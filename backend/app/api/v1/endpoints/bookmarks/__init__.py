"""Bookmarks endpoints package.

Splits the former 538-line ``bookmarks.py`` into focused submodules:
- ``_shared``     — schemas + project-access helpers
- ``collections`` — bookmark collection CRUD (exposes ``coll_router``)
- ``items``       — bookmark CRUD + batch + clip + reorder + import
                    (exposes ``bm_router``)

Two separate routers are exposed at package level because the callers
(``app/main.py`` and ``tests/conftest.py``) already mount them under
different URL prefixes — there is no single aggregating router here.
"""
from __future__ import annotations

from .collections import coll_router
from .items import bm_router

__all__ = ["coll_router", "bm_router"]
