# =============================================================================
# Firewall Configuration
# =============================================================================

# -----------------------------------------------------------------------------
# Public Firewall - GitLab Server (via Load Balancer)
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

  # SSH for Git operations
  rule {
    direction  = "in"
    protocol   = "tcp"
    port       = "22"
    source_ips = ["0.0.0.0/0", "::/0"]
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

# -----------------------------------------------------------------------------
# Internal Firewall - GitLab Server (from Admin Bot)
# -----------------------------------------------------------------------------

resource "hcloud_firewall" "gitlab_internal" {
  name = "gitlab-internal-fw"

  labels = merge(var.common_labels, {
    component = "gitlab"
    type      = "internal"
  })

  # Prometheus metrics from Admin Bot
  rule {
    direction  = "in"
    protocol   = "tcp"
    port       = "9090"
    source_ips = ["${var.admin_bot_private_ip}/32"]
  }

  # Node exporter from Admin Bot
  rule {
    direction  = "in"
    protocol   = "tcp"
    port       = "9100"
    source_ips = ["${var.admin_bot_private_ip}/32"]
  }

  # GitLab exporter from Admin Bot
  rule {
    direction  = "in"
    protocol   = "tcp"
    port       = "9168"
    source_ips = ["${var.admin_bot_private_ip}/32"]
  }

  # Admin SSH from Admin Bot (restricted)
  rule {
    direction  = "in"
    protocol   = "tcp"
    port       = "22"
    source_ips = ["${var.admin_bot_private_ip}/32"]
  }

  # All internal traffic within subnet
  rule {
    direction  = "in"
    protocol   = "tcp"
    port       = "any"
    source_ips = [var.subnet_cidr]
  }
}

# -----------------------------------------------------------------------------
# Admin Bot Firewall
# -----------------------------------------------------------------------------

resource "hcloud_firewall" "admin_bot" {
  name = "admin-bot-fw"

  labels = merge(var.common_labels, {
    component = "admin-bot"
  })

  # SSH from trusted IPs only
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

  # Prometheus/Grafana web UI (optional, from internal only)
  rule {
    direction  = "in"
    protocol   = "tcp"
    port       = "3000"
    source_ips = [var.subnet_cidr]
  }

  rule {
    direction  = "in"
    protocol   = "tcp"
    port       = "9090"
    source_ips = [var.subnet_cidr]
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
