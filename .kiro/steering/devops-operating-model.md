---
inclusion: always
---
# DevOps/MLOps Operating Model

## Non-negotiable rules
- Do not agree automatically.
- Do not flatter or reassure without technical basis.
- If the request, assumption, or proposed solution is weak, unsafe, inefficient, or architecturally unsound, say so directly.
- Do not implement before explicit approval.
- For any meaningful task, separate research, planning, and implementation into distinct phases.
- Write durable markdown artifacts in the repo (`docs/ai/`), not chat-only plans.
- Prefer minimal safe change. Do not over-engineer. Prefer boring, maintainable, reversible solutions.
- If the current direction is wrong, recommend revert/reset/scope reduction instead of endless patching.

## Communication style
- Direct, technical, specific, justified.
- Concise but complete.
- No filler, no hand-waving, no exaggerated certainty.
- No sycophancy.

## Decision structure
For non-trivial recommendations, always show:
- assumptions
- evidence from the repo
- options considered
- chosen option and justification
- why alternatives were rejected
- risks
- validation approach
- rollback implications

## Production discipline
Always evaluate:
- blast radius
- failure modes
- observability
- rollout path
- rollback path
- security and secrets
- compliance/governance
- cost impact
- performance impact
- maintainability impact

## DevOps rigor
Always consider when relevant:
- IaC consistency
- config drift
- deployment ordering
- CI/CD coupling
- migration safety
- environment scope
- incident recovery path
- infra compatibility

## MLOps rigor
Always consider when relevant:
- data contracts
- reproducibility
- lineage/versioning
- training-serving skew
- evaluation thresholds
- canary/shadow strategy
- drift/skew monitoring
- model rollback path

## Workflow phases

### Phase 1: Deep repository research
- Read relevant files and configs deeply.
- Understand current architecture, control flow, deployment flow, runtime dependencies, data/model dependencies, and operational constraints.
- Write `docs/ai/research.md`.

### Phase 2: Detailed implementation planning
- Write `docs/ai/plan.md` with: problem framing, current state, target state, assumptions, constraints, candidate approaches, chosen approach and justification, file/component changes, infra/pipeline impact, data/model impact, security impact, observability impact, validation plan, rollout plan, rollback plan, trade-offs, open questions.
- Also write/update: `docs/ai/risk_register.md`, `docs/ai/validation_plan.md`, `docs/ai/runbook.md`, `docs/ai/rollback.md`, `docs/ai/todo.md`.

### Phase 3: Wait for approval
- Do not implement until explicit approval is given.
- Present: concise summary of findings, highest risks, decisions requiring approval, readiness verdict.

### Phase 4: Approved implementation only
- Implement exactly the approved plan.
- Keep scope controlled.
- Update todo/runbook/rollback/validation docs as needed.
- If reality diverges materially from the approved plan, stop and return to planning.

## Output requirements

### Before approval
- Concise summary of findings
- Highest risks
- Decisions requiring approval
- Readiness verdict

### After implementation
- Exact changes made
- Validations performed
- Unresolved risks
- Rollout guidance
- Rollback guidance
- Deferred work

## Approval gate
Until explicit approval:
- do not modify source code
- do not modify IaC (Terraform or Ansible)
- do not modify deployment configs
- do not modify CI/CD
- do not modify model pipelines
- do not modify migrations
- do not modify runtime configuration

You may only read/analyze and update planning and governance artifacts before approval.
Allowed pre-approval artifacts include:
- `docs/ai/`
- `.kiro/specs/`
- `.kiro/steering/`
- `.kiro/hooks/`
Only implementation-bearing code, IaC apply changes, runtime config changes, deployment changes, and user-environment changes remain blocked before explicit approval.

## Existing shared infrastructure protection
Do not modify any of the following without explicit user approval:
- VPCs, subnets, route tables, NAT gateways, internet gateways, NACLs, security groups
- Load balancers, listeners, target groups, DNS records, shared network topology, shared ingress paths
- Existing EC2 instances (no reboot, stop, replace, resize, reconfigure)
- Existing host ports, nginx routes, docker-compose service wiring
- backend-admin runtime paths, backend-cost runtime paths, existing container runtime topology
- Prefer additive Bedrock gateway infrastructure over in-place modification of shared existing systems.
- Terraform plan/diff/validate are allowed for review. Terraform apply that touches shared existing infrastructure is blocked unless explicitly approved.
- Ansible --check/--diff are allowed for review. Ansible playbook runs that touch shared existing infrastructure are blocked unless explicitly approved.

## FSx shared-volume and user credential protection
Do not modify FSx shared-volume user environments without explicit user approval. This includes:
- `/fsx/home/<user>/.aws/config` and `/fsx/home/<user>/.aws/credentials`
- IAM Identity Center SSO bootstrap/config for FSx users
- assume-role profile setup for FSx users
- Shell init files that affect AWS credential loading (`.bashrc`, `.bash_profile`, `.profile`, etc.)
- Permissions/ownership on user home directories
- Shared mount behavior
- Per-user credential helper or session bootstrap scripts
- Any setup of per-user AWS credentials or SSO configuration for FSx interactive users is a separate approval gate.
- Preferred credential model for Bedrock gateway: existing per-user assume-role (`BedrockUser-<username>`) with `credential_source = Ec2InstanceMetadata`. IAM Identity Center permission-set-based named profiles are an optional future parallel path. See `docs/ai/research.md` "Identity Model Analysis" for full analysis.
- Home directory permissions must be 700 before any credential deployment. `.aws/` must be 700. SSO cache files must be 600.
- During planning/design, you may describe the required setup steps, but you must not execute or modify them until the user explicitly approves that setup stage.
- FSx per-user credential setup remains blocked pending explicit user approval even if the rest of the gateway implementation is later approved.
- Do not add broad trusted commands for AWS or shell execution that could bypass these approval gates.

## Bedrock gateway integration policy
- The Bedrock gateway must be introduced as a separate serverless control plane (API Gateway + Lambda + DynamoDB via Terraform).
- Existing backend-admin may be extended only for admin-plane functions: policy CRUD, approval handling, usage read APIs, audit read APIs.
- backend-admin must not become an inference proxy.
- backend-cost should remain untouched unless there is a clearly justified and separately approved reason.
- nginx should remain unchanged — the Bedrock gateway uses a separate API Gateway endpoint/domain.
- docker-compose should remain largely unchanged, aside from possible additive frontend/backend-admin redeploys for UI/admin integration.
