# GitLab Infrastructure Project - TODO List

**Last Updated**: 2026-05-18
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

- [ ] **Backup System Setup** (Storage Box now provisioned by Terraform as of design v2.7 — no manual Hetzner step)
  - [x] ~~Create Storage Box on Hetzner~~ — now handled by `terraform/storage_box.tf` (provider v1.63.0, unified Cloud Console)
  - [x] ~~Configure append-only sub-account~~ — sub-account itself is Terraformed; the append-only SSH constraint is installed by `scripts/setup-borg-append-only.sh` (forced-command in authorized_keys)
  - [ ] Generate OFFLINE SSH keypair on a non-daily-driver machine, put pubkey in seed.yaml, store private half on two FDE USBs (DEPLOY.md §1)
  - [ ] After `terraform apply`: paste `terraform output storage_box_post_apply` values into `seed.yaml.backup.storage_box.host/user`, re-run `seed_bootstrap.py --target borg-conf`
  - [ ] Run `setup-borg-backup.sh` then `setup-borg-append-only.sh` on the server (with `STORAGEBOX_SUBACCOUNT_PASSWORD` env var; rotate password in Console immediately after)
  - [ ] Test backup creation (a real archive — the smoke-test create+delete in `setup-borg-backup.sh` only proves the keys work)
  - [ ] Test backup restoration via `scripts/restore-test.sh` on an ephemeral CX21

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
- [ ] **Layered secrets management** (per DESIGN.md Appendix C; one sub-item done, three pending):
  - [x] Layer 1 — eliminated unused `gitlab.private_token` from seed; documented laptop-only invariants in DEPLOY.md §2a; `setup-borg-append-only.sh` now securely shreds full-access SSH keys with operator confirmation
  - [ ] Layer 2 — `systemd-creds` with host-key fallback (Hetzner Cloud doesn't expose TPM; see DESIGN.md Appendix C.4) for Borg passphrase + S3 keys; cron migrated to systemd timers (unit files in `systemd/` — install in Phase 4)
  - [ ] Layer 3 — GitLab runtime secrets (SMTP, SAML) moved to `File.read` from tmpfs populated at boot from systemd-creds
  - [ ] Layer 4 — see T1.4–T1.6, T2.3, T2.7, T2.8 (preventing root compromise is the real defence)
- [x] Pin GitLab CE version and document the upgrade runbook — `seed.gitlab.version`, threaded through Terraform, `apt-mark hold` in cloud-init; runbook in DESIGN.md §5.6

### Phase 5b: Findings from Security Review 2026-05-15

See `docs/SECURITY-REVIEW-2026-05-15.md` for full context. Items grouped by tier.

**T1 — fix sooner:**

- [ ] **T1.2** Configure remote Terraform state backend (Hetzner Object Storage, encrypted); also snapshot state into offline recovery kit. **Urgency bumped 2026-05-18 (design v2.7):** state now contains Storage Box + sub-account IDs (the load-bearing ransomware-resistant copy of all data). Local-only state is acceptable for a typo-resistant `terraform apply` (we have `prevent_destroy` on both resources), but losing the state file would force a `terraform import` recovery that's substantially more painful than it used to be.
- [ ] **T1.3** Define recovery-workstation profile in `docs/RUNBOOK-RECOVERY.md` (dedicated machine OR live-USB, FDE, network isolation when not recovering)
- [x] **T1.4** Made `trusted_ssh_ips` a required Terraform variable with two validation blocks (non-empty + every entry is a valid CIDR). Removed the `dynamic "rule"` fallback in `terraform/firewalls.tf` that opened SSH to `0.0.0.0/0`. `terraform plan` now fails loudly on empty list, invalid CIDR, or omitted variable. Files: `terraform/variables.tf`, `terraform/firewalls.tf`, `terraform/terraform.tfvars.example`. Verified locally with three `terraform plan` invocations covering empty, invalid, and valid inputs.
- [x] **T1.5** Monitoring stack exposure & auth model — partial: DEPLOY.md §7 now says "bind to 127.0.0.1" and "SSH port-forward only" explicitly; external observer webhook auth via shared secret documented in `external-observer/`. Pending: actually applying the binding in the install commands (operator's job in Phase 4).
- [x] **T1.6** Vendored the upstream packages.gitlab.com repo-install script at `scripts/vendor/install-gitlab-repo.sh` (kept under `vendor/` so the non-recursive `shellcheck scripts/*.sh` glob does not lint upstream content). Cloud-init now ships the script via `write_files` with `encoding: b64`, sourced at `terraform apply` time via `base64encode(file(...))` in `terraform/servers.tf`. Cloud-init `runcmd` runs `bash /usr/local/bin/install-gitlab-repo.sh` instead of `curl … | bash`. Added a `verify-vendored-checksums` job to `.github/workflows/test.yml` that runs `sha256sum -c CHECKSUMS`. Refresh procedure documented in `scripts/vendor/README.md`. Initial pin: sha256 `3f6a403e…2e8d30b`, audited 2026-05-18.

**T2 — should fix:**

- [x] **T2.1** Seed validator now refuses Hetzner endpoints when `backup.s3.enabled: true` — `scripts/seed_schema.py` `_validate_constraints` rejects `hetzner`/`your-objectstorage.com`/`fsn1.`/`nbg1.`/`hel1.` in `backup.s3.endpoint`.
- [ ] **T2.2** Document GitLab CVE monitoring/patching cadence in DESIGN.md §5.6 (subscribe to GitLab security advisories; patch criticals within published window)
- [x] **T2.3** Added `[sshd]` fail2ban jail to cloud-init at `/etc/fail2ban/jail.d/sshd.conf` using the built-in `sshd` filter with `backend = systemd` (correct for Ubuntu 24.04 / journald). 5 failures in 10 min → 1h ban. Files: `terraform/templates/gitlab-cloud-init.yaml`.
- [ ] **T2.4** TLS hardening in `gitlab.rb`: Mozilla Intermediate ciphers, OCSP stapling, document HSTS preload submission in DEPLOY.md
- [ ] **T2.5** Confirm/configure LB sticky-session cookie flags (`Secure; HttpOnly; SameSite=Lax`)
- [x] **T2.6** Credential rotation matrix added to DESIGN.md Appendix C.8 (v2.2).
- [ ] **T2.7** AIDE file-integrity monitoring in cloud-init; nightly cron + Prometheus textfile metric; re-baseline as part of upgrade runbook
- [x] **T2.8** Break-glass local admin account — design, scripts, verification, alerts, kit template all committed. Files: `scripts/setup-break-glass.sh`, `scripts/verify-break-glass.sh`, `docs/OFFLINE-KIT-TEMPLATE.md`, DESIGN.md §5.3.3, DEPLOY.md §5b, RUNBOOK-RECOVERY.md Appendix D (§D.1-D.8), `monitoring/alerts.yml` (`BreakGlass*` rule group). Implementation in production pending first deploy.
  - [ ] **T2.8a** Wire GitLab audit log → Prometheus textfile collector so `gitlab_break_glass_login_total` metric exists (the `BreakGlassLoginUsed` alert depends on it; alert rule is committed but the metric source isn't yet). Until then, RUNBOOK Appendix D §D.8 documents the manual `gitlab-rails` query.
  - [x] **T2.8b** Systemd timer for `scripts/verify-break-glass.sh` — units at `systemd/gitlab-break-glass-verify.{service,timer}` (monthly). Operator must edit the service file at deploy time to set the actual break-glass username.

**T3 — hardening polish:**
- [x] **T3.6** `SECURITY.md` responsible-disclosure path added at repo root.
- [x] **T3.7** Gitleaks now runs in CI (`.github/workflows/test.yml`) — was previously pre-commit-only, which is bypassable with `--no-verify`.
- [ ] **T3.x** Backlog: commit signing decision, SBOM/signature spot-checks, LFS pre-signed URL TTL, log retention policy, annual security tabletop exercise.

**New TODOs from v2.6 refactor:**

- [ ] **T4.1** Add a `--verify-data` `borg check` cadence (annually?) — separate timer; current weekly check is `--repository-only` for speed. See `scripts/borg-check.sh` header comment.
- [ ] **T4.2** Migrate the hourly backup from cron (`/etc/cron.d/gitlab-backup` baked into cloud-init) to the systemd timer `gitlab-backup.timer` once Layer 2 systemd-creds is in place. Keep the cron during the transition; remove only after the timer has run successfully through a full daily cycle.
- [ ] **T4.3** External observer alerting destination: choose a notification channel that is independent of the operator's Microsoft account (per `external-observer/README.md`). The observer should never depend on the same identity it's trying to protect.

**New TODOs from v2.7 (Storage Box → Terraform migration):**

- [ ] **T5.1** Decide whether to keep `lifecycle { ignore_changes = [ssh_keys] }` on `hcloud_storage_box.gitlab_backups` permanently or document an "OK to remove for one apply" rotation runbook. Current state: rotation goes through the Hetzner Console because changing the attribute would force a destroy/recreate of the box (and the data). A cleaner runbook would be: temporarily comment out the `ignore_changes`, apply once with the new key, restore the `ignore_changes`, commit. Untested; document before first real rotation.
- [ ] **T5.2** Validate `sshpass` is in the cloud-init packages list on the next provisioning test. (Added in v2.7; both new setup scripts depend on it for the one-shot SFTP install.)
- [ ] **T5.3** The two `setup-borg-*.sh` scripts on the server now require the sub-account password via env var. Consider whether systemd-creds Layer 2 (Phase 5) should also cover this — probably not (one-shot use only, rotated immediately), but worth a paragraph in DESIGN.md Appendix C when Layer 2 lands.
- [ ] **T5.4** The smoke-test archive `setup-borg-append-only.sh` creates (to prove append works under the constraint) cannot be deleted from the server. Document the manual prune step from the recovery workstation in DESIGN.md §12 (operational procedures).

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
