# Disaster Recovery Runbook

**Purpose**: single operator-facing document for recovering the ACME GitLab instance from total loss of the primary server. If you are reading this during an incident, start at section 1 and do not skip steps.

**Targets**: RPO ~1 hour, RTO ~1-2 hours.

**Prerequisites you must have on hand BEFORE starting:**

- Your offline recovery kit, containing:
  - Borg **full-access** key/passphrase (the append-only key on the GitLab server CANNOT decrypt archives)
  - `gitlab-secrets.json` from a recent backup (also lives in Borg, but a separate copy on offline media is cheaper insurance)
  - Snapshot of `terraform.tfstate` (or remote state credentials)
  - SSH private key matching `ssh_public_keys` in `terraform.tfvars`
- A recovery workstation that is **not** the compromised/lost GitLab server
- Network access from that workstation to:
  - Hetzner Cloud API (for `terraform apply`)
  - Hetzner Storage Box (port 23, for Borg)
  - The new server's public IP (for SSH and `scp`)
- The `gitlab.version` you were running. If unknown, check the `seed.yaml` in the repo — it is the source of truth.

If you don't have all of the above, stop and assemble them first. Improvising under pressure is how you lose the second copy.

---

## 0. Triage (5 minutes)

Before destroying or replacing anything, confirm you actually need a full recovery:

- [ ] `https://<domain>/-/health` returns non-200 or times out
- [ ] SSH to the GitLab server either fails outright or shows the host in an unrecoverable state (corrupted FS, ransomware indicators, missing data)
- [ ] You have decided that fixing the existing server in place is **not** the right move (corruption suspected, integrity uncertain, or compromise confirmed)

If you can recover in place (service crashed, reconfigure needed, disk full but data intact), use the operational procedures in `docs/DESIGN.md` §12 instead. **Don't run this runbook.**

If you are recovering from suspected ransomware: do **not** shut down the affected server. Detach it from the network (firewall rule blocking inbound 22/80/443) so you can take a forensic image later, then proceed.

---

## 1. Verify backup integrity (10 minutes)

Before relying on a backup to rebuild, verify it. If both tiers are corrupted, recovery is offline-tape-only and outside this runbook.

On the recovery workstation, with the offline Borg full-access key loaded:

```bash
export BORG_REPO="ssh://uXXXXX@uXXXXX.your-storagebox.de:23/./gitlab-borg"
export BORG_PASSPHRASE="<from offline kit>"

# List recent archives — confirm there is something from within the last hour
borg list "$BORG_REPO" | tail -10

# Integrity check (this is what the weekly cron also runs)
borg check --repository-only "$BORG_REPO"

# Identify the archive you want to restore. Pick the most recent one that
# predates the suspected incident.
LATEST="$(borg list --short "$BORG_REPO" | tail -1)"
echo "Will restore from: $LATEST"
```

If `borg check` fails, fall through to the S3 Object Lock copy:

```bash
# List S3 objects under retention
aws s3 ls "s3://<bucket>/" --endpoint-url "<endpoint>"

# Download the latest Object-Lock-protected backup
aws s3 cp "s3://<bucket>/<key>" ./gitlab-backup.tar --endpoint-url "<endpoint>"
```

Continue with the file you downloaded; the steps below assume `$LATEST` from Borg, but the same restore commands work against the S3-sourced tarball with minor adjustments noted inline.

---

## 2. Provision the replacement server (5 minutes)

From your local checkout of this repo, with `terraform.tfvars` populated (use the one from your offline kit if your laptop doesn't already have it):

```bash
cd terraform
terraform init     # if state is fresh
terraform apply -target=hcloud_server.gitlab_primary
```

This brings up a new CPX31 in Falkenstein with the cloud-init that installs GitLab CE at the pinned version. **Wait for cloud-init to finish** — typically 10-15 minutes. Confirm with:

```bash
NEW_IP="$(terraform output -raw gitlab_server_public_ip)"
ssh root@$NEW_IP 'cloud-init status --wait'
ssh root@$NEW_IP 'gitlab-ctl status'  # expect services 'down' until config restored
```

If `gitlab-ctl` reports the package isn't installed, cloud-init isn't done. Don't proceed.

**Note**: if the original incident took out the entire Hetzner account, you'll have to provision in a fresh account and update `hcloud_token` in `terraform.tfvars` first. Terraform will rebuild from scratch using the state in your offline kit.

---

## 3. Restore configuration (5 minutes)

On the recovery workstation:

```bash
borg extract "$BORG_REPO::$LATEST" etc/gitlab/gitlab.rb etc/gitlab/gitlab-secrets.json
scp etc/gitlab/gitlab.rb root@$NEW_IP:/etc/gitlab/gitlab.rb
scp etc/gitlab/gitlab-secrets.json root@$NEW_IP:/etc/gitlab/gitlab-secrets.json
ssh root@$NEW_IP 'chmod 600 /etc/gitlab/gitlab.rb /etc/gitlab/gitlab-secrets.json'
```

`gitlab-secrets.json` is **critical**: without it, every encrypted column in the DB (CI variables, integration tokens, 2FA secrets) becomes unreadable.

---

## 4. Restore the backup (30-60 minutes)

```bash
# Extract the latest GitLab tarball from Borg on the workstation
borg extract "$BORG_REPO::$LATEST" 'var/opt/gitlab/backups/*_gitlab_backup.tar'
BACKUP_FILE="$(ls var/opt/gitlab/backups/*_gitlab_backup.tar | head -1)"

# Copy to the new server
scp "$BACKUP_FILE" root@$NEW_IP:/var/opt/gitlab/backups/

# Run the restore on the new server
ssh root@$NEW_IP bash <<'EOSSH'
set -e
chown git:git /var/opt/gitlab/backups/*_gitlab_backup.tar
gitlab-ctl stop puma
gitlab-ctl stop sidekiq
TIMESTAMP="$(ls -t /var/opt/gitlab/backups/*_gitlab_backup.tar | head -1 | sed 's|.*/||; s|_gitlab_backup\.tar$||')"
gitlab-backup restore BACKUP="$TIMESTAMP" force=yes
EOSSH
```

Restore time scales with repo and DB size. For ~20 developers and a few hundred GB of repos, 30-60 minutes is typical.

---

## 5. Reconfigure & verify (5 minutes)

```bash
ssh root@$NEW_IP bash <<'EOSSH'
set -e
gitlab-ctl reconfigure
gitlab-ctl restart
gitlab-rake gitlab:check SANITIZE=true
EOSSH

# From the workstation, hit the health endpoint
curl -fsS https://$NEW_IP/-/health    # may fail on certificate; that's fine, the LB has the cert
```

Sanity checks before declaring recovery successful:

- [ ] `gitlab-ctl status` shows all services `run`
- [ ] `gitlab-rake gitlab:check` reports no errors (warnings are usually OK; investigate any failures)
- [ ] You can log in to the web UI from your laptop using a known account
- [ ] You can `git clone` a known repository
- [ ] CI/CD: pipeline page loads; previously running jobs may need manual retry

---

## 6. Cut traffic over (5 minutes)

You have two options. Pick one based on whether the Load Balancer is intact.

**Option A — LB intact (most common)**:

```bash
cd terraform
terraform apply    # re-runs hcloud_load_balancer_target to point at the new server
```

The LB target is keyed on the server ID, which has changed. Terraform will reconcile.

**Option B — LB lost too**:

Update DNS directly to the new server's public IP. TTL is 300s by design (see DESIGN.md §4.4); propagation should complete within 5 minutes.

---

## 7. Post-recovery (do not skip)

- [ ] **Rotate every credential that touched the lost server**. Borg passphrase, GitLab admin password, every API token issued by GitLab, every personal access token used by CI, the SSH keys in `authorized_keys`. Do this even if you think the loss was hardware, not compromise.
- [ ] **Run a fresh backup immediately** to seed the new Borg archive lineage:
  ```bash
  ssh root@$NEW_IP /usr/local/bin/gitlab-backup-to-borg.sh
  ```
- [ ] **Trigger an out-of-band restore test** against the fresh backup to confirm the new server's backups are recoverable.
- [ ] **If the cause was compromise**: take a forensic image of the old server before destroying it. `hcloud server create-image` produces a snapshot you can pull down later for offline analysis.
- [ ] **Destroy the old server resource in Terraform** only after the forensic image (if any) is captured and the new server has been operating cleanly for at least one full backup cycle.
- [ ] **Write the post-incident report**. Include: detection method, recovery steps actually taken (deltas from this runbook), data loss assessment vs. RPO, action items.

---

## Appendix A — Restoring from the S3 Object Lock tier

If both Borg archives are lost or corrupted:

1. The S3 copy is a Borg-formatted archive (or a plain `gitlab-backup` tarball depending on how `scripts/backup-to-s3.sh` was configured). Inspect with:
   ```bash
   aws s3 cp "s3://<bucket>/<key>" ./recovered.tar --endpoint-url "<endpoint>"
   file recovered.tar
   tar tf recovered.tar | head
   ```
2. If it's a `gitlab-backup` tarball, skip step 3 of the main runbook and copy the tarball directly to `/var/opt/gitlab/backups/` on the new server, then proceed at step 4.
3. If it's a Borg archive, extract on the recovery workstation as in step 3 of the main runbook, sourcing the passphrase from your offline kit.

The S3 tier has 90-day retention. If the incident is older than 90 days and you have no Borg, the quarterly offline tape (Appendix B in SECURITY-ASSESSMENT.md) is the last resort.

---

## Appendix B — If the entire Hetzner account is lost

This is the worst documented case. Steps:

1. Open a fresh Hetzner account (or use a pre-staged secondary account if your offline kit specifies one).
2. Generate a new API token, put it in `terraform.tfvars`.
3. Run `terraform init` against the state snapshot from your offline kit. The state references resource IDs from the lost account — Terraform will plan to **destroy** everything it can't find and **create** replacements. That is what you want.
4. Run `terraform apply`. New infrastructure comes up.
5. Continue at section 3 of this runbook.

Total time in this case: ~3 hours, not 1-2. The cross-provider S3 tier (Wasabi/B2/AWS) becomes the only data source — be doubly sure to verify its integrity before relying on it.

---

## Appendix C — Tools used in this runbook

- `terraform` — server provisioning. Version pinned in `terraform/versions.tf`.
- `borg` — backup extraction. Installed on the recovery workstation; the server-side append-only key cannot be used here, you need the offline full-access key.
- `aws` CLI — S3 Object Lock tier. Configured against whichever provider holds the immutable bucket.
- `scripts/restore-gitlab.sh` — opinionated wrapper around steps 3-5. Use this if you want; the manual commands above are what it executes.
- `scripts/verify-backup.sh` — JSON-output sanity check on a candidate backup.
