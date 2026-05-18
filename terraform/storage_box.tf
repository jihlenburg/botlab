# =============================================================================
# Storage Box (Backup Destination)
# =============================================================================
#
# Holds the only ransomware-resistant copy of GitLab data on Hetzner
# infrastructure. Provisioned via the unified Hetzner Cloud API as of
# provider v1.63.0 (May 2026) — previously required a separate Hetzner Robot
# account (see DEPLOY.md v2.6 vs v2.7).
#
# CRITICAL DESIGN NOTES:
#
# 1. `lifecycle { prevent_destroy = true }` on BOTH resources is non-negotiable.
#    A `terraform destroy` against this state would wipe the backup repo —
#    the entire ransomware-protection mechanism. Removing the guard requires
#    a code review by a second operator. See docs/DESIGN.md §9.
#
# 2. The `ssh_keys` attribute on `hcloud_storage_box` is create-only at the
#    Hetzner API level — changing it forces resource replacement, which
#    destroys the box and its contents. `ignore_changes = [ssh_keys]` is
#    mandatory. SSH key rotation goes through SFTP, not Terraform; see
#    docs/DESIGN.md Appendix C.8 for the rotation runbook.
#
# 3. The "append-only" property of the sub-account is NOT a Hetzner-side
#    permission (the API only offers `readonly`, which would block writes
#    too). Append-only is enforced at the SSH command layer via a forced
#    `borg serve --append-only --restrict-to-repository` prefix in the
#    sub-account's `~/.ssh/authorized_keys`. That install step still lives
#    in `scripts/setup-borg-append-only.sh` — Terraform creates the
#    sub-account, the script wires the constrained SSH key.
#
# 4. The primary Storage Box password and the sub-account password are
#    BOTH stored in seed.yaml. The primary password is for emergency UI
#    access only; day-to-day SSH auth uses the keys. The sub-account
#    password is needed by the script to SFTP in and install the
#    authorized_keys file.
#
# 5. The primary Storage Box's SSH key is the OPERATOR'S OFFLINE
#    full-access key — public half here, private half exclusively in the
#    offline recovery kit. NEVER on the GitLab server. See DEPLOY.md §2a.

resource "hcloud_storage_box" "gitlab_backups" {
  name             = var.storage_box_name
  storage_box_type = var.storage_box_type
  location         = var.storage_box_location
  password         = var.storage_box_password

  # Public half of the OFFLINE full-access key. Private half lives only in
  # the offline recovery kit (docs/OFFLINE-KIT-TEMPLATE.md §2).
  ssh_keys = [var.storage_box_ssh_public_key]

  access_settings = {
    ssh_enabled          = true
    reachable_externally = true
    samba_enabled        = false
    webdav_enabled       = false
    zfs_enabled          = false
  }

  # Hetzner-side guard (separate from Terraform's prevent_destroy below).
  # Both required: Terraform's guard catches `terraform destroy`, Hetzner's
  # catches deletion attempts via the API or Console with a different token.
  delete_protection = true

  labels = merge(var.common_labels, {
    component = "backup"
    purpose   = "borg-repo"
    tier      = "primary-immutable"
  })

  lifecycle {
    # See design note (1). Removing this requires deliberate operator action.
    prevent_destroy = true

    # See design note (2). Rotate SSH keys via SFTP, not via this attribute.
    ignore_changes = [ssh_keys]
  }
}

resource "hcloud_storage_box_subaccount" "gitlab_append_only" {
  storage_box_id = hcloud_storage_box.gitlab_backups.id

  name        = "gitlab-append-only"
  description = "Append-only sub-account used by the hourly Borg backup cron on the GitLab server. Append-only is enforced at SSH command layer (forced borg-serve --append-only in authorized_keys), installed by scripts/setup-borg-append-only.sh — NOT by the Hetzner sub-account permission model (which only offers full-rw or readonly)."

  # The home directory is where the sub-account SSHes in. Borg writes the
  # repo at $HOME/gitlab-borg (see seed_schema.borg_repo).
  home_directory = "borg"

  password = var.storage_box_subaccount_password

  access_settings = {
    ssh_enabled          = true
    reachable_externally = true
    samba_enabled        = false
    webdav_enabled       = false
    # readonly intentionally left unset (= false). See design note (3) —
    # append-only is enforced one layer down, in authorized_keys.
  }

  labels = {
    component = "backup"
    role      = "append-only"
  }

  lifecycle {
    # See design note (1).
    prevent_destroy = true
  }
}
