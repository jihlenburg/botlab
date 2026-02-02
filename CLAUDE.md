# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

ACME Corp GitLab infrastructure on Hetzner Cloud with AI-powered admin bot.

## Architecture Documents

**Read these documents in order for full context:**

| Document | Purpose | Priority |
|----------|---------|----------|
| `docs/DESIGN.md` | **Master design document** - authoritative specification | READ FIRST |
| `docs/SECURITY-ASSESSMENT.md` | Cybersecurity analysis, ransomware protection, DR edge cases | Security |
| `docs/INTEGRATOR-BOT-PLAN.md` | Claude Code CLI-based Integrator Bot architecture | Bot Evolution |

All implementation decisions must align with DESIGN.md. If changes are needed, update DESIGN.md first.

## Key Constraints

- **Open Source Only**: No commercial software licenses
- **Backup-based DR**: ~1 hour RPO, ~1-2 hour RTO (no hot standby)
- **Infrastructure**: Hetzner Cloud (~70 EUR/month)
- **3-2-1 Backup Strategy**: Borg (append-only) + S3 (Object Lock) for ransomware resistance

## Architecture Summary

```
GitLab Primary (CPX31, Falkenstein)
    ↑ monitors
Admin Bot (CX32) → hourly backups → Storage Box (BX21)
                                  → S3 Immutable (weekly)

Recovery: Terraform provision + BorgBackup restore (~1-2 hours)
```

## Technology Stack

| Component | Technology |
|-----------|------------|
| GitLab | CE (Community Edition) |
| Infrastructure | Terraform + Hetzner Cloud |
| Admin Bot | Python 3.12, FastAPI, APScheduler |
| Integrator Bot | Claude Code CLI + MCP servers (future) |
| Backups | BorgBackup (append-only) + S3 (Object Lock) |
| Monitoring | Prometheus + Grafana |

## Multi-Repository Policy System

Projects can define bot behavior via `.gitlab-bot.yml` files:

```yaml
# .gitlab-bot.yml - Per-project bot configuration
version: 1
owners:
  primary: alice@example.com
monitors:
  stale_branches: { enabled: true, max_age_days: 30 }
  ci_failures: { alert_after_consecutive: 3 }
automations:
  cleanup_merged_branches: true
  auto_merge: false  # Always disabled by default
compliance:
  require_code_review: true
  min_approvers: 1
context:
  bot_instructions: BOT-RESPONSIBILITIES.md
```

See DESIGN.md Section 7.8 and INTEGRATOR-BOT-PLAN.md Section 7 for full specification.

## Project Structure

```
botlab/
├── CLAUDE.md                       # This file (AI assistant guidance)
├── README.md                       # Project overview and quick start
├── TODO.md                         # Implementation status and task tracking
├── docs/
│   ├── DESIGN.md                   # Master design document (READ FIRST)
│   ├── SECURITY-ASSESSMENT.md      # Security & ransomware analysis
│   └── INTEGRATOR-BOT-PLAN.md      # Claude Code CLI bot architecture
├── terraform/                      # Infrastructure as code
│   ├── *.tf                        # Hetzner Cloud resources
│   ├── terraform.tfvars.example    # Example configuration (copy to terraform.tfvars)
│   └── templates/                  # Cloud-init templates
├── gitlab-admin-bot/               # Admin bot Python project
│   ├── src/                        # Source code
│   │   ├── monitors/               # Health, resource, backup monitors
│   │   ├── alerting/               # Alert management
│   │   ├── restore/                # DR recovery automation
│   │   ├── maintenance/            # Maintenance tasks
│   │   ├── ai/                     # Claude API integration
│   │   └── utils/                  # SSH, GitLab API clients
│   ├── tests/                      # Test suite (pytest)
│   ├── config/                     # Configuration templates
│   ├── .env.example                # Environment variables template
│   ├── Dockerfile
│   └── docker-compose.yml
├── scripts/                        # Deployment and maintenance scripts
│   ├── setup-borg-backup.sh        # BorgBackup setup
│   ├── restore-gitlab.sh           # DR restore procedure
│   └── verify-backup.sh            # Backup verification
├── .github/workflows/              # CI/CD pipeline
│   └── test.yml                    # pytest, ruff, mypy, shellcheck, terraform
├── Makefile                        # Common development commands
└── .pre-commit-config.yaml         # Pre-commit hooks configuration
```

## Development Commands

```bash
# Terraform
cd terraform && terraform init
terraform plan
terraform apply

# Admin Bot
cd gitlab-admin-bot
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest

# Docker
docker compose up -d
```

## Implementation Phases

1. **Infrastructure** (Week 1): Terraform, server, network
2. **GitLab Primary** (Week 2): GitLab CE, SSO, LFS
3. **Backup System** (Week 3): Hourly backups, BorgBackup, 3-2-1 strategy
4. **Admin Bot** (Weeks 4-6): Monitoring, alerts, restore testing
5. **Security Hardening** (Week 6): Append-only Borg, S3 immutable backups
6. **Testing** (Week 7): DR drill, documentation

## Before Making Changes

1. **Read `docs/DESIGN.md`** for the authoritative specification
2. **Read `docs/SECURITY-ASSESSMENT.md`** for security requirements
3. Ensure changes align with the design decisions
4. Update DESIGN.md if architectural changes are needed
5. All infrastructure changes go through Terraform

## Key Decisions Reference

| Decision | Choice | Document Section |
|----------|--------|------------------|
| Backup Strategy | 3-2-1 with immutable tier | DESIGN.md 6.3.3, SECURITY-ASSESSMENT.md 3.3 |
| Ransomware Protection | Append-only Borg + S3 WORM | DESIGN.md 9, SECURITY-ASSESSMENT.md 3 |
| Bot Architecture | Claude Code CLI + MCP | INTEGRATOR-BOT-PLAN.md |
| Project Policies | Per-repo .gitlab-bot.yml | DESIGN.md 7.8, INTEGRATOR-BOT-PLAN.md 7 |
| DR Automation | Human-in-the-loop approval | INTEGRATOR-BOT-PLAN.md 6.6 |

## Key Files

| File | Purpose |
|------|---------|
| `docs/DESIGN.md` | Master design document (READ FIRST) |
| `docs/SECURITY-ASSESSMENT.md` | Security analysis and recommendations |
| `docs/INTEGRATOR-BOT-PLAN.md` | Integrator Bot architecture plan |
| `terraform/*.tf` | Infrastructure definitions |
| `terraform/terraform.tfvars.example` | Configuration template with documentation |
| `terraform/templates/gitlab-cloud-init.yaml` | Server bootstrap configuration |
| `gitlab-admin-bot/src/main.py` | Bot entry point |
| `gitlab-admin-bot/config/config.yaml` | Bot configuration |
| `scripts/setup-borg-backup.sh` | BorgBackup initialization |
| `scripts/restore-gitlab.sh` | Disaster recovery procedure |
| `TODO.md` | Implementation status and task tracking |
| `.gitlab-bot.yml` (per-project) | Project-specific bot policies |

## Documentation Maintenance

**IMPORTANT: Keep documentation in sync with implementation.**

When making changes to this project, update the relevant documentation:

| Change Type | Documents to Update |
|-------------|---------------------|
| Architecture changes | `docs/DESIGN.md` (authoritative), then `README.md` |
| Security changes | `docs/SECURITY-ASSESSMENT.md`, `docs/DESIGN.md` Section 8-9 |
| SSH wrapper commands | `terraform/templates/gitlab-cloud-init.yaml`, `docs/DESIGN.md` Section 8.5 |
| New scripts | `README.md` Project Structure, `TODO.md` if applicable |
| Terraform changes | `terraform/terraform.tfvars.example`, `docs/DESIGN.md` Section 4 |
| Bot features | `docs/DESIGN.md` Section 7, `docs/INTEGRATOR-BOT-PLAN.md` |
| Test changes | `.github/workflows/test.yml`, `TODO.md` |

**Documentation hierarchy** (most authoritative first):
1. `docs/DESIGN.md` - Master specification
2. `docs/SECURITY-ASSESSMENT.md` - Security requirements
3. `docs/INTEGRATOR-BOT-PLAN.md` - Bot architecture
4. `README.md` - User-facing overview
5. `CLAUDE.md` - AI assistant guidance
6. `TODO.md` - Implementation status

**Before committing**: Verify that any code changes are reflected in the corresponding documentation.
