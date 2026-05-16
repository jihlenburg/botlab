# First-Deploy Checklist

**Audience**: an operator standing up the ACME GitLab infrastructure for the first time. Follow top to bottom; each section assumes the previous one finished cleanly.

**Expected total wall-clock time**: ~half a day, of which ~2 hours is hands-on. The rest is waiting for GitLab to install, backups to verify, and DNS to propagate.

If you are recovering from a disaster, do not use this document — see [RUNBOOK-RECOVERY.md](RUNBOOK-RECOVERY.md).

---

## 0. Prerequisites

Before you start, have:

- [ ] Hetzner Cloud project + API token with read/write scope
- [ ] Hetzner Robot account (for the Storage Box; this is a separate account from Cloud)
- [ ] A registered domain you can point an A record at
- [ ] An Azure AD tenant with permission to create an Enterprise Application (for SSO)
- [ ] An SMTP account (Microsoft 365 by default; any will do)
- [ ] (Optional, recommended) An S3-compatible bucket on a **non-Hetzner** provider (Wasabi / Backblaze B2 / AWS S3) with Object Lock enabled, for the immutable backup tier
- [ ] An offline location for the recovery kit (encrypted USB drive, safe deposit box, password manager with file attachments)

Local tools on your workstation:

- [ ] `terraform` >= 1.0
- [ ] `python` >= 3.12 with `pip install pydantic pyyaml`
- [ ] `ssh`, `scp`, `borg` (for the offline key custody and recovery rehearsal)
- [ ] (Optional) `aws` CLI configured against your immutable S3 provider

---

## 1. Provision the Storage Box (Hetzner Robot, 5 min)

Done in the Hetzner Robot web UI, not in Terraform — Storage Boxes are a separate product.

- [ ] Order a BX21 (5 TB) in Falkenstein, ideally a **different DC** from where you'll put the GitLab server (`fsn1-dc14` vs the Storage Box DC)
- [ ] Once active, note the hostname (`uXXXXX.your-storagebox.de`) and username (`uXXXXX`)
- [ ] Generate a sub-account from the Storage Box UI with **read+write but NO delete** — this will be the append-only key
- [ ] Keep the main account credentials **offline only** (recovery kit). They are required for `borg prune`, not for routine backups.

See `scripts/setup-borg-append-only.sh` once we have the server; it automates the SSH-side setup.

---

## 2. Configure the seed (15 min)

The seed is the single source of truth. Everything downstream is generated from it.

```bash
git clone <this-repo>
cd botlab
cp seed.example.yaml seed.yaml
$EDITOR seed.yaml
```

Replace every `SECRET:*` placeholder with real values. The validator will refuse to proceed if any remain:

```bash
python scripts/seed_bootstrap.py seed.yaml --validate
```

Specifically, you need:

- [ ] `organization.admin_email`
- [ ] `infrastructure.hetzner.api_token`
- [ ] `infrastructure.ssh.admin_keys.<your-name>` — paste your `~/.ssh/id_ed25519.pub`
- [ ] `infrastructure.ssh.trusted_ips` — your office/VPN CIDR (do not leave empty in production)
- [ ] `gitlab.domain` — e.g. `gitlab.yourcompany.com`
- [ ] `gitlab.version` — pinned package version, e.g. `17.10.0-ce.0` (browse https://packages.gitlab.com/gitlab/gitlab-ce for current options)
- [ ] `backup.storage_box.*` — from step 1
- [ ] `backup.borg.passphrase` — generate fresh, 20+ chars (e.g. `openssl rand -base64 32`). **Record offline immediately.**
- [ ] `backup.s3.*` — fill these in only if you've already provisioned the immutable bucket (recommended). Set `enabled: true`.
- [ ] `alerting.email.*` — SMTP creds for Alertmanager

**Lock down `seed.yaml` now**: it is gitignored, but it lives on your disk. At minimum: `chmod 600 seed.yaml`. Recommended: encrypt with `sops + age` per DESIGN.md Appendix C and remove the plaintext copy.

### 2a. Know where each secret should live

Per the layered approach in DESIGN.md Appendix C, secrets are NOT treated uniformly. Memorise this table — every secret in `seed.yaml` falls into exactly one row:

| Secret | Where it lives in normal operation | What you do |
|--------|-----------------------------------|-------------|
| `infrastructure.hetzner.api_token` | Operator laptop only (in encrypted `seed.yaml` and the gitignored `terraform.tfvars`) | **Never copy to the server.** Terraform runs from your laptop. |
| `infrastructure.ssh.admin_keys.*` (public halves) | Server `authorized_keys` via cloud-init | Public keys; private halves stay on operators' workstations (ideally on a hardware token). |
| `backup.borg.passphrase` | Server `/etc/gitlab-backup.conf` until Layer 2 is implemented, then under `systemd-creds` | This is the only laptop secret that has to live on the server. Plan to migrate it under systemd-creds in Phase 5. |
| `backup.s3.*` (access/secret) | Server `/etc/gitlab-s3-backup.conf` until Layer 2 | Same as above. |
| `alerting.email.smtp_password` | Server `/etc/gitlab/gitlab.rb` until Layer 2 | Same as above. |
| **Borg full-access SSH key + admin passphrase** | **OFFLINE recovery kit only** | Never on the server after `setup-borg-append-only.sh` finishes. The script will prompt and securely delete the on-server copies. |

The rule of thumb: **if a script on the server doesn't need to read it at 03:00 on a Tuesday, it should not be on the server.**

Generate downstream configs:

```bash
python scripts/seed_bootstrap.py seed.yaml --target all
```

This writes `terraform/terraform.tfvars` and prints the contents of `/etc/gitlab-backup.conf` and `/etc/gitlab-s3-backup.conf` to stdout — capture those, you'll deploy them to the server in section 4.

---

## 3. Provision infrastructure (15 min hands-on, ~20 min wait)

```bash
cd terraform
terraform init
terraform plan       # sanity-check the plan
terraform apply
```

Wait for it to finish. Then:

- [ ] Note the load balancer IP from `terraform output load_balancer_ip`
- [ ] Note the GitLab server public IP from `terraform output gitlab_server_public_ip`
- [ ] **Configure DNS**: A record `<domain>` → load balancer IP, TTL 300
- [ ] (Optional) CNAME `registry.<domain>` → `<domain>` for the container registry

**Wait for cloud-init to finish** on the GitLab server. This takes 15-20 minutes (apt updates, GitLab package install, fail2ban, mounting volumes):

```bash
ssh root@<gitlab-public-ip> 'cloud-init status --wait'
```

Don't proceed until that returns `status: done`.

---

## 4. Finish GitLab configuration (30 min)

GitLab is installed at the pinned version but is using the default `gitlab.rb`. You now need to apply the real config.

```bash
# Render gitlab.rb from the template (manual: scripts/gitlab.rb.template).
# Customise for your domain, SMTP, SAML, object storage credentials.
$EDITOR scripts/gitlab.rb.template
scp scripts/gitlab.rb.template root@<gitlab-public-ip>:/etc/gitlab/gitlab.rb

# Push the backup configuration captured in section 2
scp /tmp/gitlab-backup.conf root@<gitlab-public-ip>:/etc/gitlab-backup.conf
ssh root@<gitlab-public-ip> 'chmod 600 /etc/gitlab/gitlab.rb /etc/gitlab-backup.conf'

# Apply
ssh root@<gitlab-public-ip> 'gitlab-ctl reconfigure'
```

Verify:

```bash
curl -fsS "https://<domain>/-/health"        # expect 200
```

Set the initial root password via the web UI on first visit (GitLab generates one and prints it to the server during install — `cat /etc/gitlab/initial_root_password`). **Rotate it immediately** and store in a password manager.

---

## 5. Wire up Azure AD SSO (45 min)

**Order matters.** The break-glass admin account MUST be created BEFORE enabling `omniauth_auto_sign_in_with_provider`. Otherwise you'll create a chicken-and-egg: SSO is broken, no local admin exists, no way in. The steps below are in the correct order.

### 5a. Configure Azure AD (20 min)

See DESIGN.md §5.3.4 for the access-scoping model. The clicks below implement the recommended floor: Assignment Required + a security group, no individual assignments.

**Create the Enterprise App:**

- [ ] **Entra admin centre → Enterprise applications → New application → Create your own application** → name `GitLab ACME Corp`, type "Integrate any other application you don't find in the gallery"
- [ ] **Single sign-on → SAML** → Edit "Basic SAML Configuration":
  - **Identifier (Entity ID)**: `https://<domain>`
  - **Reply URL**: `https://<domain>/users/auth/saml/callback`
  - **Sign-on URL**: `https://<domain>/users/sign_in`
- [ ] Edit "Attributes & Claims" → confirm `email`, `name`, `givenname`, `surname` claims are present (defaults usually suffice)
- [ ] **Save** the IdP signing certificate (download Base64) and the Login URL → both go into `gitlab.rb` in §5c

**Lock down access (Assignment Required + group):**

- [ ] **Microsoft Entra admin centre → Groups → New group**:
  - Group type: **Security**
  - Group name: `gitlab-users`
  - Membership type: **Assigned** (not Dynamic — keeps the membership audit trail simple)
  - **Add YOURSELF as the first member NOW** (do this before the next step or you'll lock yourself out of testing SSO)
- [ ] **Enterprise applications → GitLab ACME Corp → Properties → Assignment required? → Yes → Save**
- [ ] **Enterprise applications → GitLab ACME Corp → Users and groups → Add user/group → assign `gitlab-users` group** (do NOT add individual users)
- [ ] (Optional, tiered access) Repeat for `gitlab-readonly`, `gitlab-admins`, etc. GitLab itself decides what each user can do once they're in — SAML group claims can drive auto-assignment to GitLab groups but that's a v2 enhancement; for now just gate access at the Entra layer.

**Conditional Access (skip if you don't have Entra ID P1+):**

- [ ] **Verify your licensing**: Microsoft 365 admin centre → Billing → Licenses. Conditional Access requires Entra ID P1 (or P2). Bundled with M365 Business Premium, E3, E5; NOT in Business Basic/Standard.
- [ ] If licensed: **Entra admin centre → Protection → Conditional Access → Create new policy**:
  - Name: `MFA for GitLab ACME Corp`
  - Users: include `gitlab-users` group
  - Cloud apps: include the `GitLab ACME Corp` Enterprise App
  - Grant: **Require multi-factor authentication**
  - Enable policy: On
- [ ] Test by signing in to GitLab — you should be prompted for MFA even if your account already has it for other Microsoft services. The point is that GitLab specifically requires it.

**Final verification:**

- [ ] You (in `gitlab-users`) can complete SAML to a sandbox URL. Use a SAML tester or wait until §5c to test against GitLab.
- [ ] A second test user NOT in `gitlab-users` gets blocked at Entra with "AADSTS50105 — user not assigned" (try in incognito). If they DON'T get blocked, Assignment Required isn't actually on — recheck the toggle.
- [ ] Note the IdP cert and Login URL for §5c.

### 5b. Create the break-glass local admin (10 min)

**Before any SAML config is added** to `gitlab.rb`. The setup script provisions the account, generates the TOTP secret server-side, and prints everything in a kit-ready block.

```bash
ssh root@<gitlab-public-ip>
/opt/botlab/scripts/setup-break-glass.sh <your-local-email-domain>
```

Where `<your-local-email-domain>` is a domain that does NOT exist in your Azure AD tenant — a subdomain you control but don't sync to Entra is ideal. This prevents accidental SSO auto-link via `omniauth_auto_link_saml_user`.

- [ ] Run the script. It prints a block containing username, email, password, TOTP secret, TOTP provisioning URI, and 10 backup codes.
- [ ] **Immediately** copy every field into the offline recovery kit (template: [docs/OFFLINE-KIT-TEMPLATE.md](OFFLINE-KIT-TEMPLATE.md) §4). This is the ONLY time the TOTP secret and backup codes are shown in plaintext.
- [ ] Load the TOTP URI into your authenticator app. Any standard RFC 6238 app works (Apple Passwords, 1Password, Bitwarden, Aegis, Google Authenticator) — see DESIGN.md §5.3.3 for the convenience-vs-source-of-truth discussion.
- [ ] Verify by logging in to `https://<domain>/users/sign_in?auto_sign_in=false` with the password + a TOTP code. Confirm you land on the GitLab dashboard as Administrator.
- [ ] Verify a backup code works too: log out, log back in using the password + one of the 10 backup codes. **Mark that code as used in the kit.**
- [ ] Run `/opt/botlab/scripts/verify-break-glass.sh <username>` and confirm it exits 0. This also writes the first Prometheus textfile metric for the verification-staleness alert.
- [ ] Clear your terminal scrollback: `history -c && clear`.

**Block the initial root account** (now redundant — the break-glass is your local-auth path):

- [ ] Log in once as `root` via the bypass URL (the initial password is in `/etc/gitlab/initial_root_password` on the server).
- [ ] **Admin → Users → root → Edit** → set a fresh 32-char random password (save to offline kit §5), then block the account, save.
- [ ] From now on, all local-auth admin access is via the break-glass account.

**Fallback if the setup script is unavailable** (pre-Phase-4 deploy, or you can't get to the script): the manual `gitlab-rails runner` snippet in RUNBOOK-RECOVERY.md Appendix D §D.6 Option 2 creates the same account by hand. Then enable 2FA through the web UI and capture the seed manually.

### 5c. Add SAML configuration to gitlab.rb (15 min)

- [ ] Copy the IdP cert and SSO target URL into `gitlab.rb` (`omniauth_providers`)
- [ ] **DO NOT yet add `omniauth_auto_sign_in_with_provider = 'saml'`** — see §5d.
- [ ] `gitlab-ctl reconfigure`
- [ ] From a fresh browser session: visit `https://<domain>`, click "ACME Corp SSO". Confirm SSO works end-to-end. Your Azure AD user gets a new GitLab account (because `omniauth_auto_link_saml_user = true`).
- [ ] Log out. Visit the bypass URL `https://<domain>/users/sign_in?auto_sign_in=false` and confirm you can still reach the local-auth form (the break-glass should still work even with SAML enabled).

### 5d. Enable auto-redirect (5 min)

This is the step that creates the chicken-and-egg risk if §5b is skipped. Do not run this until break-glass is verified.

- [ ] Add `gitlab_rails['omniauth_auto_sign_in_with_provider'] = 'saml'` to `gitlab.rb`
- [ ] `gitlab-ctl reconfigure`
- [ ] Visit `https://<domain>` — should auto-redirect to Azure AD. Confirm.
- [ ] **Critical verification**: visit `https://<domain>/users/sign_in?auto_sign_in=false` — should STILL show the local-auth form. If this is broken, revert §5d immediately and investigate. The bypass URL is your only path back during an SSO outage.
- [ ] Confirm `BreakGlassLoginUsed` alert in `monitoring/alerts.yml` is loaded (the alert will fire on your verification login if the audit-log-to-Prometheus bridge is up; if the bridge isn't up yet, note it in TODO.md for follow-up).

---

## 6. Set up backups (20 min)

```bash
ssh root@<gitlab-public-ip>

# Initialise the Borg repository against the Storage Box (interactive, one-time)
/opt/botlab/scripts/setup-borg-backup.sh

# Harden with the append-only sub-account (also interactive)
/opt/botlab/scripts/setup-borg-append-only.sh

# Trigger the hourly cron manually to seed the first archive
/usr/local/bin/gitlab-backup-to-borg.sh

# Confirm
borg list "$BORG_REPO"
```

If you configured S3 in step 2, also run a manual weekly backup to verify the immutable tier:

```bash
/opt/botlab/scripts/backup-to-s3.sh
```

---

## 7. Stand up monitoring (1 hour)

The monitoring stack is NOT installed by Terraform / cloud-init today (tracked in TODO.md Phase 4). Do it by hand on the GitLab server following DESIGN.md §7:

- [ ] `apt-get install prometheus prometheus-node-exporter prometheus-blackbox-exporter alertmanager grafana`
- [ ] Drop `monitoring/alerts.yml` from this repo into `/etc/prometheus/alerts.yml`
- [ ] Configure `prometheus.yml` to scrape `localhost:9100` (node), `localhost:9115` (blackbox probe of `/-/health`), and `localhost:9168` (gitlab-exporter — install separately for GitLab-specific metrics). Load `/etc/prometheus/alerts.yml`.
- [ ] Enable the node_exporter textfile collector with `--collector.textfile.directory=/var/lib/node_exporter/textfile_collector`. This is what makes the backup-script-emitted metrics (`gitlab_backup_integrity`, `gitlab_restore_test_success`, etc.) visible.
- [ ] Configure `alertmanager.yml` with the SMTP creds from `seed.yaml` and a route for `severity: critical` → email + webhook. Add a separate route for the `Watchdog` alert → `https://<observer-domain>/watchdog?secret=<...>` (see §7a).
- [ ] **Bind Prometheus, Alertmanager, and Grafana to `127.0.0.1` only.** Reach them via SSH port-forward; do NOT expose to the public internet (T1.5 from SECURITY-REVIEW-2026-05-15.md).
- [ ] Trigger a deliberate failure (stop the GitLab service) to confirm the alerts fire end-to-end. Restart immediately after.

### 7a. Provision the external observer (15 min)

This is the dead-man's-switch (DESIGN.md §7.5). Without it, "the GitLab server is down" is not reliably alertable because the very thing that would alert you is also down.

- [ ] Pick a host **outside** the GitLab server's failure domain. Recommended: ~5 EUR/mo non-Hetzner VPS (Vultr / Linode / OVH). Acceptable: Hetzner Cloud server in a different DC (cheaper; doesn't survive account-level Hetzner issues).
- [ ] Assign a DNS name (Let's Encrypt needs it).
- [ ] Copy `external-observer/setup-observer.sh` to the VPS as root and run it. It will prompt for the GitLab domain, the observer's own DNS name, an alerting destination, and a shared webhook secret.
- [ ] On the GitLab server, configure Alertmanager to dispatch the `Watchdog` alert to the observer (the setup script prints the exact YAML snippet at the end).
- [ ] Wait 10 minutes; confirm the observer's `WatchdogNeverSeen` alert clears.
- [ ] Test failure: stop Alertmanager on the GitLab server for 11 minutes. The observer should fire `WatchdogStale`. Restart immediately.

### 7b. Install the scheduled units (15 min)

The scheduled jobs (hourly backup, weekly borg-check, weekly restore-test, monthly break-glass verify) run via systemd timers. Unit files are committed in `systemd/`.

- [ ] Copy `systemd/*.{service,timer}` to `/etc/systemd/system/`.
- [ ] Edit `gitlab-break-glass-verify.service` to replace `recovery-CHANGEME` with the actual break-glass username from your offline kit.
- [ ] Set up Layer-2 credentials: `systemd-creds encrypt --with-key=host` for `borg_passphrase`, `s3_access_key`, `s3_secret_key` (commands in DESIGN.md Appendix C.4).
- [ ] Ensure `/etc/hcloud-token` exists (mode 0600 root, containing a token scoped to "create/delete servers" for the restore-test). Ensure `/root/.ssh/restore_test_key` exists and its public half is registered in Hetzner Cloud as SSH key `restore-test-key`.
- [ ] `systemctl daemon-reload && systemctl enable --now gitlab-backup.timer gitlab-borg-check.timer gitlab-restore-test.timer gitlab-break-glass-verify.timer`
- [ ] Verify timers loaded: `systemctl list-timers gitlab-*`
- [ ] If migrating from the cron-installed hourly backup: remove `/etc/cron.d/gitlab-backup` AFTER confirming `gitlab-backup.timer` is active. The cron and timer must not run concurrently.

---

## 8. Verify the restore test (10 min)

The weekly restore test (`scripts/restore-test.sh`) is the **single most important automation in the deployment**. Run it once manually before declaring the deploy done:

- [ ] `systemctl start gitlab-restore-test.service` (one-shot manual trigger)
- [ ] Tail the log: `journalctl -u gitlab-restore-test -f` AND `tail -f /var/log/gitlab-restore-test.log`
- [ ] Expected: ephemeral CX21 provisioned in Hetzner Cloud, GitLab installed at pinned version, latest Borg archive restored, `gitlab-rake gitlab:check` passes, server destroyed at the end. Total: 30-90 min.
- [ ] Confirm the metric was written: `cat /var/lib/node_exporter/textfile_collector/gitlab_restore_test.prom`
- [ ] Confirm in Hetzner Cloud console that NO `restore-test-*` server was left behind (the script's trap should have destroyed it on any exit)
- [ ] Confirm `RestoreTestFail` would fire by manually setting the metric to 0 (`echo 'gitlab_restore_test_success 0' > /var/lib/node_exporter/textfile_collector/gitlab_restore_test.prom`), waiting for Alertmanager, restoring.

If this step is skipped, you have a fancy backup architecture and no actual disaster recovery capability.

---

## 9. Build the offline recovery kit (15 min)

The authoritative list of what belongs in the kit lives in [docs/OFFLINE-KIT-TEMPLATE.md](OFFLINE-KIT-TEMPLATE.md). Don't duplicate that list here — open the template, fill in every placeholder, attach the referenced files (`gitlab-secrets.json`, `terraform.tfstate`, operator SSH private keys, Borg full-access key), and store on FDE-encrypted media. Splitting between two physical locations (off-site + on-site safe) is recommended so loss of one doesn't lose the kit.

**Deploy-flow checklist** — the minimum to do during first deploy. Refer back to the template for completeness:

- [ ] `seed.yaml` (the source of truth; everything else can be regenerated from it)
- [ ] Borg **full-access** passphrase (NOT the append-only key on the server)
- [ ] Borg **full-access** SSH private key (the one `setup-borg-append-only.sh` Step 7 prompted you to shred from the server)
- [ ] `gitlab-secrets.json` (copy it after first `gitlab-ctl reconfigure`)
- [ ] Snapshot of `terraform.tfstate` (or credentials for the remote state backend)
- [ ] SSH private keys matching `ssh_public_keys`
- [ ] **Break-glass admin credentials** (from §5b):
  - [ ] Username (e.g. `recovery-a3f7c2`)
  - [ ] Email (e.g. `break-glass-7b21@<your-local-domain>`)
  - [ ] Password (32-char random, current value — rotate after every use)
  - [ ] TOTP secret seed (base32 string from QR code setup)
  - [ ] All 10 TOTP backup codes
  - [ ] Last verified date (initially today; updated each quarterly verification)
- [ ] **Disabled-root password** (the rotated password set in §5b, in case break-glass is ever lost too)
- [ ] A printed copy of [RUNBOOK-RECOVERY.md](RUNBOOK-RECOVERY.md) — Appendix D in particular

Test the kit: on a fresh machine, can you read every file? If not, fix it now, not during an incident. For the break-glass credentials specifically, perform a real login via the bypass URL `https://<domain>/users/sign_in?auto_sign_in=false` as part of this verification.

---

## 10. Run a full DR drill (1 hour)

Before declaring the deployment "production":

- [ ] Schedule a maintenance window
- [ ] Notify stakeholders
- [ ] Walk through [RUNBOOK-RECOVERY.md](RUNBOOK-RECOVERY.md) end-to-end against a *parallel* test server (do not destroy production)
- [ ] Document the actual time taken; if it's > 2 hours, identify what to streamline
- [ ] File any deltas as TODOs

---

## Done

You should now have:

- A production-pinned GitLab CE serving traffic at `https://<domain>` via Azure AD SSO
- Hourly Borg backups to an append-only Storage Box sub-account, with weekly S3 Object Lock copies
- A weekly automated restore-test that emits a Prometheus metric
- Prometheus / Alertmanager / Grafana on the GitLab server, plus an external observer outside Hetzner
- An offline recovery kit you've actually tested
- A documented upgrade path (DESIGN.md §5.6)

Common day-to-day tasks live in DESIGN.md §12. Disaster recovery procedure: RUNBOOK-RECOVERY.md.
