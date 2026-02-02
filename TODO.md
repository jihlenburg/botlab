# GitLab Infrastructure Project - TODO List

**Last Updated**: 2026-02-02

---

## Implementation Status

### Completed Tasks

- [x] **RecoveryManager implementation** - Full disaster recovery automation
  - `_provision_recovery_server()` - Creates new VM on Hetzner Cloud
  - `_attach_volumes()` - Attaches existing volumes to recovery server
  - `_install_gitlab()` - Installs GitLab CE via SSH
  - `_restore_config()` - Restores configuration from Borg backup
  - `_restore_backup()` - Full backup restoration
  - `_reconfigure_gitlab()` - Post-restore reconfiguration
  - `_verify_recovery()` - Health checks and validation

- [x] **RestoreTester implementation** - Automated backup restore testing
  - `_provision_test_server()` - Creates ephemeral test VM
  - `_install_gitlab()` - Installs GitLab on test server
  - `_restore_backup()` - Restores backup for verification
  - `_verify_restore()` - Comprehensive verification checks

- [x] **Test suite created**
  - `tests/conftest.py` - Shared fixtures and mocks
  - `tests/test_monitors.py` - Health, Resource, Backup monitor tests
  - `tests/test_alerting.py` - AlertManager tests
  - `tests/test_ai_analyst.py` - AI analyst tests
  - `tests/test_recovery.py` - Recovery and RestoreTester tests

- [x] **Restore scripts enhanced**
  - `scripts/restore-gitlab.sh` - Full error handling, verification, rollback support
  - `scripts/verify-backup.sh` - JSON output, cross-platform support

- [x] **CI/CD pipeline created**
  - `.github/workflows/test.yml` - pytest, ruff, mypy, shellcheck, terraform validate

- [x] **SSH wrapper expanded**
  - `terraform/templates/gitlab-cloud-init.yaml` - Expanded ALLOWED_COMMANDS from ~12 to ~40+ commands
  - Supports all monitor requirements (nproc, stat, borg commands, gitlab-psql, etc.)

- [x] **Documentation updated**
  - `terraform/terraform.tfvars.example` - Comprehensive configuration template with documentation
  - `docs/DESIGN.md` - Updated Section 7.3 (project structure), Section 8.5 (SSH wrapper)
  - `CLAUDE.md` - Added documentation maintenance guidelines
  - `README.md` - Updated project structure with tests, CI/CD
  - `scripts/setup-borg-backup.sh` - Creates backup script if not present from cloud-init

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

- [ ] **Admin Bot Deployment**
  - [ ] Configure admin bot `.env`
  - [ ] Deploy with `docker-compose`
  - [ ] Verify monitoring active
  - [ ] Test alerting
  - [ ] Test AI analysis

- [ ] **End-to-End DR Test**
  - [ ] Trigger full backup
  - [ ] Simulate server failure
  - [ ] Execute recovery procedure
  - [ ] Verify GitLab functional
  - [ ] Document results

### Phase 5: Security Hardening (Priority: MEDIUM)

- [ ] Configure S3 Object Lock for immutable backups
- [ ] Set up secondary backup destination
- [ ] Create offline backup recovery kit
- [ ] Configure fail2ban on all servers
- [ ] Security audit of configurations

### Phase 6: Future Enhancements (Priority: LOW)

- [ ] Implement Integrator Bot (Claude Code CLI)
- [ ] Add MCP servers as per `INTEGRATOR-BOT-PLAN.md`
- [ ] Implement per-project `.gitlab-bot.yml` scanning
- [ ] Add Grafana dashboards
- [ ] Add Slack/Teams integration

---

## Quick Commands

```bash
# Run tests
cd gitlab-admin-bot
pip install -e ".[dev]"
pytest tests/ -v

# Run linting
ruff check src/ tests/

# Type checking
mypy src/ --ignore-missing-imports

# Terraform
cd terraform
terraform init
terraform plan
terraform apply

# Docker deployment
cd gitlab-admin-bot
docker compose up -d
```

---

## Files Modified in This Session

| File | Status | Changes |
|------|--------|---------|
| `gitlab-admin-bot/src/restore/recovery.py` | Updated | Full method implementations |
| `gitlab-admin-bot/src/restore/tester.py` | Updated | Full method implementations |
| `gitlab-admin-bot/tests/__init__.py` | Created | Test package init |
| `gitlab-admin-bot/tests/conftest.py` | Created | Shared fixtures |
| `gitlab-admin-bot/tests/test_monitors.py` | Created | Monitor tests |
| `gitlab-admin-bot/tests/test_alerting.py` | Created | Alerting tests |
| `gitlab-admin-bot/tests/test_ai_analyst.py` | Created | AI analyst tests |
| `gitlab-admin-bot/tests/test_recovery.py` | Created | Recovery tests |
| `scripts/restore-gitlab.sh` | Updated | Error handling, rollback |
| `scripts/verify-backup.sh` | Updated | JSON output, cross-platform |
| `scripts/setup-borg-backup.sh` | Updated | Creates backup script if not exists |
| `.github/workflows/test.yml` | Created | CI/CD pipeline |
| `terraform/terraform.tfvars.example` | Updated | Comprehensive configuration template |
| `terraform/templates/gitlab-cloud-init.yaml` | Updated | Expanded SSH wrapper commands |
| `docs/DESIGN.md` | Updated | Section 7.3 project structure, Section 8.5 SSH security |
| `CLAUDE.md` | Updated | Project structure, documentation maintenance guidelines |
| `README.md` | Updated | Project structure with tests, CI/CD |
| `TODO.md` | Created | Implementation status tracking |
