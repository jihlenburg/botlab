# =============================================================================
# GitLab Primary Server
# =============================================================================

resource "hcloud_server" "gitlab_primary" {
  name        = "gitlab-primary"
  image       = var.server_image
  server_type = var.gitlab_server_type
  location    = var.location

  ssh_keys = [for key in hcloud_ssh_key.admin : key.id]

  public_net {
    ipv4_enabled = true
    ipv6_enabled = true
  }

  labels = merge(var.common_labels, {
    component = "gitlab"
    role      = "primary"
  })

  user_data = templatefile("${path.module}/templates/gitlab-cloud-init.yaml", {
    gitlab_domain    = var.domain
    admin_email      = var.admin_email
    data_volume_id   = hcloud_volume.gitlab_data.id
    backup_volume_id = hcloud_volume.gitlab_backups.id
  })

  lifecycle {
    ignore_changes = [
      user_data,
      ssh_keys,
    ]
  }
}

# Attach GitLab server to private network
resource "hcloud_server_network" "gitlab_primary" {
  server_id  = hcloud_server.gitlab_primary.id
  network_id = hcloud_network.main.id
  ip         = var.gitlab_private_ip
}

# Attach volumes to GitLab server
resource "hcloud_volume_attachment" "gitlab_data" {
  volume_id = hcloud_volume.gitlab_data.id
  server_id = hcloud_server.gitlab_primary.id
  automount = false
}

resource "hcloud_volume_attachment" "gitlab_backups" {
  volume_id = hcloud_volume.gitlab_backups.id
  server_id = hcloud_server.gitlab_primary.id
  automount = false
}

# Apply firewall to GitLab server
resource "hcloud_firewall_attachment" "gitlab_public" {
  firewall_id = hcloud_firewall.gitlab_public.id
  server_ids  = [hcloud_server.gitlab_primary.id]
}
