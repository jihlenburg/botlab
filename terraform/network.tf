# =============================================================================
# Private Network Configuration
# =============================================================================

resource "hcloud_network" "main" {
  name     = "acme-gitlab-network"
  ip_range = var.network_cidr

  labels = merge(var.common_labels, {
    component = "network"
  })
}

resource "hcloud_network_subnet" "production" {
  network_id   = hcloud_network.main.id
  type         = "cloud"
  network_zone = "eu-central"
  ip_range     = var.subnet_cidr
}

# =============================================================================
# Floating IP for GitLab (optional, for IP persistence during recovery)
# =============================================================================

resource "hcloud_primary_ip" "gitlab" {
  name          = "gitlab-primary-ip"
  datacenter    = "${var.location}-dc14"
  type          = "ipv4"
  assignee_type = "server"
  auto_delete   = false

  labels = merge(var.common_labels, {
    component = "gitlab"
  })
}
