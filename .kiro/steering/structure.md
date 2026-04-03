---
inclusion: always
---

# Project Structure

## Root Organization

```
/
├── account-portal/          # Web application
├── ansible/                 # Infrastructure automation
└── README.md
```

## Account Portal Structure

```
account-portal/
├── frontend/                # React SPA
│   ├── src/
│   │   ├── pages/          # Route components
│   │   ├── components/     # Reusable UI components
│   │   ├── api.js          # API client
│   │   └── main.jsx        # Entry point
│   ├── dist/               # Build output
│   └── package.json
│
├── backend-admin/          # Admin microservice
│   ├── routes/             # Flask blueprints
│   ├── services/           # Business logic (GitHub, etc)
│   ├── data/               # Static data (mappings.json)
│   ├── logs/               # Application logs
│   ├── app.py              # Flask app entry
│   └── requirements.txt
│
├── backend-cost/           # Cost monitoring microservice
│   ├── routes/             # Flask blueprints
│   ├── utils/              # Utilities (exchange rates, etc)
│   ├── agent/              # Cost collection agent
│   ├── data/               # Static data
│   └── app.py
│
├── backend-gateway/        # Reserved — NOT a Flask service
│   └── (empty, gateway is serverless: API Gateway + Lambda)
│   └── See infra/bedrock-gateway/ for Terraform + Lambda code
│
├── nginx/                  # Reverse proxy config
└── docker-compose-fixed.yml
```

## Ansible Structure

```
ansible/
├── regions/                # Region-specific configs
│   ├── template_region/   # Template for new regions
│   ├── us-east-1/
│   └── us-west-2/
│       ├── playbooks/      # Region playbooks
│       ├── group_vars/     # Region variables
│       └── files/          # Region-specific files (sudoers)
│
├── roles/                  # Reusable Ansible roles
│   ├── identity_center/   # SSO user management
│   └── ssm/               # SSM automation tasks
│
├── ssm_automation/         # AWS SSM documents
│   ├── documents/         # SSM automation YAML
│   └── scripts/           # Upload scripts
│
├── cost_monitoring/        # Cost pipeline infrastructure
│   ├── infrastructure/    # Terraform, Lambda, Athena DDL
│   ├── agent/             # Cost collection agent
│   └── files/             # Config and deployment files
│
└── *.yml                   # Top-level playbooks
```

## Key Conventions

### Backend Routes
- Each feature has its own blueprint in `routes/`
- Blueprints registered in `app.py`
- URL prefix pattern: `/api/<feature>`

### Frontend Pages
- One file per route in `src/pages/`
- Backup files use `.bak` or timestamp suffixes
- Layout wrapper in `components/Layout.jsx`

### Ansible Playbooks
- Region-specific playbooks in `regions/<region>/playbooks/`
- Shared roles in `roles/`
- Group variables in `group_vars/`
- Inventory files per region

### Docker Volumes
- Ansible directory mounted read-write to backend-admin
- AWS credentials mounted read-only from host
- Application data in service-specific `data/` directories

### Logging
- Backend logs in `logs/` directories
- Audit logs in JSON format (audit_logs.json, task_logs.json)
- Auth logs mounted from host system
