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
