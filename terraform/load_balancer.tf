# =============================================================================
# Load Balancer Configuration
# =============================================================================

resource "hcloud_load_balancer" "gitlab" {
  name               = "gitlab-lb"
  load_balancer_type = "lb11"
  location           = var.location

  labels = merge(var.common_labels, {
    component = "load-balancer"
  })
}

# Attach Load Balancer to private network
resource "hcloud_load_balancer_network" "gitlab" {
  load_balancer_id = hcloud_load_balancer.gitlab.id
  network_id       = hcloud_network.main.id
  ip               = "10.0.1.2"
}

# HTTPS Service
resource "hcloud_load_balancer_service" "https" {
  load_balancer_id = hcloud_load_balancer.gitlab.id
  protocol         = "https"
  listen_port      = 443
  destination_port = 443

  http {
    sticky_sessions = true
    cookie_name     = "GITLABLB"
    certificates    = [hcloud_managed_certificate.gitlab.id]
  }

  health_check {
    protocol = "http"
    port     = 80
    interval = 15
    timeout  = 10
    retries  = 3

    http {
      path         = "/-/health"
      status_codes = ["200"]
    }
  }
}

# HTTP to HTTPS redirect
resource "hcloud_load_balancer_service" "http_redirect" {
  load_balancer_id = hcloud_load_balancer.gitlab.id
  protocol         = "http"
  listen_port      = 80
  destination_port = 80

  health_check {
    protocol = "http"
    port     = 80
    interval = 15
    timeout  = 10
    retries  = 3

    http {
      path         = "/-/health"
      status_codes = ["200"]
    }
  }
}

# Add GitLab server as target
resource "hcloud_load_balancer_target" "gitlab" {
  type             = "server"
  load_balancer_id = hcloud_load_balancer.gitlab.id
  server_id        = hcloud_server.gitlab_primary.id
  use_private_ip   = true

  depends_on = [
    hcloud_load_balancer_network.gitlab,
    hcloud_server_network.gitlab_primary
  ]
}

# Managed TLS Certificate
resource "hcloud_managed_certificate" "gitlab" {
  name         = "gitlab-cert"
  domain_names = [var.domain]

  labels = merge(var.common_labels, {
    component = "certificate"
  })
}
