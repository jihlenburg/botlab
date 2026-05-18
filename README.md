# ACME Corp GitLab Infrastructure

Self-hosted GitLab CE on Hetzner Cloud with cron-driven backups and Prometheus/Alertmanager monitoring.

## Overview

| Attribute | Value |
|-----------|-------|
| **Scale** | 10-20 developers |
| **Features** | Git LFS, Azure AD SSO, CI/CD |
| **Hosting** | Hetzner Cloud (EU) |
| **Cost** | ~63 EUR/month |
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
                       ┌────▼────┐         ┌─────────┐
                       │ GitLab  │         │ Object  │
                       │ Primary │────────►│ Storage │
                       │ (CPX31) │         │  (S3)   │
                       └────┬────┘         └─────────┘
                            │
                       ┌────▼─────────────────────┐
                       │ Private Network          │
                       │   10.0.0.0/16            │
                       └────┬─────────────────────┘
                            │
                     ┌──────▼──────┐
                     │ Storage Box │
                     │  (Backups)  │
                     │  BX21 5TB   │
                     └─────────────┘
```

Prometheus, Alertmanager, Grafana, and the hourly backup cron jobs all run on the GitLab server itself; there is no separate automation host.

## Technology Stack

All components are **100% open source** (no license fees).

| Component | Technology | License |
|-----------|------------|---------|
| Version Control | GitLab CE | MIT |
| Infrastructure | Terraform | MPL 2.0 |
| Monitoring | Prometheus + Grafana + Alertmanager | Apache 2.0 |
| Backups | BorgBackup (+ optional S3 Object Lock) | BSD |

## Quick Start

### Prerequisites

- Hetzner Cloud account
- Terraform >= 1.0
- Azure AD tenant (for SSO)

### Deploy Infrastructure

```bash
cd terraform
cp terraform.tfvars.template terraform.tfvars
# Edit terraform.tfvars with your values

terraform init
terraform plan
terraform apply
```

### Install GitLab

Cloud-init on the GitLab server already installs the pinned version of GitLab CE
(see `gitlab.version` in `seed.yaml`). If you need to install manually:

```bash
curl https://packages.gitlab.com/install/repositories/gitlab/gitlab-ce/script.deb.sh | sudo bash
sudo EXTERNAL_URL="https://gitlab.example.com" apt-get install "gitlab-ce=17.10.0-ce.0"
sudo apt-mark hold gitlab-ce
```

See `docs/DESIGN.md` §5 for complete configuration, §5.6 for the upgrade runbook,
and `docs/DEPLOY.md` for the ordered first-deploy checklist.

### Set up backups

```bash
scripts/setup-borg-backup.sh           # initialize repo (interactive)
scripts/setup-borg-append-only.sh      # harden with append-only sub-account
# Optional: weekly immutable S3 copy
scripts/backup-to-s3.sh                # invoked weekly by cron
```

## Project Structure

For the full project tree see `CLAUDE.md`. Key directories:

```
botlab/
├── docs/                           # DESIGN.md, SECURITY-ASSESSMENT.md
├── terraform/                      # Hetzner Cloud infrastructure (Terraform)
├── scripts/                        # Deployment, backup, recovery, seed bootstrap
│   ├── seed_schema.py              # Seed config validation (Pydantic)
│   ├── seed_bootstrap.py           # Generate all downstream configs from seed.yaml
│   ├── setup-borg-backup.sh        # BorgBackup setup (interactive)
│   ├── setup-borg-append-only.sh   # Append-only Borg hardening
│   ├── backup-to-s3.sh             # S3 immutable backup (Object Lock)
│   ├── restore-gitlab.sh           # DR restore procedure (operator-driven)
│   └── verify-backup.sh            # Backup verification
├── seed.template.yaml              # Single source of truth config template
└── .github/workflows/test.yml      # CI: shellcheck, terraform validate
```

## Disaster Recovery

**Strategy**: 3-2-1 backup with immutable tier (no hot standby). ~1h RPO, ~1-2h RTO.

| Tier | Frequency | Retention | Protection |
|------|-----------|-----------|------------|
| Local | Hourly | 24 hours | None (staging only) |
| Borg (Storage Box) | Hourly | 12 months | Append-only (ransomware-resistant) |
| S3 (Object Lock) | Weekly | 90 days | WORM / immutable |

Restore is performed by an operator using `scripts/restore-gitlab.sh`. A weekly cron drives a fully automated restore-test on an ephemeral CX21 VM and emits a Prometheus metric — Alertmanager fires if the test fails or doesn't run.

See `docs/DESIGN.md` Section 6 and `docs/SECURITY-ASSESSMENT.md` for details.

## Monitoring (Phase 4 — not yet deployed)

**Target architecture** — installed by hand following `docs/DEPLOY.md` §7. Not provisioned by Terraform or cloud-init today.

- Prometheus, Alertmanager, Grafana run as systemd services on the GitLab server
- **Health checks**: blackbox_exporter probes `/-/health`
- **Resource monitoring**: node_exporter (disk, CPU, memory)
- **Backup signals**: `scripts/borg-check.sh` (weekly) and `scripts/restore-test.sh` (weekly) emit Prometheus textfile metrics via the node_exporter textfile collector
- **Alerting**: email + webhook via Alertmanager; rules in `monitoring/alerts.yml`
- **External observer**: ~5 EUR/mo non-Hetzner VPS probes the LB and the Watchdog alert (scaffolding in `external-observer/`)

Grafana dashboards (once installed): `http://gitlab-server:3000` via SSH port-forward only.

**Current implementation state** lives in `TODO.md` — search for "T2.8" and Phase 4 to see what's wired and what isn't.

## Design History

Earlier drafts (v1.x) proposed an "Admin Bot" (Python service) and a planned LLM-driven "Integrator Bot" to perform administrator duties. Both were dropped in v2.0 of the design — administration is now a human responsibility, supported by deterministic monitoring and cron-scheduled scripts. See the v2.0 row of the document control table in `docs/DESIGN.md`.

## Documentation

| Document | Description |
|----------|-------------|
| [DESIGN.md](docs/DESIGN.md) | Complete technical specification (master document) |
| [SECURITY-ASSESSMENT.md](docs/SECURITY-ASSESSMENT.md) | Security & ransomware protection analysis |
| [DEPLOY.md](docs/DEPLOY.md) | First-deploy checklist for operators |
| [RUNBOOK-RECOVERY.md](docs/RUNBOOK-RECOVERY.md) | Operator-facing disaster recovery runbook |
| [CLAUDE.md](CLAUDE.md) | AI assistant instructions |

## Cost Breakdown

Server type is configurable in `terraform/terraform.tfvars`. Default sizing:

| Resource | Specification | EUR/month |
|----------|---------------|-----------|
| GitLab Server | CPX31 (4 vCPU, 16GB RAM)* | ~18 |
| Block Storage | 300 GB* | ~13 |
| Object Storage | ~2 TB | ~10 |
| Storage Box | BX21 (5 TB) | ~16 |
| Load Balancer | LB11 | ~6 |
| **Total** | | **~63** |

*Configurable via Terraform variables. See `terraform/variables.tf` for options.

## License

Infrastructure code is proprietary to ACME Corp.

GitLab CE, Terraform, Prometheus/Grafana/Alertmanager, BorgBackup, and other tools retain their original open source licenses.
