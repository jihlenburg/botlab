# GitLab Infrastructure Project - TODO List

**Last Updated**: 2026-05-12

---

## Implementation Status

### Completed Tasks

- [x] **Backup scripts**
  - `scripts/setup-borg-backup.sh` - BorgBackup initialization
  - `scripts/setup-borg-append-only.sh` - Append-only hardening
  - `scripts/backup-to-s3.sh` - S3 immutable copy (Object Lock)
  - `scripts/restore-gitlab.sh` - Operator-driven restore with verification
  - `scripts/verify-backup.sh` - Backup health check (JSON output)

- [x] **Terraform infrastructure**
  - Hetzner network, subnet, firewalls
  - GitLab primary CPX31 with attached data + backup volumes
  - Load balancer with TLS termination
  - Cloud-init for GitLab server bootstrap (fail2ban, cron, Borg)

- [x] **Seed configuration**
  - `seed.example.yaml` - Single source of truth template
  - `scripts/seed_schema.py` - Pydantic validation
  - `scripts/seed_bootstrap.py` - Generates `terraform.tfvars`, Borg conf, S3 conf

- [x] **Documentation v2.0**
  - Removed Admin Bot and (planned) Integrator Bot from the architecture
  - Documented Prometheus + Alertmanager + cron model as the replacement
  - `docs/DESIGN.md` and `docs/SECURITY-ASSESSMENT.md` updated to v2.0

---

## Remaining Tasks

### Phase 4: Deployment & Testing (Priority: HIGH)

- [ ] **Infrastructure Deployment**
  - [ ] Create Hetzner Cloud account (if not exists)
  - [ ] Configure `terraform/terraform.tfvars` with real values
  - [ ] Run `terraform plan` to verify
  - [ ] Run `terraform apply` to deploy
  - [ ] Verify network connectivity

- [ ] **GitLab Installation**
  - [ ] SSH to GitLab server
  - [ ] Run `gitlab-setup.sh`
  - [ ] Configure `gitlab.rb` from template
  - [ ] Run `gitlab-ctl reconfigure`
  - [ ] Verify GitLab accessible

- [ ] **Backup System Setup**
  - [ ] Create Storage Box on Hetzner
  - [ ] Run `setup-borg-backup.sh`
  - [ ] Configure append-only sub-account
  - [ ] Test backup creation
  - [ ] Test backup restoration

- [ ] **Monitoring & Alerting Setup**
  - [ ] Install Prometheus, Alertmanager, Grafana on the GitLab server (systemd)
  - [ ] Install node_exporter, blackbox_exporter, gitlab-exporter
  - [x] Author alert rules (`monitoring/alerts.yml`): `GitLabDown`, `DiskSpace*`, `Memory*`, `CPU*`, `BackupOverdue*`, `BorgIntegrityFail`, `BorgCheckStale`, `RestoreTestFail`, `RestoreTestStale`, `SSLExpiring*`, `Watchdog`
  - [ ] Configure Alertmanager email + webhook routes (including the `Watchdog` webhook to the external observer)
  - [ ] Wire textfile collector for cron-emitted metrics (`gitlab_backup_last_success_timestamp`, `gitlab_backup_integrity`, `gitlab_restore_test_success`)
  - [ ] Wire weekly restore-test cron (`scripts/`) to ephemeral CX21 VM and emit metric
  - [ ] Provision external observer (recommended: ~5 EUR/mo non-Hetzner VPS running blackbox_exporter + a webhook receiver). See DESIGN.md §7.5.

- [ ] **End-to-End DR Test**
  - [ ] Trigger full backup
  - [ ] Simulate server failure
  - [ ] Execute recovery procedure (`scripts/restore-gitlab.sh`)
  - [ ] Verify GitLab functional
  - [ ] Document results

### Phase 5: Security Hardening (Priority: MEDIUM)

- [x] Configure S3 Object Lock for immutable backups — `scripts/backup-to-s3.sh`
- [x] Set up secondary backup destination — S3 immutable backup script
- [x] Implement append-only Borg backup — `scripts/setup-borg-append-only.sh`
- [x] Extend backup retention to 12 months — updated defaults
- [x] Add S3 backup to seed configuration — `backup.s3` in `seed_schema.py`
- [ ] Wire `borg check` into a weekly cron + Prometheus textfile metric
- [ ] Move S3 immutable copy to a non-Hetzner provider (Wasabi/B2/AWS) to decouple from Hetzner account lockout risk
- [ ] Create offline backup recovery kit (Borg admin key, Terraform state snapshot, gitlab-secrets.json)
- [ ] Configure fail2ban on the GitLab server (currently set up in cloud-init — verify in prod)
- [ ] Adopt sops/age (or systemd-creds) for secrets on disk, replacing plaintext in `/etc/gitlab/gitlab.rb` and `/etc/gitlab-backup.conf` (see DESIGN.md Appendix C for the documented approach)
- [x] Pin GitLab CE version and document the upgrade runbook — `seed.gitlab.version`, threaded through Terraform, `apt-mark hold` in cloud-init; runbook in DESIGN.md §5.6
- [ ] Security audit of configurations

### Phase 6: Future Enhancements (Priority: LOW)

- [ ] Author shareable Grafana dashboards (GitLab Overview, Infrastructure, Backup Status)
- [ ] Add Slack/Teams Alertmanager receiver
- [ ] AIDE or auditd on `/var/opt/gitlab` and `/etc/gitlab` for file integrity monitoring
- [ ] Object Storage versioning + cross-bucket replication for LFS/artifacts

---

## Quick Commands

```bash
# Terraform
cd terraform
terraform init
terraform plan
terraform apply

# Validate seed config
python scripts/seed_bootstrap.py seed.yaml --validate

# Shellcheck
make shellcheck
```

---

## Recent Changes (v2.0, 2026-05-12)

| Area | Change |
|------|--------|
| `docs/DESIGN.md` | Bumped to v2.0. Removed Section 7 (AI Bot Admin System) and Section 7.8 (per-repo bot policies). Replaced with a Monitoring & Alerting section describing Prometheus + Alertmanager + cron on the GitLab server. Removed the admin-bot CX32 instance from the cost summary and infrastructure section. Updated total cost to ~63 EUR/month. |
| `docs/SECURITY-ASSESSMENT.md` | Bumped to v2.0. Removed "Admin Bot" attack-vector entries, updated backup architecture diagram to reflect cron-from-GitLab-server flow, replaced bot-driven detection language with deterministic Prometheus/Alertmanager signals. |
| `docs/INTEGRATOR-BOT-PLAN.md` | Deleted. |
| `README.md` | Rewrote to reflect cron + Alertmanager model. Cost updated to ~63 EUR/month. |
| `CLAUDE.md` | Updated guidance to forbid LLM-driven automation and document the new architecture. |
| `terraform/` | Removed admin-bot server, its firewall, its outputs, its private IP variable, and the admin-bot cloud-init template. Simplified `gitlab-cloud-init.yaml` to remove the bot SSH wrapper and `gitlab-admin` user. |
| `scripts/seed_bootstrap.py` | Dropped `bot-env` and `bot-config` targets. Remaining targets: `terraform`, `borg-conf`, `s3-conf`. |
| `scripts/seed_schema.py` | Removed `ClaudeConfig`, `BotConfig`, `MonitoringConfig`, and `ServersConfig.admin_bot`. |
| `seed.example.yaml` | Dropped `claude`, `bot`, `monitoring` sections and the admin-bot server entry. |
| `Makefile`, `.github/workflows/test.yml`, `.pre-commit-config.yaml` | Removed Python/pytest/mypy/ruff/docker targets. Kept shellcheck and terraform validation. |
| `gitlab-admin-bot/` | Tree deleted. |
