# Offline Recovery Kit — Template

> **Use**: copy this file, fill in every `<...>` placeholder, store the result on
> FDE-encrypted media (or print on paper for a physical safe). Verify quarterly.
> Re-issue after any rotation event.
>
> **Security**: this kit contains the keys to the entire infrastructure. Treat
> it like a master password. Splitting between two physical locations (off-site
> + on-site safe) is recommended so loss of one doesn't lose the kit.
>
> **Cross-references**:
>
> - [DESIGN.md](DESIGN.md) §6 (DR), §5.3.3 (break-glass), Appendix C (secrets layering), Appendix C.8 (rotation cadence)
> - [DEPLOY.md](DEPLOY.md) §9 (initial kit assembly during first deploy)
> - [RUNBOOK-RECOVERY.md](RUNBOOK-RECOVERY.md) (this kit's whole reason for existing) — Appendix D for SSO recovery specifically

---

## Kit metadata

| Field | Value |
|-------|-------|
| **Kit format** | <FDE USB / printed in safe / both> |
| **Stored at** | <physical location 1>, <physical location 2> |
| **Operators with access** | <names> |
| **Kit created** | YYYY-MM-DD |
| **Kit last refreshed** | YYYY-MM-DD |
| **Next quarterly verification due** | YYYY-MM-DD |

---

## 1. Infrastructure provisioning

These secrets live ONLY in this kit and on the operator's laptop. Per
DESIGN.md Appendix C.3 (Layer 1), they must NEVER be copied to the GitLab
server.

- **Hetzner Cloud API token**: `<hcloud_token>`
  - Created: YYYY-MM-DD  •  Last rotated: YYYY-MM-DD  •  Next rotation: YYYY-MM-DD (6 months)
- **Domain**: `<gitlab.yourcompany.com>`
- **GitLab CE version pinned**: `<e.g. 17.10.0-ce.0>`
- **Hetzner project ID**: `<id>`

## 2. Borg backups

- **Storage Box host**: `<uXXXXX.your-storagebox.de>`
- **Storage Box main-account user**: `<uXXXXX>`
- **Borg full-access SSH private key** (multi-line — paste full PEM):
  ```
  -----BEGIN OPENSSH PRIVATE KEY-----
  <paste full key here>
  -----END OPENSSH PRIVATE KEY-----
  ```
  > This is the key `setup-borg-append-only.sh` Step 7 prompts you to shred from the server. It must exist only here.
- **Borg encryption passphrase** (32+ chars): `<passphrase>`
- **Last passphrase rotation**: YYYY-MM-DD  •  Next: YYYY-MM-DD (12 months)
- **Last full-access SSH key rotation**: YYYY-MM-DD  •  Next: YYYY-MM-DD (24 months)

## 3. S3 immutable backup (if configured)

- **Provider**: `<Wasabi / Backblaze B2 / AWS S3>`
- **Endpoint**: `<endpoint>`
- **Bucket**: `<bucket>`
- **Access key**: `<access key>`
- **Secret key**: `<secret key>`
- **Last rotation**: YYYY-MM-DD

## 4. Break-glass GitLab admin account

> Created via `scripts/setup-break-glass.sh`. Verified via
> `scripts/verify-break-glass.sh` quarterly. Recovery procedure:
> RUNBOOK-RECOVERY.md Appendix D.

- **Username**: `<recovery-XXXXXX>`
- **Email**: `<break-glass-XXXXXXXX@your-local-domain>`
- **Password** (32-char random): `<password>`
- **TOTP secret seed (base32)**: `<base32 string>`
- **TOTP provisioning URI** (otpauth://): `<otpauth://...>`
- **Backup codes** (each one-time use; cross out as consumed):
  - [ ] `<code 1>`
  - [ ] `<code 2>`
  - [ ] `<code 3>`
  - [ ] `<code 4>`
  - [ ] `<code 5>`
  - [ ] `<code 6>`
  - [ ] `<code 7>`
  - [ ] `<code 8>`
  - [ ] `<code 9>`
  - [ ] `<code 10>`
- **Bypass login URL**: `https://<gitlab.yourcompany.com>/users/sign_in?auto_sign_in=false`
- **Last verified**: YYYY-MM-DD (run `verify-break-glass.sh` AND log in)
- **Last password rotation**: YYYY-MM-DD (rotate after every use)
- **Last TOTP rotation**: YYYY-MM-DD (rotate on suspected leak; see Appendix D §D.7)

## 5. Disabled root account (backup-to-the-backup)

> Per DEPLOY.md §5b, the GitLab `root` account is set to a fresh random
> password and blocked. This password is here in case the break-glass
> account itself is lost.

- **Username**: `root`
- **Password**: `<password>`
- **Last rotation**: YYYY-MM-DD

## 6. GitLab encryption keys

- **`/etc/gitlab/gitlab-secrets.json`** — large JSON file, stored as a
  separate file in this kit (not pasted inline).
  - Kit filename: `<kit-gitlab-secrets-YYYYMMDD.json>`
  - Captured: YYYY-MM-DD
  - Refresh after every successful `gitlab-ctl reconfigure` that touches secrets.

## 7. Terraform state snapshot

- **State file** — stored as a separate file in this kit.
  - Kit filename: `<kit-terraform-YYYYMMDD.tfstate>`
  - Snapshot date: YYYY-MM-DD
  - Refresh after every successful `terraform apply`.

## 8. Operator SSH private keys

> Private halves of the keys whose public halves are in `seed.yaml ->
> infrastructure.ssh.admin_keys`. Used during DR to SSH into the
> provisioned replacement server.

| Operator | Filename in kit | Notes |
|----------|-----------------|-------|
| `<name 1>` | `<kit-ssh-name1>` | YubiKey-resident preferred |
| `<name 2>` | `<kit-ssh-name2>` | |

## 9. Printed reference documents

Include hard copies (or read-only PDFs on the same media):

- [ ] `docs/RUNBOOK-RECOVERY.md` — full document, especially Appendix D (SSO failure)
- [ ] `docs/DESIGN.md` §6 (DR), §5.3.3 (break-glass), Appendix C (secrets)
- [ ] This kit, blank, as a reference for what the filled version should contain

## 10. SSO provider (Azure AD / Entra)

- **Tenant ID**: `<tenant id>`
- **Enterprise App display name**: `GitLab ACME Corp`
- **Object ID of the Enterprise App**: `<id>`
- **Current IdP signing cert thumbprint**: `<thumbprint>` (capture on rotation)
- **Cert expiry**: YYYY-MM-DD
- **Cert rotation procedure**: see DESIGN.md Appendix C.8

## 11. SMTP

- **Host**: `<smtp.office365.com>`
- **Port**: `587`
- **User**: `<gitlab-noreply@your-domain>`
- **Password**: `<smtp password>`
- **Last rotation**: YYYY-MM-DD

---

## Verification log

Append a line every time the kit is exercised, real or test. Format:
`YYYY-MM-DD | <verifier> | <event> | <outcome>`

| Date | Verifier | Event | Outcome |
|------|----------|-------|---------|
| YYYY-MM-DD | <name> | Initial kit creation | OK |

---

## Rotation cadence (mirrors DESIGN.md Appendix C.8)

| Item | Cadence | Last | Next |
|------|---------|------|------|
| Borg encryption passphrase | 12 mo / operator turnover | YYYY-MM-DD | YYYY-MM-DD |
| Storage Box append-only key | 12 mo | YYYY-MM-DD | YYYY-MM-DD |
| Storage Box full-access key | 24 mo | YYYY-MM-DD | YYYY-MM-DD |
| `hcloud_token` | 6 mo / operator turnover | YYYY-MM-DD | YYYY-MM-DD |
| SMTP password | 12 mo | YYYY-MM-DD | YYYY-MM-DD |
| SAML cert | per Azure AD lifetime | YYYY-MM-DD | YYYY-MM-DD |
| Break-glass password | after every use | YYYY-MM-DD | (event-driven) |
| Break-glass TOTP secret | on suspected leak | YYYY-MM-DD | (event-driven) |
| Kit verification (script) | quarterly | YYYY-MM-DD | YYYY-MM-DD |
| Kit verification (real login) | annually | YYYY-MM-DD | YYYY-MM-DD |
