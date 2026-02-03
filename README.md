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

For the full project tree see `CLAUDE.md`. Key directories:

```
botlab/
├── docs/                        # DESIGN.md, SECURITY-ASSESSMENT.md, INTEGRATOR-BOT-PLAN.md
├── terraform/                   # Hetzner Cloud infrastructure (Terraform)
├── gitlab-admin-bot/            # AI-powered admin bot (Python, FastAPI)
│   ├── src/                     # Source code (monitors, alerting, AI, maintenance, restore)
│   └── tests/                   # Test suite (pytest)
├── scripts/                     # Deployment, backup, and recovery scripts
│   ├── seed_schema.py           # Seed config validation (Pydantic)
│   ├── seed_bootstrap.py        # Generate all downstream configs from seed.yaml
│   ├── setup-borg-backup.sh     # BorgBackup setup (interactive)
│   ├── setup-borg-append-only.sh # Append-only Borg hardening
│   ├── backup-to-s3.sh          # S3 immutable backup (Object Lock)
│   ├── restore-gitlab.sh        # DR restore procedure
│   └── verify-backup.sh         # Backup verification
├── seed.example.yaml            # Single source of truth config template
└── .github/workflows/test.yml   # CI: pytest, ruff, mypy, shellcheck, terraform
```

## Disaster Recovery

**Strategy**: 3-2-1 backup with immutable tier (no hot standby). ~1h RPO, ~1-2h RTO.

| Tier | Frequency | Retention | Protection |
|------|-----------|-----------|------------|
| Local | Hourly | 24 hours | None (staging only) |
| Borg (Storage Box) | Hourly | 12 months | Append-only (ransomware-resistant) |
| S3 (Object Lock) | Weekly | 90 days | WORM / immutable |

See `docs/DESIGN.md` Section 6 and `docs/SECURITY-ASSESSMENT.md` for details.

## Monitoring

The Admin Bot provides:

- **Health Checks**: GitLab endpoints every 30 seconds
- **Resource Monitoring**: Disk, CPU, memory
- **Backup Verification**: Weekly automated restore test
- **Alerting**: Email notifications for critical issues

Access Grafana dashboards at `http://admin-bot:3000` (internal network).

## Per-Project Bot Configuration (Planned)

> **Status**: Planned — not yet implemented. The policy file format is defined but the bot does not yet scan or enforce `.gitlab-bot.yml` files.

See `docs/DESIGN.md` Section 7.8 and `docs/INTEGRATOR-BOT-PLAN.md` Section 7 for the specification.

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
