# Module 2 - RBAC, Groups, Fine-Grained ACL Policies

## Implemented Scope

### Data model + migration

Added full schema and Alembic migration (`20260217_0002_rbac_acl`) for:

- `roles` (system + custom)
- `groups`
- `group_memberships`
- `user_role_assignments`
- `acl_policies`
- `invitations`
- `documents` (ACL-bound retrieval target)
- `tool_definitions`

### API endpoints

#### Users and assignments

- `GET /api/v1/admin/users?q=&role=`
- `POST /api/v1/admin/users/invite`
- `GET /api/v1/admin/users/{user_id}`
- `POST /api/v1/admin/users/{user_id}/groups`
- `POST /api/v1/admin/users/{user_id}/roles`

#### Groups

- `GET /api/v1/admin/groups`
- `POST /api/v1/admin/groups`
- `GET /api/v1/admin/groups/{group_id}`
- `PATCH /api/v1/admin/groups/{group_id}`
- `DELETE /api/v1/admin/groups/{group_id}`
- `GET /api/v1/admin/groups/{group_id}/members`

#### Roles

- `GET /api/v1/admin/roles`
- `POST /api/v1/admin/roles`

#### Policies

- `GET /api/v1/admin/policies?policy_type=`
- `POST /api/v1/admin/policies`
- `PATCH /api/v1/admin/policies/{policy_id}`
- `DELETE /api/v1/admin/policies/{policy_id}`

#### Enforcement points

- Retrieval ACL: `GET /api/v1/retrieval/documents`
- Tool ACL: `POST /api/v1/tools/{tool_name}/execute`

### Enforcement details

- Every admin endpoint requires tenant context and admin-like role (`Owner`, `Admin`, or `Manager`).
- Retrieval checks document policies before returning documents.
- Tool execution checks tool policies before executing.
- Admin actions and policy-governed tool execution are audit logged in `audit_logs`.

### UI pages (separate, non-generic)

- `/admin/users` (search/filter/invite)
- `/admin/users/:userId` (roles/groups assignments)
- `/admin/groups` (CRUD entry + listing)
- `/admin/groups/:groupId` (detail + members)
- `/admin/roles` (system/custom roles)
- `/admin/policies` (document/tool/data-source policies)

### Tests

`backend/tests/test_rbac_acl.py` covers:

- Role/group creation
- User-group + user-role assignment
- ACL policy-driven retrieval filtering
- ACL policy-driven tool execution allow/deny
