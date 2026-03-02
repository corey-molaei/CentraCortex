# CentraCortex Business Process Document (BPD)

## 1. Document Control

- Document Name: `CentraCortex Business Process Document`
- Version: `1.0`
- Status: `Approved Baseline`
- Effective Date: `2026-02-19`
- System Scope: `CentraCortex (Modules 0-9)`

## 2. Purpose

This document defines the operational business processes required to run CentraCortex as a secure multi-tenant SaaS product, including tenant onboarding, identity and access governance, data ingestion, retrieval/chat operations, agent lifecycle management, and compliance/governance workflows.

## 3. Objectives

- Standardize end-to-end service delivery across product, engineering, support, and security teams.
- Ensure tenant isolation, ACL enforcement, and auditability in all user and admin workflows.
- Define operational controls, service targets, and escalation paths.
- Provide a repeatable process framework for onboarding and scale.

## 4. Stakeholders and Roles

- `Platform Owner`: product and roadmap ownership.
- `Tenant Owner`: customer-side accountable admin.
- `Tenant Admin`: manages users, roles, connectors, and policies.
- `End User`: searches knowledge, chats, runs approved agents.
- `Security Officer`: governance, approvals, and security review.
- `Support Engineer`: incident triage and customer support.
- `Data Steward`: validates data-source quality and permissions.

## 5. Process Catalog

1. Tenant Onboarding and Environment Provisioning
2. Identity, Session, and Tenant Context Management
3. RBAC/Group/ACL Administration
4. LLM Provider Configuration and Routing Governance
5. Connector Onboarding and Sync Operations
6. Document Lifecycle (Ingest, Index, Retrieve, Delete/Forget)
7. Chat and Retrieval Operations
8. Agent Execution and Risk Approval Workflow
9. No-Code Agent Builder Lifecycle (Draft, Test, Deploy, Rollback)
10. Audit, Governance, Security Monitoring, and Incident Response

## 6. End-to-End Process Flows

## 6.1 Tenant Onboarding and Provisioning

- Trigger: New customer contract or internal tenant request.
- Inputs: tenant name, slug, initial owner email, compliance profile.
- Steps:
  1. Platform Owner creates tenant record.
  2. Platform script provisions tenant resources (including Qdrant collection).
  3. Initial Tenant Owner account is created and activated.
  4. Baseline roles, groups, and default ACL policies are seeded.
  5. Audit entry is written for each provisioning action.
- Outputs: active tenant, owner access, isolated data/index/storage namespace.
- SLA: tenant provisioning completed within `1 business day`.

## 6.2 Identity, Session, and Tenant Context

- Trigger: user login, token refresh, tenant switch, password reset.
- Steps:
  1. User authenticates with email/password and receives access + refresh tokens.
  2. User selects tenant context when multiple memberships exist.
  3. APIs validate JWT type, expiry, and tenant membership on each request.
  4. Password reset requests issue time-bound reset tokens.
- Controls:
  - Access tokens are short-lived.
  - Refresh tokens are tracked and revocable.
  - All auth flows generate audit events.
- KPI: authentication success rate >= `99.9%` monthly.

## 6.3 Access Governance (RBAC + Groups + ACL)

- Trigger: user invite, role/group assignment, policy creation/update.
- Steps:
  1. Tenant Admin invites user and assigns tenant role.
  2. Admin assigns user to one or more groups.
  3. Admin configures ACL policies for document/tool/data-source access.
  4. Retrieval and tool runtime enforce ACLs before action execution.
- Outputs: least-privilege access model per tenant.
- Controls:
  - Admin-only endpoints for role/group/policy management.
  - Policy changes are fully audited.
- KPI: unauthorized access attempts blocked = `100%`.

## 6.4 LLM Provider Management

- Trigger: tenant AI setup or model policy update.
- Steps:
  1. Tenant Admin adds provider credentials (OpenAI/local vLLM/Ollama).
  2. System encrypts and stores credentials.
  3. Admin runs connection test.
  4. Admin assigns default and fallback models/providers.
  5. Router enforces per-tenant rate limits and failover.
  6. Calls are logged with tokens/latency/cost metadata when available.
- Controls:
  - Credentials encrypted at rest.
  - Provider changes and test actions audited.
- KPI: failover success for provider outages >= `99%`.

## 6.5 Connector Onboarding and Sync Operations

- Trigger: tenant enables a data source.
- Connectors in scope:
  - Jira, Slack, Email, GitHub/GitLab, Confluence, SharePoint/Graph, DB read-only, Logs, File upload.
- Steps:
  1. Tenant Admin completes connector-specific setup wizard.
  2. Credentials are stored securely per tenant.
  3. Admin selects projects/channels/repos/folders/tables.
  4. Initial sync runs and stores cursor state.
  5. Scheduled incremental sync runs via worker scheduler.
  6. Sync status/errors are visible in UI and audit log.
- Outputs: normalized documents with source metadata and ACL binding.
- SLA: sync failure acknowledged within `30 minutes` during support window.

## 6.6 Document Lifecycle

- Trigger: connector sync or manual upload.
- Steps:
  1. Raw source artifact stored in MinIO under tenant scope.
  2. Normalized document record created in Postgres.
  3. Chunking/indexing service generates versioned chunks.
  4. Embeddings stored in tenant-specific Qdrant collection.
  5. BM25/text index data persisted in Postgres.
  6. Reindex and delete/forget workflows are available.
- Controls:
  - No embedding or indexing outside tenant boundary.
  - All chunks retain ACL metadata.
- KPI: median ingest-to-searchability time <= `5 minutes` for standard payloads.

## 6.7 Retrieval and Chat Operations

- Trigger: user chat/query request.
- Steps:
  1. Input is screened by safety filters (prompt injection/exfil patterns).
  2. Hybrid retrieval runs (vector + BM25) with ACL filtering.
  3. LLM router selects tenant provider/model (with fallback).
  4. Response is generated with citations and source snippets.
  5. Conversation history and user feedback are stored.
- Outputs: grounded answer with traceable sources.
- KPI:
  - citation coverage >= `95%` for knowledge-grounded answers
  - blocked unsafe prompts reviewed daily.

## 6.8 Agent Runtime and Risk Approvals

- Trigger: user executes agent task.
- Steps:
  1. RouterAgent selects specialist path (knowledge/comms/ops/sql/guard).
  2. Tool permissions are checked against tenant ACL policies.
  3. Risky actions require approval queue decision before execution.
  4. Execution trace captures steps and tool calls (with redaction as needed).
  5. Outcome and trace are stored for audit and diagnostics.
- Controls:
  - approval gate for high-risk tool actions.
  - full run and decision audit trail.
- KPI: `100%` of high-risk actions have an explicit approval record.

## 6.9 No-Code Agent Builder Lifecycle

- Trigger: tenant builds or updates a custom agent.
- Steps:
  1. Admin provides prompt, tools, data sources, risk level, and style examples.
  2. System generates strict AgentSpec JSON.
  3. Auto-generated test suite validates behavior and guardrails.
  4. Version is promoted from draft to deployed after review.
  5. Rollback can revert to a previous deployed version.
- Outputs: governed, versioned, test-backed tenant agent definitions.
- KPI: rollback completion time <= `10 minutes`.

## 6.10 Governance, Audit, and Incident Response

- Trigger: compliance review, alert, policy breach, or support escalation.
- Steps:
  1. Security Officer filters audit logs by tenant/user/event/tool/time.
  2. Governance queue reviews pending risky actions.
  3. Logs are exported for compliance/legal workflows when needed.
  4. Incident runbook is executed (containment, analysis, remediation, postmortem).
- Controls:
  - rate limits, security headers, optional request signing.
  - immutable audit trail for privileged actions.
- SLA: critical incident triage starts within `15 minutes`.

## 7. RACI Matrix (Summary)

- Tenant Onboarding:
  - Responsible: `Platform Owner`
  - Accountable: `Platform Owner`
  - Consulted: `Security Officer`, `Support Engineer`
  - Informed: `Tenant Owner`
- Access Governance:
  - Responsible: `Tenant Admin`
  - Accountable: `Tenant Owner`
  - Consulted: `Security Officer`
  - Informed: `End Users`
- Connector and Data Operations:
  - Responsible: `Tenant Admin`, `Data Steward`
  - Accountable: `Tenant Owner`
  - Consulted: `Support Engineer`
  - Informed: `End Users`
- Agent and Governance Operations:
  - Responsible: `Tenant Admin`, `Security Officer`
  - Accountable: `Tenant Owner`
  - Consulted: `Platform Owner`
  - Informed: `Support Engineer`

## 8. Controls and Compliance Mapping

- Identity and session controls:
  - JWT validation, refresh token lifecycle, password reset token expiry.
- Access controls:
  - RBAC + group + ACL enforcement in admin APIs, retrieval, and tools.
- Data controls:
  - tenant isolation in Postgres/Qdrant/MinIO.
  - source metadata and ACL binding persisted on ingestion.
- Operational controls:
  - audit logging on privileged operations.
  - approval workflow for high-risk tools.
  - rate limiting and secure HTTP headers.

## 9. Operational Metrics

- Availability and reliability:
  - API uptime
  - worker success/failure rate
  - sync success rate by connector
- Security and governance:
  - unauthorized access attempts blocked
  - approval queue volume and latency
  - incident response MTTA/MTTR
- Data and AI quality:
  - indexing latency
  - citation coverage
  - unsafe prompt detection rate

## 10. Escalation Paths

- P1 security incident:
  - Security Officer + Platform Owner paged immediately.
  - Tenant Owner notified within `30 minutes`.
- P2 service degradation:
  - Support Engineer triages.
  - Platform Owner engaged if SLA risk is detected.
- Data quality incident:
  - Data Steward validates source mappings and connector state.
  - Tenant Admin informed with remediation plan.

## 11. Governance Cadence

- Daily:
  - review failed sync jobs and high-risk approval queue.
- Weekly:
  - audit sampling of privileged actions and policy changes.
- Monthly:
  - access recertification (roles/groups/policies), KPI review, control effectiveness review.
- Quarterly:
  - incident simulation and security hardening review.

## 12. References

- `docs/technical-design.md`
- `docs/security-secrets.md`
- `docs/module-0.md`
- `docs/module-1.md`
- `docs/module-2.md`
- `docs/module-3.md`
- `docs/module-4.md`
- `docs/module-5.md`
- `docs/module-6.md`
- `docs/module-7.md`
- `docs/module-8.md`
- `docs/module-9.md`
