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

### 5a. Configure Azure AD (15 min)

- [ ] Create an Enterprise Application "GitLab ACME Corp"
- [ ] Set the Identifier, Reply URL, Sign-on URL to your `<domain>`
- [ ] Add the GitLab user group(s) as assigned users — do NOT leave it open to "all users in tenant" unless that's actually intended
- [ ] Note the IdP cert and SSO target URL for §5c

### 5b. Create the break-glass local admin (10 min)

Done via the GitLab web UI as the initial root account, **before any SAML config is added** to `gitlab.rb`.

```bash
# Get the initial root password (set by omnibus at install time)
ssh root@<gitlab-public-ip> 'cat /etc/gitlab/initial_root_password'
```

Log in to `https://<domain>` as `root` with that password. Then:

- [ ] Generate the break-glass identity (record EVERYTHING in the offline kit immediately):
  ```bash
  # On the operator workstation
  echo "Username:  recovery-$(openssl rand -hex 3)"
  echo "Email:     break-glass-$(openssl rand -hex 4)@<your-local-domain>"
  echo "Password:  $(openssl rand -base64 24)"
  ```
  Where `<your-local-domain>` is one that does NOT exist in your Azure AD tenant (prevents accidental SSO auto-link). A subdomain you control but don't sync to Entra is fine.
- [ ] In the GitLab admin area: **Admin → Users → New user** with the above
- [ ] Set **Access level → Administrator**, **Can create group → No**, **External → No**, **Confirmation → Skip user confirmation**
- [ ] Save. Log out as root. Log back in as the new break-glass user with the password above.
- [ ] **Enable 2FA (TOTP)**: Profile → Account → Two-Factor Authentication → Enable. Scan the QR code with an authenticator app on a phone/computer that you control. **Save the TOTP secret seed AND all 10 backup codes to the offline kit.** Verify by completing a 2FA challenge.
- [ ] Log out and back in via the bypass URL `https://<domain>/users/sign_in?auto_sign_in=false` to confirm the path works.
- [ ] Now demote the root account: log in as root one last time, **Admin → Users → root → Edit** → set a fresh 32-char random password (also save to offline kit), block the account, save. From now on, all local-auth admin access is via the break-glass account.

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

This is the biggest TODO right now — the cloud-init does **not** install Prometheus/Alertmanager/Grafana yet. You'll do it by hand following DESIGN.md §7 until the next iteration scripts it.

- [ ] `apt-get install prometheus prometheus-node-exporter prometheus-blackbox-exporter alertmanager grafana`
- [ ] Drop `monitoring/alerts.yml` from this repo into `/etc/prometheus/alerts.yml`
- [ ] Configure `prometheus.yml` to scrape `localhost:9100` (node), `localhost:9115` (blackbox probe of `/-/health`), `localhost:9168` (gitlab-exporter — install separately if you want GitLab-specific metrics), and load `/etc/prometheus/alerts.yml`
- [ ] Configure `alertmanager.yml` with the SMTP creds from `seed.yaml` and a route for `severity: critical` → email + webhook
- [ ] Enable the node_exporter textfile collector with `--collector.textfile.directory=/var/lib/node_exporter/textfile_collector` so the backup cron metrics get picked up
- [ ] Provision the **external observer** (see DESIGN.md §7.5) — a ~5 EUR/mo non-Hetzner VPS that probes the LB and watches for the `Watchdog` alert. This is the dead-man's-switch.
- [ ] Trigger a deliberate failure (stop the GitLab service) to confirm the alert fires end-to-end. Restart immediately after.

---

## 8. Schedule the weekly restore-test (15 min)

This is the single most important thing in the entire deployment. Backups you haven't tested are aspirations, not insurance.

- [ ] Author a cron entry (or systemd timer) that runs weekly, provisions a CX21 via the Hetzner API, installs the same pinned GitLab version, restores the latest Borg archive, runs `gitlab-rake gitlab:check`, then destroys the test VM
- [ ] Emit `gitlab_restore_test_success{} 1|0` to the textfile collector
- [ ] Run it manually once to confirm the whole chain works
- [ ] Confirm `monitoring/alerts.yml`'s `RestoreTestFail` alert would fire by manually setting the metric to `0`

If you skip this step, you have a fancy backup architecture and no actual disaster recovery capability.

---

## 9. Build the offline recovery kit (15 min)

Put the following on an encrypted USB drive (or split between two — one for off-site, one in a safe):

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
