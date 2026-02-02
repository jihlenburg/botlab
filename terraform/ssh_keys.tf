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

# Generate SSH key pair for admin bot to access GitLab server
resource "tls_private_key" "admin_bot" {
  algorithm = "ED25519"
}

resource "hcloud_ssh_key" "admin_bot" {
  name       = "admin-bot-key"
  public_key = tls_private_key.admin_bot.public_key_openssh

  labels = merge(var.common_labels, {
    type = "service"
    component = "admin-bot"
  })
}

# Save admin bot private key locally (for provisioning)
resource "local_sensitive_file" "admin_bot_private_key" {
  content         = tls_private_key.admin_bot.private_key_openssh
  filename        = "${path.module}/generated/admin_bot_key"
  file_permission = "0600"
}

resource "local_file" "admin_bot_public_key" {
  content  = tls_private_key.admin_bot.public_key_openssh
  filename = "${path.module}/generated/admin_bot_key.pub"
}
