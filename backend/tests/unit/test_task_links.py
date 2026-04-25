"""Unit tests for ``app.services.task_links.has_cycle``.

Validates the BFS cycle-detection primitive used by link creation. Runs under
the conftest's mongomock-motor / Beanie fixtures — no real MongoDB required.
"""

from __future__ import annotations

import pytest
import pytest_asyncio

from app.models import Task
from app.models.task import TaskStatus
from app.services.task_links import has_cycle, has_parent_cycle


@pytest_asyncio.fixture
async def linked_project(test_project):
    """Insert a small set of tasks inside ``test_project`` for dependency tests.

    Returns a dict ``{"project_id": str, "a"|"b"|"c"|"d"|"e": Task}``. The
    tests then link them up via ``blocks`` lists and call ``has_cycle``.
    """
    pid = str(test_project.id)
    tasks = {}
    for key in ("a", "b", "c", "d", "e"):
        t = Task(
            project_id=pid,
            title=f"Task {key.upper()}",
            created_by="test",
            status=TaskStatus.todo,
        )
        await t.insert()
        tasks[key] = t
    return {"project_id": pid, **tasks}


def _set_blocks(task: Task, blocks: list[str]):
    task.blocks = blocks


async def _save(*tasks: Task):
    for t in tasks:
        await t.save()


class TestHasCycle:
    @pytest.mark.asyncio
    async def test_self_reference_is_cycle(self, linked_project):
        """A task linking to itself always forms a trivial cycle."""
        pid = linked_project["project_id"]
        a = linked_project["a"]
        path = await has_cycle(pid, str(a.id), str(a.id))
        assert path == [str(a.id)]

    @pytest.mark.asyncio
    async def test_disconnected_tasks_no_cycle(self, linked_project):
        """Two unrelated tasks with no blocks edges have no path between them."""
        pid = linked_project["project_id"]
        a, b = linked_project["a"], linked_project["b"]
        assert await has_cycle(pid, str(a.id), str(b.id)) is None

    @pytest.mark.asyncio
    async def test_forward_edge_does_not_cycle(self, linked_project):
        """A→B exists. Adding A→C should not cycle (C is fresh)."""
        pid = linked_project["project_id"]
        a, b, c = (linked_project[k] for k in ("a", "b", "c"))
        _set_blocks(a, [str(b.id)])
        await _save(a)
        assert await has_cycle(pid, str(a.id), str(c.id)) is None

    @pytest.mark.asyncio
    async def test_reverse_edge_creates_cycle(self, linked_project):
        """A→B exists. Proposing B→A closes a length-2 cycle."""
        pid = linked_project["project_id"]
        a, b = linked_project["a"], linked_project["b"]
        _set_blocks(a, [str(b.id)])
        await _save(a)
        path = await has_cycle(pid, str(b.id), str(a.id))
        assert path == [str(a.id), str(b.id)]

    @pytest.mark.asyncio
    async def test_chain_cycle_returns_full_path(self, linked_project):
        """A→B→C→D exists. Proposing D→A reveals the full chain as the cycle path."""
        pid = linked_project["project_id"]
        a, b, c, d = (linked_project[k] for k in ("a", "b", "c", "d"))
        _set_blocks(a, [str(b.id)])
        _set_blocks(b, [str(c.id)])
        _set_blocks(c, [str(d.id)])
        await _save(a, b, c)

        path = await has_cycle(pid, str(d.id), str(a.id))
        assert path == [str(a.id), str(b.id), str(c.id), str(d.id)]

    @pytest.mark.asyncio
    async def test_branching_graph_no_cycle(self, linked_project):
        """Y-shaped DAG: A→B, A→C, B→D, C→D. Proposing E→A has no cycle."""
        pid = linked_project["project_id"]
        a, b, c, d, e = (linked_project[k] for k in ("a", "b", "c", "d", "e"))
        _set_blocks(a, [str(b.id), str(c.id)])
        _set_blocks(b, [str(d.id)])
        _set_blocks(c, [str(d.id)])
        await _save(a, b, c)

        assert await has_cycle(pid, str(e.id), str(a.id)) is None

    @pytest.mark.asyncio
    async def test_branching_graph_detects_cycle_via_either_path(self, linked_project):
        """Same Y-shape: proposing D→A must cycle (D has two ancestors reaching A)."""
        pid = linked_project["project_id"]
        a, b, c, d = (linked_project[k] for k in ("a", "b", "c", "d"))
        _set_blocks(a, [str(b.id), str(c.id)])
        _set_blocks(b, [str(d.id)])
        _set_blocks(c, [str(d.id)])
        await _save(a, b, c)

        path = await has_cycle(pid, str(d.id), str(a.id))
        assert path is not None
        assert path[0] == str(a.id)
        assert path[-1] == str(d.id)
        # The intermediate hop is whichever BFS reached first (B or C); both are valid.
        assert path[1] in {str(b.id), str(c.id)}

    @pytest.mark.asyncio
    async def test_different_project_isolation(self, linked_project, admin_user):
        """Cross-project edges must not influence cycle detection."""
        from app.models import Project
        from app.models.project import ProjectMember

        other = Project(
            name="Other Project",
            color="#000000",
            created_by=admin_user,
            members=[ProjectMember(user_id=str(admin_user.id))],
        )
        await other.insert()

        foreign = Task(
            project_id=str(other.id),
            title="Foreign Task",
            created_by="test",
            blocks=[linked_project["a"].id and str(linked_project["a"].id)],
        )
        await foreign.insert()

        pid = linked_project["project_id"]
        a, b = linked_project["a"], linked_project["b"]
        # Foreign.blocks contains a.id but lives in a different project, so our
        # has_cycle scoped to ``pid`` must ignore it.
        assert await has_cycle(pid, str(b.id), str(a.id)) is None

    @pytest.mark.asyncio
    async def test_deep_chain_does_not_loop_forever(self, test_project):
        """A 12-node deep chain must resolve without infinite traversal."""
        pid = str(test_project.id)
        tasks: list[Task] = []
        for i in range(12):
            t = Task(project_id=pid, title=f"T{i}", created_by="test")
            await t.insert()
            tasks.append(t)
        # Chain: 0 → 1 → 2 → ... → 11
        for i in range(11):
            tasks[i].blocks = [str(tasks[i + 1].id)]
            await tasks[i].save()

        # Adding 11 → 0 would close the loop.
        path = await has_cycle(pid, str(tasks[11].id), str(tasks[0].id))
        assert path is not None
        assert len(path) == 12
        assert path[0] == str(tasks[0].id)
        assert path[-1] == str(tasks[11].id)

    @pytest.mark.asyncio
    async def test_deleted_tasks_excluded(self, linked_project):
        """Soft-deleted tasks must not participate in cycle detection."""
        pid = linked_project["project_id"]
        a, b = linked_project["a"], linked_project["b"]
        _set_blocks(a, [str(b.id)])
        a.is_deleted = True
        await a.save()

        # Even though A.blocks points to B, A is deleted — proposing B→A should
        # not walk through A's outgoing edges.
        assert await has_cycle(pid, str(b.id), str(a.id)) is None


def _set_parent(task: Task, parent_id: str | None):
    task.parent_task_id = parent_id


class TestHasParentCycle:
    """Cycle detection for parent reassignment (separate from blocks graph)."""

    @pytest.mark.asyncio
    async def test_self_reference_is_cycle(self, linked_project):
        """Setting a task as its own parent is a trivial cycle."""
        pid = linked_project["project_id"]
        a = linked_project["a"]
        path = await has_parent_cycle(pid, str(a.id), str(a.id))
        assert path == [str(a.id)]

    @pytest.mark.asyncio
    async def test_unrelated_top_level_no_cycle(self, linked_project):
        """Two unrelated top-level tasks can be reparented freely."""
        pid = linked_project["project_id"]
        a, b = linked_project["a"], linked_project["b"]
        # Both are top-level; making a a child of b creates no cycle.
        assert await has_parent_cycle(pid, str(a.id), str(b.id)) is None

    @pytest.mark.asyncio
    async def test_descendant_as_new_parent_creates_cycle(self, linked_project):
        """A → child B; making A a child of B creates a 2-node cycle."""
        pid = linked_project["project_id"]
        a, b = linked_project["a"], linked_project["b"]
        _set_parent(b, str(a.id))
        await _save(b)

        path = await has_parent_cycle(pid, str(a.id), str(b.id))
        assert path == [str(a.id), str(b.id)]

    @pytest.mark.asyncio
    async def test_grandchild_as_new_parent_creates_cycle(self, linked_project):
        """A → B → C → D; making A a child of D returns the full chain."""
        pid = linked_project["project_id"]
        a, b, c, d = (linked_project[k] for k in ("a", "b", "c", "d"))
        _set_parent(b, str(a.id))
        _set_parent(c, str(b.id))
        _set_parent(d, str(c.id))
        await _save(b, c, d)

        path = await has_parent_cycle(pid, str(a.id), str(d.id))
        assert path is not None
        assert path[0] == str(a.id)
        assert path[-1] == str(d.id)
        assert len(path) == 4

    @pytest.mark.asyncio
    async def test_sibling_reparenting_no_cycle(self, linked_project):
        """B and C share parent A; moving C under B is safe (no cycle)."""
        pid = linked_project["project_id"]
        a, b, c = (linked_project[k] for k in ("a", "b", "c"))
        _set_parent(b, str(a.id))
        _set_parent(c, str(a.id))
        await _save(b, c)

        assert await has_parent_cycle(pid, str(c.id), str(b.id)) is None

    @pytest.mark.asyncio
    async def test_cross_project_chain_does_not_cycle(self, linked_project, admin_user):
        """Parent chains in other projects must not affect this project's check."""
        from app.models import Project
        from app.models.project import ProjectMember

        other = Project(
            name="Other Project",
            color="#000000",
            created_by=admin_user,
            members=[ProjectMember(user_id=str(admin_user.id))],
        )
        await other.insert()

        # In the other project, build a chain that points to a's id (string id only).
        a, b = linked_project["a"], linked_project["b"]
        foreign_parent = Task(
            project_id=str(other.id),
            title="Foreign",
            created_by="test",
            parent_task_id=str(a.id),  # references a string id from another project
        )
        await foreign_parent.insert()

        pid = linked_project["project_id"]
        # Walking up from b in `pid` should not stray into the other project.
        assert await has_parent_cycle(pid, str(a.id), str(b.id)) is None

    @pytest.mark.asyncio
    async def test_deleted_ancestor_breaks_chain(self, linked_project):
        """A soft-deleted ancestor breaks the parent chain — no cycle reported."""
        pid = linked_project["project_id"]
        a, b, c = (linked_project[k] for k in ("a", "b", "c"))
        _set_parent(b, str(a.id))
        _set_parent(c, str(b.id))
        b.is_deleted = True
        await _save(b, c)

        # Walking up from c hits b (deleted) → chain breaks before reaching a.
        assert await has_parent_cycle(pid, str(a.id), str(c.id)) is None

    @pytest.mark.asyncio
    async def test_deep_chain_resolves(self, test_project):
        """A 12-node chain resolves without infinite traversal."""
        pid = str(test_project.id)
        tasks: list[Task] = []
        for i in range(12):
            t = Task(project_id=pid, title=f"T{i}", created_by="test")
            await t.insert()
            tasks.append(t)
        # Chain 0 ← 1 ← 2 ← ... ← 11 (each child points to the previous task)
        for i in range(1, 12):
            tasks[i].parent_task_id = str(tasks[i - 1].id)
            await tasks[i].save()

        # Making tasks[0] a child of tasks[11] would close the loop.
        path = await has_parent_cycle(pid, str(tasks[0].id), str(tasks[11].id))
        assert path is not None
        assert len(path) == 12
        assert path[0] == str(tasks[0].id)
        assert path[-1] == str(tasks[11].id)

    @pytest.mark.asyncio
    async def test_top_level_target_no_cycle(self, linked_project):
        """A task with no parent_task_id makes a fine new parent for anyone else."""
        pid = linked_project["project_id"]
        a, b = linked_project["a"], linked_project["b"]
        # Both are top-level (no parent set).
        assert await has_parent_cycle(pid, str(b.id), str(a.id)) is None
