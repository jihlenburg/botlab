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

  # SSH for Git operations + admin access. `trusted_ssh_ips` is a required,
  # non-empty variable (see variables.tf validation blocks). There is
  # deliberately NO fallback to 0.0.0.0/0 — security review T1.4 (2026-05-15).
  rule {
    direction  = "in"
    protocol   = "tcp"
    port       = "22"
    source_ips = var.trusted_ssh_ips
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
