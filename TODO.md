# GitLab Infrastructure Project - TODO List

**Last Updated**: 2026-05-15
**Last security review**: 2026-05-15 — see `docs/SECURITY-REVIEW-2026-05-15.md`
**Next baseline security review due**: 2026-08-15 (quarterly check) / 2027-05-15 (annual)

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
- [~] **Layered secrets management** (per DESIGN.md Appendix C v2.2):
  - [x] Layer 1 — eliminated unused `gitlab.private_token` from seed; documented laptop-only invariants in DEPLOY.md §2a; `setup-borg-append-only.sh` now securely shreds full-access SSH keys with operator confirmation
  - [ ] Layer 2 — `systemd-creds` (TPM2-sealed where available) for Borg passphrase + S3 keys; migrate cron entries to systemd timers
  - [ ] Layer 3 — GitLab runtime secrets (SMTP, SAML) moved to `File.read` from tmpfs populated at boot from systemd-creds
  - [ ] Layer 4 — see T1.4–T1.6, T2.3, T2.7, T2.8 (preventing root compromise is the real defence)
- [x] Pin GitLab CE version and document the upgrade runbook — `seed.gitlab.version`, threaded through Terraform, `apt-mark hold` in cloud-init; runbook in DESIGN.md §5.6

### Phase 5b: Findings from Security Review 2026-05-15

See `docs/SECURITY-REVIEW-2026-05-15.md` for full context. Items grouped by tier.

**T1 — fix sooner:**

- [ ] **T1.2** Configure remote Terraform state backend (Hetzner Object Storage, encrypted); also snapshot state into offline recovery kit
- [ ] **T1.3** Define recovery-workstation profile in `docs/RUNBOOK-RECOVERY.md` (dedicated machine OR live-USB, FDE, network isolation when not recovering)
- [ ] **T1.4** Make `trusted_ssh_ips` a required Terraform variable with no default (fail-loud instead of silent open-SSH)
- [ ] **T1.5** Document monitoring stack exposure & auth model in DESIGN.md §7 (bind to 127.0.0.1, SSH port-forward access; Grafana admin pwd from seed; Alertmanager API auth; external observer webhook auth)
- [ ] **T1.6** Vendor the GitLab repo install script (`scripts/install-gitlab-repo.sh`) with CI checksum verification; have cloud-init run the vendored copy instead of `curl ... | bash`

**T2 — should fix:**

- [ ] **T2.2** Document GitLab CVE monitoring/patching cadence in DESIGN.md §5.6 (subscribe to GitLab security advisories; patch criticals within published window)
- [ ] **T2.3** Add `sshd` fail2ban jail to cloud-init
- [ ] **T2.4** TLS hardening in `gitlab.rb`: Mozilla Intermediate ciphers, OCSP stapling, document HSTS preload submission in DEPLOY.md
- [ ] **T2.5** Confirm/configure LB sticky-session cookie flags (`Secure; HttpOnly; SameSite=Lax`)
- [ ] **T2.6** Credential rotation matrix in DESIGN.md Appendix C (hcloud_token, GitLab PAT, SAML cert, SMTP password, SSH host keys, operator SSH keys)
- [ ] **T2.7** AIDE file-integrity monitoring in cloud-init; nightly cron + Prometheus textfile metric; re-baseline as part of upgrade runbook
- [x] **T2.8** Break-glass local admin account designed & documented — DESIGN.md §5.3.3 (account model), DEPLOY.md §5b (create before enabling auto-redirect; correct ordering enforced), RUNBOOK-RECOVERY.md Appendix D (SSO failure recovery procedure), `monitoring/alerts.yml` (`BreakGlassLoginUsed` alert wired up). Implementation pending first deploy.
  - [ ] **T2.8a** Wire GitLab audit log → Prometheus textfile collector so `gitlab_break_glass_login_total` metric exists (the `BreakGlassLoginUsed` alert depends on it; alert rule is committed but the metric source isn't yet)

**T3 — hardening polish backlog** (work after T1/T2 closed): commit signing decision, SBOM/signature spot-checks, LFS pre-signed URL TTL, log retention policy, annual security tabletop exercise, `SECURITY.md` responsible-disclosure path, verify gitleaks runs in CI not just pre-commit.

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
