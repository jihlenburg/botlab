# =============================================================================
# Hetzner Cloud Configuration Variables
# =============================================================================

variable "hcloud_token" {
  description = "Hetzner Cloud API token"
  type        = string
  sensitive   = true
}

variable "location" {
  description = "Hetzner datacenter location"
  type        = string
  default     = "fsn1"
}

variable "environment" {
  description = "Environment name (prod, staging, dev)"
  type        = string
  default     = "prod"
}

# =============================================================================
# Domain Configuration
# =============================================================================

variable "domain" {
  description = "Primary domain for GitLab"
  type        = string
  default     = "gitlab.example.com"
}

variable "admin_email" {
  description = "Admin email for Let's Encrypt and notifications"
  type        = string
  default     = "admin@example.com"
}

# =============================================================================
# Server Configuration
# =============================================================================

variable "gitlab_server_type" {
  description = "Hetzner server type for GitLab primary"
  type        = string
  default     = "cpx31"
}

variable "admin_bot_server_type" {
  description = "Hetzner server type for Admin Bot"
  type        = string
  default     = "cx32"
}

variable "server_image" {
  description = "OS image for servers"
  type        = string
  default     = "ubuntu-24.04"
}

# =============================================================================
# Storage Configuration
# =============================================================================

variable "gitlab_data_volume_size" {
  description = "Size of GitLab data volume in GB"
  type        = number
  default     = 200
}

variable "gitlab_backup_volume_size" {
  description = "Size of GitLab backup staging volume in GB"
  type        = number
  default     = 100
}

# =============================================================================
# Network Configuration
# =============================================================================

variable "network_cidr" {
  description = "CIDR for the private network"
  type        = string
  default     = "10.0.0.0/16"
}

variable "subnet_cidr" {
  description = "CIDR for the production subnet"
  type        = string
  default     = "10.0.1.0/24"
}

variable "gitlab_private_ip" {
  description = "Private IP for GitLab server"
  type        = string
  default     = "10.0.1.10"
}

variable "admin_bot_private_ip" {
  description = "Private IP for Admin Bot server"
  type        = string
  default     = "10.0.1.30"
}

# =============================================================================
# SSH Configuration
# =============================================================================

variable "ssh_public_keys" {
  description = "Map of SSH public keys for admin access"
  type        = map(string)
  default     = {}
}

variable "trusted_ssh_ips" {
  description = "List of trusted IPs for SSH access to admin bot"
  type        = list(string)
  default     = []
}

# =============================================================================
# Storage Box Configuration (for backups)
# =============================================================================

variable "storage_box_host" {
  description = "Storage Box hostname"
  type        = string
  default     = ""
}

variable "storage_box_user" {
  description = "Storage Box username"
  type        = string
  default     = ""
}

# =============================================================================
# Tags
# =============================================================================

variable "common_labels" {
  description = "Common labels to apply to all resources"
  type        = map(string)
  default = {
    project     = "acme-gitlab"
    managed_by  = "terraform"
  }
}
