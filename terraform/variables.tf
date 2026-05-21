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
  default     = "hel1"
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

variable "gitlab_version" {
  description = "Pinned GitLab CE apt package version (e.g. 17.10.0-ce.0). See docs/DESIGN.md §5.6 for the upgrade runbook."
  type        = string
  default     = "17.10.0-ce.0"
}

# =============================================================================
# Server Configuration
# =============================================================================

variable "gitlab_server_type" {
  description = "Hetzner server type for GitLab primary"
  type        = string
  default     = "cpx31"
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

# =============================================================================
# SSH Configuration
# =============================================================================

variable "ssh_public_keys" {
  description = "Map of SSH public keys for admin access"
  type        = map(string)
  default     = {}
}

variable "trusted_ssh_ips" {
  description = "List of CIDRs allowed to SSH to the GitLab server. REQUIRED — must be a non-empty list of valid CIDRs. There is no fallback to 0.0.0.0/0; a missing or empty value will fail `terraform plan` (security review T1.4)."
  type        = list(string)

  validation {
    condition     = length(var.trusted_ssh_ips) > 0
    error_message = "trusted_ssh_ips must contain at least one CIDR. Open SSH (0.0.0.0/0) is not permitted; set explicit CIDRs in terraform.tfvars or in seed.yaml -> infrastructure.ssh.trusted_ips."
  }

  validation {
    condition     = alltrue([for c in var.trusted_ssh_ips : can(cidrnetmask(c))])
    error_message = "Every entry in trusted_ssh_ips must be a valid CIDR (e.g. 203.0.113.10/32, 198.51.100.0/24, 2001:db8::/32)."
  }
}

# =============================================================================
# Storage Box (Borg backup destination)
# =============================================================================
# Provisioned by `terraform/storage_box.tf` against the unified Hetzner Cloud
# API. The Storage Box product moved from Hetzner Robot to Cloud Console;
# the hcloud Terraform provider added support in v1.63.0 (May 2026).
#
# Every variable below is REQUIRED — there are no production-safe defaults
# for credentials or for the SSH key (which is the OFFLINE full-access key
# that must NEVER live on the GitLab server).

variable "storage_box_name" {
  description = "Name of the Storage Box (Hetzner Cloud Console label). Cosmetic; does not affect hostname (Hetzner assigns the FQDN)."
  type        = string
}

variable "storage_box_type" {
  description = "Storage Box plan. bx11 (1TB ~6 EUR), bx21 (5TB ~16 EUR), bx31 (10TB ~30 EUR), bx41 (20TB ~58 EUR). Recommended floor: bx21."
  type        = string
  default     = "bx21"

  validation {
    condition     = contains(["bx11", "bx21", "bx31", "bx41"], var.storage_box_type)
    error_message = "storage_box_type must be one of: bx11, bx21, bx31, bx41."
  }
}

variable "storage_box_location" {
  description = "Storage Box location. Recommended: same region as the GitLab server (hel1 for this project) — Hetzner places it in a different DC within the region. Cross-region (e.g. fsn1 or nbg1) gives geo-diversity at the cost of WAN backup latency."
  type        = string
  default     = "hel1"

  validation {
    condition     = contains(["fsn1", "nbg1", "hel1"], var.storage_box_location)
    error_message = "storage_box_location must be one of: fsn1, nbg1, hel1."
  }
}

variable "storage_box_password" {
  description = "Primary Storage Box password. Used for emergency Hetzner Console access only — day-to-day Borg backups authenticate via SSH key. Generate with `openssl rand -base64 24`. Store in offline recovery kit and in seed.yaml (encrypted)."
  type        = string
  sensitive   = true

  validation {
    condition     = length(var.storage_box_password) >= 20
    error_message = "storage_box_password must be >= 20 characters (Hetzner requires complex passwords; this is an extra floor)."
  }
}

variable "storage_box_ssh_public_key" {
  description = "Public half of the OFFLINE full-access SSH key for the primary Storage Box account. Private half MUST live only in the offline recovery kit (DEPLOY.md §2a). Format: full ssh-ed25519 / ssh-rsa line."
  type        = string

  validation {
    condition     = can(regex("^(ssh-ed25519|ssh-rsa|ecdsa-sha2-nistp[0-9]+) [A-Za-z0-9+/=]+( .*)?$", var.storage_box_ssh_public_key))
    error_message = "storage_box_ssh_public_key must be a valid OpenSSH-format public key line (ssh-ed25519, ssh-rsa, or ecdsa-sha2-nistp*)."
  }
}

variable "storage_box_subaccount_password" {
  description = "Password for the append-only Storage Box sub-account. Used by scripts/setup-borg-append-only.sh to SFTP in and install the forced-command authorized_keys file. After that, Borg uses the SSH key, not this password. Generate with `openssl rand -base64 24`."
  type        = string
  sensitive   = true

  validation {
    condition     = length(var.storage_box_subaccount_password) >= 20
    error_message = "storage_box_subaccount_password must be >= 20 characters."
  }
}

# =============================================================================
# Tags
# =============================================================================

variable "common_labels" {
  description = "Common labels to apply to all resources"
  type        = map(string)
  default = {
    project    = "acme-gitlab"
    managed_by = "terraform"
  }
}
