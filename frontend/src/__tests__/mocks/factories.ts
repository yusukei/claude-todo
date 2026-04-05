import type { Task, User, Project, ProjectMember } from '../../types'

export function createMockTask(overrides?: Partial<Task>): Task {
  return {
    id: 'task-id-1',
    project_id: 'project-id-1',
    title: 'Test Task',
    description: null,
    status: 'todo',
    priority: 'medium',
    due_date: null,
    assignee_id: null,
    parent_task_id: null,
    task_type: 'action',
    decision_context: null,
    tags: [],
    comments: [],
    attachments: [],
    is_deleted: false,
    archived: false,
    completion_report: null,
    completed_at: null,
    needs_detail: false,
    approved: false,
    created_by: 'user-id-1',
    created_at: '2024-01-01T00:00:00Z',
    updated_at: '2024-01-01T00:00:00Z',
    sort_order: 0,
    ...overrides,
  }
}

export function createMockUser(overrides?: Partial<User>): User {
  return {
    id: 'user-id-1',
    email: 'admin@test.com',
    name: 'Admin User',
    auth_type: 'admin',
    is_active: true,
    is_admin: true,
    created_at: '2024-01-01T00:00:00Z',
    ...overrides,
  }
}

export function createMockProject(overrides?: Partial<Project>): Project {
  return {
    id: 'project-id-1',
    name: 'Test Project',
    description: 'Test description',
    color: '#6366f1',
    status: 'active',
    is_locked: false,
    members: [{ user_id: 'user-id-1', role: 'owner', joined_at: '2024-01-01T00:00:00Z' }],
    created_by: 'user-id-1',
    created_at: '2024-01-01T00:00:00Z',
    updated_at: '2024-01-01T00:00:00Z',
    ...overrides,
  }
}
