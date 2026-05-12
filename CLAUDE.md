# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

ACME Corp GitLab CE on Hetzner Cloud. Backups via BorgBackup (append-only) and optional S3 Object Lock. Monitoring via Prometheus + Alertmanager + Grafana. No autonomous admin bot — administration is performed by humans.

## Architecture Documents

**Read these documents in order for full context:**

| Document | Purpose | Priority |
|----------|---------|----------|
| `docs/DESIGN.md` | **Master design document** - authoritative specification | READ FIRST |
| `docs/SECURITY-ASSESSMENT.md` | Cybersecurity analysis, ransomware protection, DR edge cases | Security |

All implementation decisions must align with DESIGN.md. If changes are needed, update DESIGN.md first.

## Key Constraints

- **Open Source Only**: No commercial software licenses
- **Backup-based DR**: ~1 hour RPO, ~1-2 hour RTO (no hot standby)
- **Infrastructure**: Hetzner Cloud (~63 EUR/month)
- **3-2-1 Backup Strategy**: Borg (append-only) + S3 (Object Lock) for ransomware resistance
- **No autonomous automation**: Cron + Prometheus/Alertmanager only. No LLM-driven agents.

## Architecture Summary

```
GitLab Primary (CPX31, Falkenstein)
  + Prometheus / Grafana / Alertmanager (systemd)
  + cron: hourly backup → Storage Box (Borg, append-only)
  + cron: weekly       → S3 (Object Lock, optional)
  + cron: weekly       → restore-test on ephemeral VM

Recovery: Terraform provision + scripts/restore-gitlab.sh (~1-2 hours, operator-driven)
```

## Technology Stack

| Component | Technology |
|-----------|------------|
| GitLab | CE (Community Edition) |
| Infrastructure | Terraform + Hetzner Cloud |
| Monitoring | Prometheus + Grafana + Alertmanager |
| Backups | BorgBackup (append-only) + optional S3 (Object Lock) |
| Scheduling | cron |

## Project Structure

```
botlab/
├── CLAUDE.md                       # This file (AI assistant guidance)
├── README.md                       # Project overview and quick start
├── TODO.md                         # Implementation status and task tracking
├── seed.example.yaml               # Seed config template (copy to seed.yaml)
├── docs/
│   ├── DESIGN.md                   # Master design document (READ FIRST)
│   └── SECURITY-ASSESSMENT.md      # Security & ransomware analysis
├── terraform/                      # Infrastructure as code
│   ├── *.tf                        # Hetzner Cloud resources
│   ├── terraform.tfvars.example    # Example configuration (copy to terraform.tfvars)
│   └── templates/                  # Cloud-init templates
├── scripts/                        # Deployment and maintenance scripts
│   ├── seed_schema.py              # Pydantic model for seed.yaml validation
│   ├── seed_bootstrap.py           # Generate configs from seed.yaml
│   ├── setup-borg-backup.sh        # BorgBackup setup
│   ├── setup-borg-append-only.sh   # Append-only Borg hardening (ransomware protection)
│   ├── backup-to-s3.sh             # S3 immutable backup (Object Lock)
│   ├── restore-gitlab.sh           # DR restore procedure
│   └── verify-backup.sh            # Backup verification
├── .github/workflows/              # CI/CD pipeline
│   └── test.yml                    # shellcheck, terraform validate
├── Makefile                        # Common development commands
└── .pre-commit-config.yaml         # Pre-commit hooks configuration
```

## Seed Configuration (Single Source of Truth)

`seed.yaml` is the unified config file that generates all downstream configs:

```bash
# Validate seed.yaml
python scripts/seed_bootstrap.py seed.yaml --validate

# Generate all config files
python scripts/seed_bootstrap.py seed.yaml --target all

# Preview changes without writing
python scripts/seed_bootstrap.py seed.yaml --target all --diff

# Generate a specific target
python scripts/seed_bootstrap.py seed.yaml --target terraform
python scripts/seed_bootstrap.py seed.yaml --target borg-conf
python scripts/seed_bootstrap.py seed.yaml --target s3-conf
```

**Files generated from seed.yaml:**
| Target | Output File |
|--------|-------------|
| `terraform` | `terraform/terraform.tfvars` |
| `borg-conf` | stdout (`/etc/gitlab-backup.conf` content) |
| `s3-conf` | stdout (`/etc/gitlab-s3-backup.conf` content) |

**Important:** `seed.yaml` contains secrets and is gitignored. Use `seed.example.yaml` as a template.

## Development Commands

```bash
# Terraform
cd terraform && terraform init
terraform plan
terraform apply

# Validate seed config
python scripts/seed_bootstrap.py seed.yaml --validate

# Shellcheck
make shellcheck
```

## Implementation Phases

1. **Infrastructure** (Week 1): Terraform, server, network
2. **GitLab Primary** (Week 2): GitLab CE, SSO, LFS
3. **Backup System** (Week 3): Hourly backups, BorgBackup, 3-2-1 strategy
4. **Monitoring & Alerting** (Week 4): Prometheus, Alertmanager, Grafana, cron metrics
5. **Security Hardening** (Week 5): Append-only Borg, S3 immutable backups
6. **Testing** (Week 6): DR drill, documentation

## Code Quality Requirements

For shell scripts: `shellcheck scripts/*.sh` must pass.
For Terraform: `terraform fmt -check -recursive` and `terraform validate` must pass.
For Python utilities (seed bootstrap): the script should validate cleanly against `seed.example.yaml`.

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
| Automation | Cron + Prometheus + Alertmanager (deterministic) | DESIGN.md 7 |
| DR Procedure | Operator-driven `scripts/restore-gitlab.sh` | DESIGN.md 6.4 |

## Key Files

| File | Purpose |
|------|---------|
| `docs/DESIGN.md` | Master design document (READ FIRST) |
| `docs/SECURITY-ASSESSMENT.md` | Security analysis and recommendations |
| `terraform/*.tf` | Infrastructure definitions |
| `terraform/terraform.tfvars.example` | Configuration template with documentation |
| `terraform/templates/gitlab-cloud-init.yaml` | Server bootstrap configuration |
| `scripts/setup-borg-backup.sh` | BorgBackup initialization |
| `scripts/setup-borg-append-only.sh` | Append-only Borg hardening (ransomware protection) |
| `scripts/backup-to-s3.sh` | S3 immutable backup with Object Lock |
| `scripts/restore-gitlab.sh` | Disaster recovery procedure |
| `TODO.md` | Implementation status and task tracking |
| `seed.example.yaml` | Seed config template (single source of truth) |
| `scripts/seed_bootstrap.py` | Generate downstream configs from seed.yaml |
| `scripts/seed_schema.py` | Pydantic validation model for seed.yaml |

## Documentation Maintenance

**IMPORTANT: Keep documentation in sync with implementation.**

When making changes to this project, update the relevant documentation:

| Change Type | Documents to Update |
|-------------|---------------------|
| Architecture changes | `docs/DESIGN.md` (authoritative), then `README.md` |
| Security changes | `docs/SECURITY-ASSESSMENT.md`, `docs/DESIGN.md` Section 8-9 |
| New scripts | `README.md` Project Structure, `TODO.md` if applicable |
| Terraform changes | `terraform/terraform.tfvars.example`, `docs/DESIGN.md` Section 4 |
| Monitoring changes | `docs/DESIGN.md` Section 7, alert-rules files |
| Test changes | `.github/workflows/test.yml`, `TODO.md` |

**Documentation hierarchy** (most authoritative first):
1. `docs/DESIGN.md` - Master specification
2. `docs/SECURITY-ASSESSMENT.md` - Security requirements
3. `README.md` - User-facing overview
4. `CLAUDE.md` - AI assistant guidance
5. `TODO.md` - Implementation status

**Before committing**: Verify that any code changes are reflected in the corresponding documentation.
