---
inclusion: always
---

# MOGAM Account Manager

AWS account management and monitoring portal for managing server accounts, GitHub repositories, and cost tracking across multiple AWS regions.

## Core Features

- Server account lifecycle management (create/delete/role updates) via AWS SSM
- Role-based access control (admin/ops/user) with sudo privilege management
- GitHub organization and repository management
- User access log monitoring and audit trails
- Cost monitoring and FinOps data pipeline
- Multi-region support (us-east-1, us-west-2)
- Project group organization
- Bedrock Access Control Gateway: mediated, audited access to Amazon Bedrock with per-principal quotas and approval workflows

## Architecture

Three-tier application:
- Frontend: React SPA with Vite
- Backend: Two Flask microservices (admin, cost) + serverless Bedrock gateway
  - backend-admin: Account and GitHub management (port 5000)
  - backend-cost: Cost monitoring and FinOps (port 5001)
  - Bedrock Gateway: API Gateway (AWS_IAM) + Lambda — NOT a Flask service
- Automation: Ansible playbooks for infrastructure provisioning

## Target Users

Internal operations teams managing AWS infrastructure and user access across multiple regions and projects.
but, default infrastructure setting is us-west-2 region.