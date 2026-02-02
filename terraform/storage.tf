# =============================================================================
# Block Storage Volumes
# =============================================================================

# GitLab data volume (repositories, PostgreSQL)
resource "hcloud_volume" "gitlab_data" {
  name      = "gitlab-data"
  size      = var.gitlab_data_volume_size
  location  = var.location
  format    = "ext4"
  automount = false

  labels = merge(var.common_labels, {
    component = "gitlab"
    purpose   = "data"
  })
}

# GitLab backup staging volume
resource "hcloud_volume" "gitlab_backups" {
  name      = "gitlab-backups"
  size      = var.gitlab_backup_volume_size
  location  = var.location
  format    = "ext4"
  automount = false

  labels = merge(var.common_labels, {
    component = "gitlab"
    purpose   = "backups"
  })
}
