# ACME Corp GitLab Infrastructure

Self-hosted GitLab CE on Hetzner Cloud with automated monitoring and disaster recovery.

## Overview

| Attribute | Value |
|-----------|-------|
| **Scale** | 10-20 developers |
| **Features** | Git LFS, Azure AD SSO, CI/CD |
| **Hosting** | Hetzner Cloud (EU) |
| **Cost** | ~70 EUR/month |
| **RTO** | ~1-2 hours |
| **RPO** | ~1 hour (hourly backups) |

## Architecture

```
                         Internet
                            │
                      ┌─────▼─────┐
                      │    DNS    │
                      │    /LB    │
                      └─────┬─────┘
                            │
              ┌─────────────┼─────────────┐
              │             │             │
         ┌────▼────┐   ┌────▼────┐   ┌────▼────┐
         │ GitLab  │   │  Admin  │   │ Object  │
         │ Primary │◄──│   Bot   │   │ Storage │
         │ (CPX31) │   │ (CX32)  │   │  (S3)   │
         └────┬────┘   └────┬────┘   └─────────┘
              │             │
         ┌────▼─────────────▼────┐
         │    Private Network    │
         │      10.0.0.0/16      │
         └───────────┬───────────┘
                     │
              ┌──────▼──────┐
              │ Storage Box │
              │  (Backups)  │
              │   BX21 5TB  │
              └─────────────┘
```

## Technology Stack

All components are **100% open source** (no license fees).

| Component | Technology | License |
|-----------|------------|---------|
| Version Control | GitLab CE | MIT |
| Infrastructure | Terraform | MPL 2.0 |
| Admin Bot | Python, FastAPI | MIT |
| Backups | BorgBackup | BSD |
| Monitoring | Prometheus + Grafana | Apache 2.0 |

## Quick Start

### Prerequisites

- Hetzner Cloud account
- Terraform >= 1.0
- Python >= 3.12
- Azure AD tenant (for SSO)

### Deploy Infrastructure

```bash
cd terraform
cp terraform.tfvars.example terraform.tfvars
# Edit terraform.tfvars with your values

terraform init
terraform plan
terraform apply
```

### Install GitLab

SSH to the provisioned server and run:

```bash
curl https://packages.gitlab.com/install/repositories/gitlab/gitlab-ce/script.deb.sh | sudo bash
sudo EXTERNAL_URL="https://gitlab.example.com" apt-get install gitlab-ce
```

See `docs/DESIGN.md` for complete configuration.

### Deploy Admin Bot

```bash
cd gitlab-admin-bot
docker compose up -d
```

## Project Structure

```
botlab/
├── README.md                    # This file
├── CLAUDE.md                    # AI assistant guidance
├── TODO.md                      # Implementation status and task tracking
├── docs/
│   ├── DESIGN.md                # Master design document
│   ├── SECURITY-ASSESSMENT.md   # Security & DR analysis
│   └── INTEGRATOR-BOT-PLAN.md   # Claude Code CLI bot architecture
├── terraform/                   # Infrastructure as code
│   ├── versions.tf              # Provider versions
│   ├── variables.tf             # Input variables
│   ├── provider.tf              # Hetzner provider
│   ├── network.tf               # VPC and subnets
│   ├── servers.tf               # Compute instances
│   ├── storage.tf               # Block volumes
│   ├── load_balancer.tf         # Load balancer
│   ├── firewalls.tf             # Firewall rules
│   ├── ssh_keys.tf              # SSH key management
│   ├── outputs.tf               # Output values
│   ├── terraform.tfvars.example # Configuration template
│   └── templates/               # Cloud-init templates
│       └── gitlab-cloud-init.yaml
├── gitlab-admin-bot/            # AI-powered admin bot
│   ├── src/
│   │   ├── main.py              # Entry point
│   │   ├── config.py            # Configuration
│   │   ├── scheduler.py         # APScheduler
│   │   ├── ai/                  # Claude API integration
│   │   ├── monitors/            # Health, resource, backup monitors
│   │   ├── alerting/            # Alert management
│   │   ├── maintenance/         # Maintenance tasks
│   │   ├── restore/             # DR automation
│   │   └── utils/               # SSH, GitLab API clients
│   ├── tests/                   # Test suite
│   │   ├── conftest.py          # Shared fixtures
│   │   ├── test_monitors.py     # Monitor tests
│   │   ├── test_alerting.py     # Alert manager tests
│   │   ├── test_ai_analyst.py   # AI integration tests
│   │   └── test_recovery.py     # Recovery tests
│   ├── config/config.yaml       # Configuration template
│   ├── .env.example             # Environment variables template
│   ├── Dockerfile
│   └── docker-compose.yml
├── scripts/                     # Utility scripts
│   ├── gitlab-setup.sh          # GitLab installation
│   ├── gitlab.rb.template       # GitLab configuration
│   ├── setup-borg-backup.sh     # Backup setup (interactive)
│   ├── verify-backup.sh         # Backup verification (--json, --quiet)
│   └── restore-gitlab.sh        # DR restore procedure
├── .github/workflows/           # CI/CD
│   └── test.yml                 # pytest, ruff, mypy, shellcheck, terraform
├── Makefile                     # Development commands (make help)
└── .pre-commit-config.yaml      # Pre-commit hooks
```

## Disaster Recovery

**Strategy**: Backup-based recovery (no hot standby)

| Metric | Target |
|--------|--------|
| RPO | ~1 hour (hourly backups to Storage Box) |
| RTO | ~1-2 hours (provision + restore) |

**Backup Schedule**:
- Hourly: GitLab backup to local staging
- Every 4 hours: Sync to Storage Box (encrypted with BorgBackup)
- Daily: Full consistency check

**Recovery Procedure**:
1. Provision new CPX31 via Terraform
2. Install GitLab CE
3. Restore from latest BorgBackup
4. Update DNS
5. Verify services

See `docs/DESIGN.md` Section 6 for detailed procedures.

## Monitoring

The Admin Bot provides:

- **Health Checks**: GitLab endpoints every 30 seconds
- **Resource Monitoring**: Disk, CPU, memory
- **Backup Verification**: Weekly automated restore test
- **Alerting**: Email notifications for critical issues

Access Grafana dashboards at `http://admin-bot:3000` (internal network).

## Per-Project Bot Configuration

Projects can customize bot behavior via `.gitlab-bot.yml` files:

```yaml
# .gitlab-bot.yml - Optional per-project configuration
version: 1
owners:
  primary: team-lead@example.com
monitors:
  stale_branches: { enabled: true, max_age_days: 30 }
  ci_failures: { alert_after_consecutive: 3 }
compliance:
  require_code_review: true
  min_approvers: 1
```

See `docs/DESIGN.md` Section 7.8 for full specification.

## Documentation

| Document | Description |
|----------|-------------|
| [DESIGN.md](docs/DESIGN.md) | Complete technical specification (master document) |
| [SECURITY-ASSESSMENT.md](docs/SECURITY-ASSESSMENT.md) | Security & ransomware protection analysis |
| [INTEGRATOR-BOT-PLAN.md](docs/INTEGRATOR-BOT-PLAN.md) | Claude Code CLI-based Integrator Bot architecture |
| [CLAUDE.md](CLAUDE.md) | AI assistant instructions |

## Cost Breakdown

Server types are configurable in `terraform/terraform.tfvars`. Default sizing:

| Resource | Specification | EUR/month |
|----------|---------------|-----------|
| GitLab Server | CPX31 (4 vCPU, 16GB RAM)* | ~18 |
| Admin Bot | CX32 (4 vCPU, 8GB RAM)* | ~7 |
| Block Storage | 300 GB* | ~13 |
| Object Storage | ~2 TB | ~10 |
| Storage Box | BX21 (5 TB) | ~16 |
| Load Balancer | LB11 | ~6 |
| **Total** | | **~70** |

*Configurable via Terraform variables. See `terraform/variables.tf` for options.

## License

Infrastructure code and admin bot are proprietary to ACME Corp.

GitLab CE, Terraform, and other tools retain their original open source licenses.
