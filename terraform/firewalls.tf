# =============================================================================
# Firewall Configuration
# =============================================================================

# -----------------------------------------------------------------------------
# Public Firewall - GitLab Server
# -----------------------------------------------------------------------------

resource "hcloud_firewall" "gitlab_public" {
  name = "gitlab-public-fw"

  labels = merge(var.common_labels, {
    component = "gitlab"
    type      = "public"
  })

  # HTTPS from anywhere (through load balancer)
  rule {
    direction  = "in"
    protocol   = "tcp"
    port       = "443"
    source_ips = ["0.0.0.0/0", "::/0"]
  }

  # HTTP for Let's Encrypt ACME challenges
  rule {
    direction  = "in"
    protocol   = "tcp"
    port       = "80"
    source_ips = ["0.0.0.0/0", "::/0"]
  }

  # SSH for Git operations + admin access (restricted to trusted IPs if provided)
  dynamic "rule" {
    for_each = length(var.trusted_ssh_ips) > 0 ? [1] : []
    content {
      direction  = "in"
      protocol   = "tcp"
      port       = "22"
      source_ips = var.trusted_ssh_ips
    }
  }

  # Fallback: SSH from anywhere if no trusted IPs specified (NOT recommended for production)
  dynamic "rule" {
    for_each = length(var.trusted_ssh_ips) == 0 ? [1] : []
    content {
      direction  = "in"
      protocol   = "tcp"
      port       = "22"
      source_ips = ["0.0.0.0/0", "::/0"]
    }
  }

  # Allow all outbound
  rule {
    direction       = "out"
    protocol        = "tcp"
    port            = "any"
    destination_ips = ["0.0.0.0/0", "::/0"]
  }

  rule {
    direction       = "out"
    protocol        = "udp"
    port            = "any"
    destination_ips = ["0.0.0.0/0", "::/0"]
  }

  rule {
    direction       = "out"
    protocol        = "icmp"
    destination_ips = ["0.0.0.0/0", "::/0"]
  }
}
