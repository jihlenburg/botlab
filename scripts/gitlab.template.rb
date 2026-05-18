# =============================================================================
# GitLab CE Configuration Template
# =============================================================================
# Copy this to /etc/gitlab/gitlab.rb on the GitLab server
# Replace all <PLACEHOLDER> values with your actual configuration
# Run 'gitlab-ctl reconfigure' after changes

# =============================================================================
# External URL and SSL
# =============================================================================

external_url 'https://gitlab.example.com'

# Let's Encrypt (handled by load balancer, so disabled here)
letsencrypt['enable'] = false

# Nginx SSL configuration (load balancer terminates TLS)
nginx['listen_port'] = 80
nginx['listen_https'] = false
nginx['proxy_set_headers'] = {
  "X-Forwarded-Proto" => "https",
  "X-Forwarded-Ssl" => "on"
}

# Security headers
nginx['hsts_max_age'] = 31536000
nginx['ssl_protocols'] = "TLSv1.2 TLSv1.3"

# =============================================================================
# Object Storage (Hetzner S3-compatible)
# =============================================================================

gitlab_rails['object_store']['enabled'] = true
gitlab_rails['object_store']['proxy_download'] = true
gitlab_rails['object_store']['connection'] = {
  'provider' => 'AWS',
  'endpoint' => 'https://fsn1.your-objectstorage.com',
  'aws_access_key_id' => '<S3_ACCESS_KEY>',
  'aws_secret_access_key' => '<S3_SECRET_KEY>',
  'region' => 'fsn1',
  'path_style' => true
}

# Object storage buckets
gitlab_rails['object_store']['objects']['artifacts']['bucket'] = 'gitlab-acme-artifacts'
gitlab_rails['object_store']['objects']['lfs']['bucket'] = 'gitlab-acme-lfs'
gitlab_rails['object_store']['objects']['uploads']['bucket'] = 'gitlab-acme-uploads'
gitlab_rails['object_store']['objects']['packages']['bucket'] = 'gitlab-acme-packages'
gitlab_rails['object_store']['objects']['dependency_proxy']['bucket'] = 'gitlab-acme-dependency-proxy'
gitlab_rails['object_store']['objects']['terraform_state']['bucket'] = 'gitlab-acme-terraform-state'
gitlab_rails['object_store']['objects']['pages']['bucket'] = 'gitlab-acme-pages'

# =============================================================================
# Git LFS
# =============================================================================

gitlab_rails['lfs_enabled'] = true

# =============================================================================
# Container Registry
# =============================================================================

registry_external_url 'https://registry.gitlab.example.com'
gitlab_rails['registry_enabled'] = true
registry['enable'] = true
registry_nginx['listen_port'] = 5050
registry_nginx['listen_https'] = false

# =============================================================================
# SMTP Configuration (Microsoft 365)
# =============================================================================

gitlab_rails['smtp_enable'] = true
gitlab_rails['smtp_address'] = "smtp.office365.com"
gitlab_rails['smtp_port'] = 587
gitlab_rails['smtp_user_name'] = "gitlab-noreply@example.com"
gitlab_rails['smtp_password'] = "<SMTP_PASSWORD>"
gitlab_rails['smtp_domain'] = "example.com"
gitlab_rails['smtp_authentication'] = "login"
gitlab_rails['smtp_enable_starttls_auto'] = true
gitlab_rails['smtp_tls'] = false
gitlab_rails['smtp_openssl_verify_mode'] = 'peer'

gitlab_rails['gitlab_email_from'] = 'gitlab-noreply@example.com'
gitlab_rails['gitlab_email_display_name'] = 'GitLab ACME Corp'
gitlab_rails['gitlab_email_reply_to'] = 'noreply@example.com'

# =============================================================================
# Azure AD SSO (SAML 2.0)
# =============================================================================

gitlab_rails['omniauth_enabled'] = true
gitlab_rails['omniauth_allow_single_sign_on'] = ['saml']
gitlab_rails['omniauth_block_auto_created_users'] = false
gitlab_rails['omniauth_auto_link_saml_user'] = true
gitlab_rails['omniauth_auto_sign_in_with_provider'] = 'saml'

gitlab_rails['omniauth_providers'] = [
  {
    name: "saml",
    label: "ACME Corp SSO",
    args: {
      assertion_consumer_service_url: "https://gitlab.example.com/users/auth/saml/callback",
      idp_cert: "-----BEGIN CERTIFICATE-----\n<AZURE_AD_CERTIFICATE>\n-----END CERTIFICATE-----",
      idp_sso_target_url: "https://login.microsoftonline.com/<AZURE_TENANT_ID>/saml2",
      issuer: "https://gitlab.example.com",
      name_identifier_format: "urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress",
      attribute_statements: {
        email: ['http://schemas.xmlsoap.org/ws/2005/05/identity/claims/emailaddress'],
        name: ['http://schemas.xmlsoap.org/ws/2005/05/identity/claims/name'],
        first_name: ['http://schemas.xmlsoap.org/ws/2005/05/identity/claims/givenname'],
        last_name: ['http://schemas.xmlsoap.org/ws/2005/05/identity/claims/surname']
      }
    }
  }
]

# =============================================================================
# Security Hardening
# =============================================================================

# Disable public signups
gitlab_rails['gitlab_signup_enabled'] = false

# Require 2FA (with 7-day grace period for new users)
gitlab_rails['require_two_factor_authentication'] = true
gitlab_rails['two_factor_grace_period_in_hours'] = 168

# Session timeout (8 hours)
gitlab_rails['session_timeout'] = 28800

# Password requirements
gitlab_rails['minimum_password_length'] = 12

# Default project visibility
gitlab_rails['gitlab_default_projects_features_visibility_level'] = 'private'

# Restrict group creation
gitlab_rails['gitlab_default_can_create_group'] = false

# Disable Gravatar (privacy)
gitlab_rails['gravatar_enabled'] = false

# Rate limiting for authentication
gitlab_rails['rack_attack_git_basic_auth'] = {
  'enabled' => true,
  'ip_whitelist' => ["127.0.0.1", "10.0.0.0/8"],
  'maxretry' => 10,
  'findtime' => 60,
  'bantime' => 3600
}

# =============================================================================
# Backup Configuration
# =============================================================================

gitlab_rails['backup_keep_time'] = 86400  # 1 day local retention
gitlab_rails['backup_path'] = "/var/opt/gitlab/backups"
gitlab_rails['backup_archive_permissions'] = 0600

# =============================================================================
# Monitoring (Prometheus)
# =============================================================================

prometheus_monitoring['enable'] = true
prometheus['enable'] = true
prometheus['listen_address'] = '0.0.0.0:9090'

# Node exporter
node_exporter['enable'] = true
node_exporter['listen_address'] = '0.0.0.0:9100'

# GitLab exporter
gitlab_exporter['enable'] = true
gitlab_exporter['listen_address'] = '0.0.0.0'
gitlab_exporter['listen_port'] = 9168

# =============================================================================
# Performance Tuning (for CPX31: 4 vCPU, 16GB RAM)
# =============================================================================

# Puma workers (web server)
puma['worker_processes'] = 3

# Sidekiq (background jobs)
sidekiq['max_concurrency'] = 20

# PostgreSQL
postgresql['shared_buffers'] = "4GB"
postgresql['work_mem'] = "64MB"
postgresql['maintenance_work_mem'] = "512MB"
postgresql['effective_cache_size'] = "12GB"

# Redis
redis['maxmemory'] = "2gb"
redis['maxmemory_policy'] = "allkeys-lru"

# Gitaly (Git RPC service)
gitaly['configuration'] = {
  concurrency: [
    {
      'rpc' => "/gitaly.SmartHTTPService/PostReceivePack",
      'max_per_repo' => 3,
    },
  ],
}

# =============================================================================
# Logging
# =============================================================================

gitlab_rails['log_level'] = 'info'
logging['logrotate_frequency'] = 'daily'
logging['logrotate_size'] = nil
logging['logrotate_rotate'] = 30
logging['logrotate_compress'] = 'compress'
logging['logrotate_method'] = 'copytruncate'
