# =============================================================================
# SSH Keys
# =============================================================================

# Admin SSH keys (uploaded by users)
resource "hcloud_ssh_key" "admin" {
  for_each = var.ssh_public_keys

  name       = "admin-${each.key}"
  public_key = each.value

  labels = merge(var.common_labels, {
    type = "admin"
  })
}
