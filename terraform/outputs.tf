# =============================================================================
# Terraform Outputs
# =============================================================================

# -----------------------------------------------------------------------------
# Server Information
# -----------------------------------------------------------------------------

output "gitlab_server_id" {
  description = "ID of the GitLab primary server"
  value       = hcloud_server.gitlab_primary.id
}

output "gitlab_server_public_ip" {
  description = "Public IPv4 address of GitLab server"
  value       = hcloud_server.gitlab_primary.ipv4_address
}

output "gitlab_server_private_ip" {
  description = "Private IP address of GitLab server"
  value       = var.gitlab_private_ip
}

# -----------------------------------------------------------------------------
# Load Balancer Information
# -----------------------------------------------------------------------------

output "load_balancer_id" {
  description = "ID of the load balancer"
  value       = hcloud_load_balancer.gitlab.id
}

output "load_balancer_ip" {
  description = "Public IP of the load balancer (point DNS here)"
  value       = hcloud_load_balancer.gitlab.ipv4
}

# -----------------------------------------------------------------------------
# Network Information
# -----------------------------------------------------------------------------

output "network_id" {
  description = "ID of the private network"
  value       = hcloud_network.main.id
}

output "subnet_id" {
  description = "ID of the production subnet"
  value       = hcloud_network_subnet.production.id
}

# -----------------------------------------------------------------------------
# Volume Information
# -----------------------------------------------------------------------------

output "gitlab_data_volume_id" {
  description = "ID of the GitLab data volume"
  value       = hcloud_volume.gitlab_data.id
}

output "gitlab_backups_volume_id" {
  description = "ID of the GitLab backups volume"
  value       = hcloud_volume.gitlab_backups.id
}

# -----------------------------------------------------------------------------
# Storage Box (Borg backup destination)
# -----------------------------------------------------------------------------
# After `terraform apply`, paste the sub-account server + username back
# into seed.yaml under `backup.storage_box.host` / `backup.storage_box.user`
# so `seed_bootstrap.py --target borg-conf` can emit the correct BORG_REPO.
# See docs/DEPLOY.md §1 for the documented sequence.

output "storage_box_id" {
  description = "ID of the primary Storage Box (for reference and import)"
  value       = hcloud_storage_box.gitlab_backups.id
}

output "storage_box_server" {
  description = "FQDN of the primary Storage Box. The PRIMARY (full-access) account; used only for emergency offline-key access — day-to-day backups use the sub-account below."
  value       = hcloud_storage_box.gitlab_backups.server
}

output "storage_box_username" {
  description = "Primary Storage Box username (Hetzner-assigned, format uXXXXX). Full read+write+delete via the OFFLINE SSH key only."
  value       = hcloud_storage_box.gitlab_backups.username
}

output "storage_box_subaccount_server" {
  description = "FQDN of the append-only sub-account — paste into seed.yaml backup.storage_box.host. This is what the GitLab server connects to for hourly Borg backups."
  value       = hcloud_storage_box_subaccount.gitlab_append_only.server
}

output "storage_box_subaccount_username" {
  description = "Username of the append-only sub-account (Hetzner-assigned, format uXXXXX-subN) — paste into seed.yaml backup.storage_box.user. Append-only enforcement is at the SSH command layer, installed by scripts/setup-borg-append-only.sh."
  value       = hcloud_storage_box_subaccount.gitlab_append_only.username
}

output "storage_box_subaccount_id" {
  description = "ID of the append-only sub-account (for reference, scripted rotations, and import)"
  value       = hcloud_storage_box_subaccount.gitlab_append_only.id
}

# -----------------------------------------------------------------------------
# DNS Configuration Instructions
# -----------------------------------------------------------------------------

output "dns_configuration" {
  description = "DNS records to configure"
  value = {
    gitlab_a_record = {
      name  = var.domain
      type  = "A"
      value = hcloud_load_balancer.gitlab.ipv4
      ttl   = 300
    }
    registry_cname = {
      name  = "registry.${var.domain}"
      type  = "CNAME"
      value = var.domain
      ttl   = 3600
    }
  }
}

# -----------------------------------------------------------------------------
# Connection Instructions
# -----------------------------------------------------------------------------

output "connection_instructions" {
  description = "How to connect to the server"
  value       = <<-EOT
    # SSH to GitLab server:
    ssh root@${hcloud_server.gitlab_primary.ipv4_address}

    # GitLab URL (after DNS configured):
    https://${var.domain}

    # Load Balancer IP (point DNS here):
    ${hcloud_load_balancer.gitlab.ipv4}
  EOT
}

output "storage_box_post_apply" {
  description = "Required follow-up steps after `terraform apply` for the Storage Box"
  value       = <<-EOT
    # 1. Paste these two values into seed.yaml under backup.storage_box:
    #      host: ${hcloud_storage_box_subaccount.gitlab_append_only.server}
    #      user: ${hcloud_storage_box_subaccount.gitlab_append_only.username}
    #
    # 2. Re-run the seed bootstrap to regenerate /etc/gitlab-backup.conf:
    #      python scripts/seed_bootstrap.py seed.yaml --target borg-conf
    #
    # 3. SCP the resulting conf to the server, then run:
    #      scripts/setup-borg-backup.sh        # init the Borg repo
    #      scripts/setup-borg-append-only.sh   # install append-only SSH key + shred full-access keys
    #
    # 4. For the OFFLINE recovery kit, record the PRIMARY account too:
    #      host: ${hcloud_storage_box.gitlab_backups.server}
    #      user: ${hcloud_storage_box.gitlab_backups.username}
    #    (used only with the offline full-access SSH private key)
  EOT
}
