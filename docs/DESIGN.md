# ACME Corp GitLab Infrastructure - Master Design Document

**Version**: 1.3
**Last Updated**: 2026-02-02
**Status**: Draft - Pending Approval

---

## Related Documents

| Document | Purpose |
|----------|---------|
| [SECURITY-ASSESSMENT.md](SECURITY-ASSESSMENT.md) | Cybersecurity analysis, ransomware protection, DR edge cases |
| [INTEGRATOR-BOT-PLAN.md](INTEGRATOR-BOT-PLAN.md) | Claude Code CLI-based Integrator Bot architecture |

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Requirements](#2-requirements)
3. [Architecture Overview](#3-architecture-overview)
4. [Infrastructure Design](#4-infrastructure-design)
5. [GitLab Configuration](#5-gitlab-configuration)
6. [Disaster Recovery Design](#6-disaster-recovery-design)
7. [AI Bot Admin System](#7-ai-bot-admin-system)
   - 7.8 [Multi-Repository Policy System](#78-multi-repository-policy-system)
8. [Security Architecture](#8-security-architecture)
9. [Ransomware Protection](#9-ransomware-protection) *(NEW)*
10. [Monitoring & Alerting](#10-monitoring--alerting)
11. [Implementation Plan](#11-implementation-plan)
12. [Verification & Testing](#12-verification--testing)
13. [Operational Procedures](#13-operational-procedures)

---

## 1. Executive Summary

### 1.1 Purpose

This document defines the complete technical architecture for ACME Corp' GitLab infrastructure hosted on Hetzner Cloud. It serves as the **single source of truth** for all implementation decisions.

### 1.2 Scope

- GitLab CE instance for 10-20 developers
- Git LFS support for electronics design files
- SSO integration with Microsoft Azure AD
- Backup-based disaster recovery
- AI-powered admin bot for automated monitoring and maintenance

### 1.3 Constraints

| Constraint | Description |
|------------|-------------|
| **Open Source Only** | No commercial software licenses |
| **Data Protection** | Hourly backups, encrypted offsite storage |
| **Budget** | ~70 EUR/month infrastructure |
| **Scale** | 10-20 developers initially |

### 1.4 Key Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| GitLab Edition | CE (Community) | Open source requirement |
| Hosting | Hetzner Cloud | Cost-effective, EU data residency |
| DR Strategy | Backup-based cold recovery | Simple, robust, cost-effective |
| Server Size | CPX31 (4 vCPU, 16GB) | Right-sized for 10-20 developers |
| Admin Automation | Claude Code CLI + MCP | AI-powered, extensible, future-proof |
| Backup Strategy | 3-2-1 with immutable tier | Ransomware-resistant (see Section 9) |
| Backup Destinations | Borg (append-only) + S3 (Object Lock) | Defense in depth |
| Project Configuration | Per-repo `.gitlab-bot.yml` | Distributed policy, auditable, scalable |

**Evolution Note**: The Admin Bot architecture evolves from Python-based to Claude Code CLI-based "Integrator Bot" for improved extensibility and AI capabilities. See [INTEGRATOR-BOT-PLAN.md](INTEGRATOR-BOT-PLAN.md).

---

## 2. Requirements

### 2.1 Functional Requirements

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-01 | Host Git repositories for 10-20 developers | Must |
| FR-02 | Support Git LFS for large binary files (CAD, firmware) | Must |
| FR-03 | SSO via Microsoft Azure AD | Must |
| FR-04 | CI/CD pipeline execution | Must |
| FR-05 | Container registry | Should |
| FR-06 | Issue tracking and project management | Must |

### 2.2 Non-Functional Requirements

| ID | Requirement | Target |
|----|-------------|--------|
| NFR-01 | Availability | 99% uptime |
| NFR-02 | Recovery Point Objective (RPO) | ~1 hour |
| NFR-03 | Recovery Time Objective (RTO) | ~1-2 hours |
| NFR-04 | Response time | < 2s for web UI |
| NFR-05 | Backup retention | 30 days minimum |
| NFR-06 | Security | 2FA enforced, encrypted at rest |

### 2.3 Compliance Requirements

| Requirement | Description |
|-------------|-------------|
| Data Residency | All data stored in EU (Germany) |
| Access Control | Role-based, audit logged |
| Encryption | TLS 1.2+ in transit, encrypted backups |

---

## 3. Architecture Overview

### 3.1 System Context Diagram

```
                                    ┌─────────────────┐
                                    │   Developers    │
                                    │   (10-20)       │
                                    └────────┬────────┘
                                             │
                                    HTTPS/SSH (Git)
                                             │
┌────────────────────────────────────────────▼────────────────────────────────────────────┐
│                                    INTERNET                                              │
└────────────────────────────────────────────┬────────────────────────────────────────────┘
                                             │
                         ┌───────────────────┼───────────────────┐
                         │                   │                   │
                         ▼                   ▼                   ▼
                ┌─────────────┐     ┌─────────────┐     ┌─────────────┐
                │   Azure AD  │     │   Hetzner   │     │   Email     │
                │   (SSO)     │     │   Cloud     │     │   (SMTP)    │
                └─────────────┘     └──────┬──────┘     └─────────────┘
                                           │
                              ┌────────────┴────────────┐
                              │     ACME GitLab         │
                              │     Infrastructure      │
                              └─────────────────────────┘
```

### 3.2 High-Level Architecture

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                           HETZNER CLOUD                                       │
│  ┌─────────────────────────────────────────────────────────────────────────┐ │
│  │                    PRIVATE NETWORK (10.0.0.0/16)                         │ │
│  │                                                                          │ │
│  │         ┌─────────────┐                    ┌─────────────┐              │ │
│  │         │   GITLAB    │                    │  ADMIN BOT  │              │ │
│  │         │   PRIMARY   │◄───── monitors ────│   MACHINE   │              │ │
│  │         │   (CPX31)   │                    │   (CX32)    │              │ │
│  │         │             │                    │             │              │ │
│  │         │ Falkenstein │                    │ Falkenstein │              │ │
│  │         └──────┬──────┘                    └──────┬──────┘              │ │
│  │                │                                  │                      │ │
│  │                └──────────────┬───────────────────┘                      │ │
│  │                               │                                          │ │
│  └───────────────────────────────┼──────────────────────────────────────────┘ │
│                                  │                                            │
│  ┌───────────────────────────────┼───────────────────────────────────────┐   │
│  │                               │                                       │   │
│  │  ┌──────────────┐     ┌───────┴───────┐     ┌──────────────┐        │   │
│  │  │   OBJECT     │     │  STORAGE BOX  │     │   VOLUMES    │        │   │
│  │  │   STORAGE    │     │   (BACKUPS)   │     │  (300 GB)    │        │   │
│  │  │   (S3)       │     │    BX21       │     │              │        │   │
│  │  └──────────────┘     └───────────────┘     └──────────────┘        │   │
│  │                         STORAGE LAYER                                │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
│  ┌──────────────────┐                                                        │
│  │  LOAD BALANCER   │◄──── Public IP / DNS                                  │
│  │      (LB11)      │                                                        │
│  └──────────────────┘                                                        │
│                                                                              │
└──────────────────────────────────────────────────────────────────────────────┘
```

### 3.3 Component Summary

| Component | Purpose | Location |
|-----------|---------|----------|
| GitLab Primary | Main GitLab instance | Falkenstein |
| Admin Bot | Monitoring, maintenance, alerting | Falkenstein |
| Object Storage | LFS, artifacts, uploads | Falkenstein |
| Storage Box | Encrypted backups (offsite) | Falkenstein (different DC) |
| Load Balancer | TLS termination, health checks | Falkenstein |

**Note**: No hot standby secondary. Recovery via backup restoration to new server.

---

## 4. Infrastructure Design

### 4.1 Server Specifications

#### 4.1.1 GitLab Primary (Configurable)

| Attribute | Default Value | Terraform Variable |
|-----------|---------------|-------------------|
| **Type** | CPX31 (Shared vCPU) | `gitlab_server_type` |
| **vCPUs** | 4 shared | - |
| **RAM** | 16 GB | - |
| **Local Storage** | 160 GB NVMe | - |
| **Location** | Falkenstein (fsn1) | `location` |
| **OS** | Ubuntu 24.04 LTS | `server_image` |
| **Cost** | ~18 EUR/month | - |

**Rationale**: CPX31 provides adequate resources for 10-20 developers. GitLab recommends 4+ vCPU and 8+ GB RAM for this scale.

**Scaling Options**:
- Small team (5-10): `cx31` (2 vCPU, 8GB) ~8 EUR/month
- Medium team (10-20): `cpx31` (4 vCPU, 16GB) ~18 EUR/month (default)
- Large team (20-50): `cpx41` (8 vCPU, 32GB) ~35 EUR/month

#### 4.1.2 Admin Bot Machine (Configurable)

| Attribute | Default Value | Terraform Variable |
|-----------|---------------|-------------------|
| **Type** | CX32 (Shared vCPU) | `admin_bot_server_type` |
| **vCPUs** | 4 shared | - |
| **RAM** | 8 GB | - |
| **Local Storage** | 80 GB NVMe | - |
| **Location** | Falkenstein (fsn1) | `location` |
| **OS** | Ubuntu 24.04 LTS | `server_image` |
| **Cost** | ~7 EUR/month | - |

**Rationale**: Monitoring workload is lightweight. Co-located with primary for low-latency health checks.

**Note**: For minimal setups, `cx22` (2 vCPU, 4GB) at ~4 EUR/month is sufficient.

### 4.2 Network Architecture

#### 4.2.1 IP Addressing

```
Private Network: 10.0.0.0/16

Subnet: 10.0.1.0/24 (Production)
├── 10.0.1.10  GitLab Primary
└── 10.0.1.30  Admin Bot

Subnet: 10.0.2.0/24 (Future CI Runners)
└── Reserved for scaling
```

#### 4.2.2 Firewall Rules

**Public Firewall (gitlab-public-fw)**

| Direction | Protocol | Port | Source | Purpose |
|-----------|----------|------|--------|---------|
| Inbound | TCP | 443 | 0.0.0.0/0 | HTTPS |
| Inbound | TCP | 22 | 0.0.0.0/0 | SSH (Git) |
| Inbound | TCP | 80 | 0.0.0.0/0 | HTTP→HTTPS redirect |

**Internal Firewall (gitlab-internal-fw)**

| Direction | Protocol | Port | Source | Purpose |
|-----------|----------|------|--------|---------|
| Inbound | TCP | 9090 | 10.0.1.30 | Prometheus metrics |
| Inbound | TCP | 22 | 10.0.1.30 | Admin SSH |
| Inbound | ALL | ALL | 10.0.1.0/24 | Internal services |

**Admin Bot Firewall (admin-fw)**

| Direction | Protocol | Port | Source | Purpose |
|-----------|----------|------|--------|---------|
| Inbound | TCP | 22 | Trusted IPs | SSH access |
| Outbound | TCP | 443 | 0.0.0.0/0 | APIs, alerts |
| Outbound | TCP | 22 | 10.0.1.0/24 | GitLab SSH |

### 4.3 Storage Architecture

#### 4.3.1 Block Storage Volumes

| Volume | Size | Mount Point | Purpose |
|--------|------|-------------|---------|
| gitlab-data | 200 GB | /var/opt/gitlab | Repos, PostgreSQL |
| gitlab-backups | 100 GB | /var/opt/gitlab/backups | Backup staging |

**Features**:
- Triple replication
- SSD performance
- Expandable to 10 TB

#### 4.3.2 Object Storage Buckets

| Bucket | Purpose |
|--------|---------|
| gitlab-acme-lfs | Git LFS objects |
| gitlab-acme-artifacts | CI/CD artifacts |
| gitlab-acme-uploads | Attachments, avatars |
| gitlab-acme-registry | Container images |
| gitlab-acme-packages | Package registry |

**Configuration**:
- S3-compatible API
- Versioning enabled for data protection

#### 4.3.3 Backup Storage (Storage Box BX21)

| Attribute | Value |
|-----------|-------|
| **Capacity** | 5 TB |
| **Protocol** | SSH/rsync, SFTP |
| **Location** | Falkenstein (different datacenter) |
| **Encryption** | Client-side (BorgBackup) |
| **Cost** | ~16 EUR/month |

### 4.4 DNS Configuration

| Record | Type | Value | TTL | Purpose |
|--------|------|-------|-----|---------|
| gitlab.example.com | A | Load Balancer IP | 300 | Main access |
| registry.gitlab.example.com | CNAME | gitlab.example.com | 3600 | Container registry |

**Note**: Low TTL (300s) enables DNS updates within 5 minutes during recovery.

### 4.5 Load Balancer Configuration

| Attribute | Value |
|-----------|-------|
| **Type** | LB11 |
| **Algorithm** | Round Robin |
| **Health Check** | HTTP GET /-/health |
| **TLS Termination** | Yes (Let's Encrypt) |
| **Backends** | GitLab Primary |

### 4.6 Cost Summary

| Resource | Specification | EUR/month |
|----------|---------------|-----------|
| GitLab Primary | CPX31 (4 vCPU, 16GB) | ~18 |
| Admin Bot | CX32 (4 vCPU, 8GB) | ~7 |
| Block Storage | 300 GB | ~13 |
| Object Storage | ~2 TB | ~10 |
| Storage Box | BX21 (5 TB) | ~16 |
| Load Balancer | LB11 | ~6 |
| **Total** | | **~70** |

---

## 5. GitLab Configuration

### 5.1 Installation

**Method**: Omnibus package (gitlab-ce)
**Version**: Latest stable
**OS**: Ubuntu 24.04 LTS

```bash
curl https://packages.gitlab.com/install/repositories/gitlab/gitlab-ce/script.deb.sh | sudo bash
sudo EXTERNAL_URL="https://gitlab.example.com" apt-get install gitlab-ce
```

### 5.2 Core Configuration

**File**: `/etc/gitlab/gitlab.rb`

#### 5.2.1 External URL and SSL

```ruby
external_url 'https://gitlab.example.com'

letsencrypt['enable'] = true
letsencrypt['contact_emails'] = ['admin@example.com']
letsencrypt['auto_renew'] = true
letsencrypt['auto_renew_hour'] = 3

nginx['ssl_protocols'] = "TLSv1.2 TLSv1.3"
nginx['hsts_max_age'] = 31536000
```

#### 5.2.2 Object Storage (Consolidated)

```ruby
gitlab_rails['object_store']['enabled'] = true
gitlab_rails['object_store']['connection'] = {
  'provider' => 'AWS',
  'endpoint' => 'https://fsn1.your-objectstorage.com',
  'aws_access_key_id' => '<ACCESS_KEY>',
  'aws_secret_access_key' => '<SECRET_KEY>',
  'region' => 'fsn1',
  'path_style' => true
}
gitlab_rails['object_store']['objects']['artifacts']['bucket'] = 'gitlab-acme-artifacts'
gitlab_rails['object_store']['objects']['lfs']['bucket'] = 'gitlab-acme-lfs'
gitlab_rails['object_store']['objects']['uploads']['bucket'] = 'gitlab-acme-uploads'
gitlab_rails['object_store']['objects']['packages']['bucket'] = 'gitlab-acme-packages'
```

#### 5.2.3 Git LFS

```ruby
gitlab_rails['lfs_enabled'] = true
# LFS uses object storage defined above
```

#### 5.2.4 SMTP (Microsoft 365)

```ruby
gitlab_rails['smtp_enable'] = true
gitlab_rails['smtp_address'] = "smtp.office365.com"
gitlab_rails['smtp_port'] = 587
gitlab_rails['smtp_user_name'] = "gitlab-noreply@example.com"
gitlab_rails['smtp_password'] = "<SMTP_PASSWORD>"
gitlab_rails['smtp_domain'] = "example.com"
gitlab_rails['smtp_authentication'] = "login"
gitlab_rails['smtp_enable_starttls_auto'] = true

gitlab_rails['gitlab_email_from'] = 'gitlab-noreply@example.com'
gitlab_rails['gitlab_email_display_name'] = 'GitLab ACME Corp'
```

#### 5.2.5 Security Hardening

```ruby
gitlab_rails['gitlab_signup_enabled'] = false
gitlab_rails['require_two_factor_authentication'] = true
gitlab_rails['two_factor_grace_period_in_hours'] = 168
gitlab_rails['session_timeout'] = 28800
gitlab_rails['minimum_password_length'] = 12
gitlab_rails['gitlab_default_projects_features_visibility_level'] = 'private'
gitlab_rails['gitlab_default_can_create_group'] = false
gitlab_rails['gravatar_enabled'] = false

gitlab_rails['rack_attack_git_basic_auth'] = {
  'enabled' => true,
  'ip_whitelist' => ["127.0.0.1", "10.0.0.0/8"],
  'maxretry' => 10,
  'findtime' => 60,
  'bantime' => 3600
}
```

#### 5.2.6 Backup Configuration

```ruby
gitlab_rails['backup_keep_time'] = 86400  # 1 day local retention
gitlab_rails['backup_path'] = "/var/opt/gitlab/backups"
```

### 5.3 Azure AD SSO (SAML 2.0)

#### 5.3.1 Azure AD Configuration

1. Create Enterprise Application "GitLab ACME Corp"
2. Configure SAML:
   - **Identifier (Entity ID)**: `https://gitlab.example.com`
   - **Reply URL**: `https://gitlab.example.com/users/auth/saml/callback`
   - **Sign-on URL**: `https://gitlab.example.com/users/sign_in`

3. User Attributes:
   | Claim | Source Attribute |
   |-------|------------------|
   | email | user.mail |
   | name | user.displayname |
   | first_name | user.givenname |
   | last_name | user.surname |

#### 5.3.2 GitLab SAML Configuration

```ruby
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
      idp_cert: "-----BEGIN CERTIFICATE-----\n<AZURE_AD_CERT>\n-----END CERTIFICATE-----",
      idp_sso_target_url: "https://login.microsoftonline.com/<TENANT_ID>/saml2",
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
```

**Note**: GitLab CE supports SAML SSO. Users are auto-created on first login. Group assignment is manual (automatic group sync requires EE).

### 5.4 Git LFS Configuration

#### 5.4.1 Company .gitattributes Template

```gitattributes
# ACME Corp Standard LFS Rules
# Include this in all repositories

# Electronics CAD Files
*.brd filter=lfs diff=lfs merge=lfs -text
*.sch filter=lfs diff=lfs merge=lfs -text
*.kicad_pcb filter=lfs diff=lfs merge=lfs -text
*.kicad_sch filter=lfs diff=lfs merge=lfs -text
*.PcbDoc filter=lfs diff=lfs merge=lfs -text
*.SchDoc filter=lfs diff=lfs merge=lfs -text
*.dsn filter=lfs diff=lfs merge=lfs -text

# 3D Models
*.step filter=lfs diff=lfs merge=lfs -text
*.stp filter=lfs diff=lfs merge=lfs -text
*.stl filter=lfs diff=lfs merge=lfs -text
*.3ds filter=lfs diff=lfs merge=lfs -text

# Firmware/Binaries
*.hex filter=lfs diff=lfs merge=lfs -text
*.bin filter=lfs diff=lfs merge=lfs -text
*.elf filter=lfs diff=lfs merge=lfs -text
*.axf filter=lfs diff=lfs merge=lfs -text

# Archives
*.zip filter=lfs diff=lfs merge=lfs -text
*.tar.gz filter=lfs diff=lfs merge=lfs -text
*.7z filter=lfs diff=lfs merge=lfs -text

# Images and Documents
*.pdf filter=lfs diff=lfs merge=lfs -text
*.png filter=lfs diff=lfs merge=lfs -text
*.jpg filter=lfs diff=lfs merge=lfs -text
*.jpeg filter=lfs diff=lfs merge=lfs -text
```

---

## 6. Disaster Recovery Design

### 6.1 Design Philosophy

**Strategy**: Backup-based cold recovery

Instead of maintaining a hot standby (expensive, complex), we rely on:
1. Frequent backups (hourly)
2. Fast provisioning (Hetzner API/Terraform)
3. Automated restore procedures

**Trade-off**: Accept ~1-2 hour RTO in exchange for simpler architecture and lower cost.

### 6.2 Recovery Objectives

| Metric | Target | How Achieved |
|--------|--------|--------------|
| **RPO** | ~1 hour | Hourly backups to Storage Box |
| **RTO** | ~1-2 hours | Terraform + automated restore |

### 6.3 Backup Strategy

#### 6.3.1 Backup Components

| Component | What's Backed Up |
|-----------|------------------|
| GitLab Backup | Database, repositories, uploads, LFS pointers |
| Object Storage | LFS objects, artifacts (separate sync) |
| Config Files | /etc/gitlab/gitlab.rb, gitlab-secrets.json |

#### 6.3.2 Backup Schedule

| Backup Type | Frequency | Retention | Destination |
|-------------|-----------|-----------|-------------|
| GitLab backup | Hourly | 24 hours local | /var/opt/gitlab/backups |
| BorgBackup sync | Hourly | 30 days | Storage Box (append-only) |
| **Immutable backup** | Weekly | 90 days | S3 with Object Lock |
| Config backup | On change + daily | 90 days | Storage Box |
| Volume snapshots | Every 6 hours | 7 days | Hetzner |
| **Offline backup** | Quarterly | 1 year | Physical offline storage |

#### 6.3.3 Multi-Destination Backup Strategy (3-2-1 Rule)

**Rationale**: Per [SECURITY-ASSESSMENT.md](SECURITY-ASSESSMENT.md), single-destination backups are vulnerable to ransomware attacks that could delete all backups. The 3-2-1 strategy ensures recovery is always possible.

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         3-2-1 Backup Strategy                            │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│   3 COPIES                 2 MEDIA TYPES              1 OFFSITE         │
│   ────────                 ──────────────             ────────          │
│   1. Local (GitLab)        1. SSD (local)             S3 immutable      │
│   2. Borg (Storage Box)    2. HDD (Storage Box)       (different        │
│   3. S3 (Object Lock)         + S3 Cloud              provider)         │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

| Destination | Type | Access Mode | Ransomware Protection |
|-------------|------|-------------|----------------------|
| Local | SSD | Read/Write | None (staging only) |
| Borg Primary | HDD | **Append-only** | Cannot delete archives |
| S3 Immutable | Cloud | **Object Lock (WORM)** | Cannot modify for 90 days |
| Offline | USB/Tape | Air-gapped | Physical isolation |

**Append-Only Borg Configuration**:
```bash
# Storage Box sub-account: backup-write (can create, cannot delete)
# Separate backup-admin account with delete permission stored OFFLINE only
export BORG_REPO="ssh://uXXXXX-sub1@uXXXXX.your-storagebox.de:23/./gitlab-borg"
```

**S3 Object Lock Configuration** (Backblaze B2 or AWS S3):
```bash
# Weekly backup to immutable storage
aws s3 cp gitlab-backup.tar s3://acme-gitlab-immutable/ \
    --object-lock-mode GOVERNANCE \
    --object-lock-retain-until-date $(date -d "+90 days" --iso-8601)
```

#### 6.3.4 BorgBackup Configuration

**Initialize repository (with append-only sub-account):**
```bash
# Main repository initialization (one-time, with full-access credentials)
borg init --encryption=repokey-blake2 ssh://uXXXXX@uXXXXX.your-storagebox.de:23/./gitlab-borg

# Create Storage Box sub-account via Hetzner Robot:
# - Name: backup-write
# - Permissions: Read, Write (NO Delete)
# Use this restricted account for automated backups
```

**Backup script** (`/usr/local/bin/gitlab-backup-to-borg.sh`):
```bash
#!/bin/bash
set -e

BORG_REPO="ssh://uXXXXX@uXXXXX.your-storagebox.de:23/./gitlab-borg"
export BORG_PASSPHRASE="<encryption-passphrase>"

# Create GitLab backup first
gitlab-backup create STRATEGY=copy SKIP=artifacts,lfs

# Find latest backup
LATEST_BACKUP=$(ls -t /var/opt/gitlab/backups/*_gitlab_backup.tar | head -1)

# Send to BorgBackup
borg create --stats --compression zstd \
    "${BORG_REPO}::{hostname}-{now}" \
    "$LATEST_BACKUP" \
    /etc/gitlab/gitlab.rb \
    /etc/gitlab/gitlab-secrets.json

# Prune old backups
borg prune --keep-hourly=24 --keep-daily=7 --keep-weekly=4 --keep-monthly=6 \
    "$BORG_REPO"

# Clean local backups older than 24h
find /var/opt/gitlab/backups -name "*_gitlab_backup.tar" -mtime +1 -delete
```

**Cron schedule** (`/etc/cron.d/gitlab-backup`):
```
0 * * * * root /usr/local/bin/gitlab-backup-to-borg.sh >> /var/log/gitlab-backup.log 2>&1
```

### 6.4 Recovery Procedure

#### 6.4.1 Recovery Timeline

| Step | Duration | Description |
|------|----------|-------------|
| 1 | 2-5 min | Provision new CPX31 via Terraform |
| 2 | 10-15 min | Install GitLab CE |
| 3 | 5 min | Restore config files from Borg |
| 4 | 30-60 min | Restore GitLab backup |
| 5 | 5 min | Reconfigure and verify |
| 6 | 5 min | Update DNS |
| **Total** | **~1-2 hours** | |

#### 6.4.2 Detailed Recovery Steps

**Step 1: Provision new server**
```bash
cd terraform
terraform apply -target=hcloud_server.gitlab_primary
```

**Step 2: Install GitLab CE**
```bash
ssh root@<new-server>
curl https://packages.gitlab.com/install/repositories/gitlab/gitlab-ce/script.deb.sh | bash
apt-get install gitlab-ce
```

**Step 3: Restore configuration**
```bash
# On admin bot or recovery workstation
export BORG_REPO="ssh://uXXXXX@uXXXXX.your-storagebox.de:23/./gitlab-borg"
borg extract "${BORG_REPO}::latest" etc/gitlab

scp etc/gitlab/gitlab.rb root@<new-server>:/etc/gitlab/
scp etc/gitlab/gitlab-secrets.json root@<new-server>:/etc/gitlab/
```

**Step 4: Restore GitLab backup**
```bash
# Extract backup from Borg
borg extract "${BORG_REPO}::latest" var/opt/gitlab/backups

# Copy to new server
scp var/opt/gitlab/backups/*_gitlab_backup.tar root@<new-server>:/var/opt/gitlab/backups/

# On new server
gitlab-ctl stop puma
gitlab-ctl stop sidekiq
gitlab-backup restore BACKUP=<timestamp>
```

**Step 5: Reconfigure and verify**
```bash
gitlab-ctl reconfigure
gitlab-ctl restart
gitlab-rake gitlab:check SANITIZE=true
```

**Step 6: Update DNS**
```bash
# Update gitlab.example.com to new server IP
# Or update Load Balancer backend
```

#### 6.4.3 Automated Recovery Script

The Admin Bot includes a semi-automated recovery script that:
1. Provisions new server via Hetzner API
2. Installs GitLab
3. Restores from latest backup
4. Runs verification checks
5. Prompts operator to update DNS

See `gitlab-admin-bot/src/restore/recovery.py`

### 6.5 Backup Verification

**Weekly automated test:**
1. Provision ephemeral CX21 server
2. Install GitLab CE
3. Restore latest backup
4. Verify:
   - Web UI accessible
   - Admin login works
   - Sample repo cloneable
5. Generate report
6. Destroy test server

---

## 7. AI Bot Admin System

### 7.1 Purpose

Automated monitoring, maintenance, backup management, and recovery assistance for the GitLab infrastructure.

### 7.2 Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                      ADMIN BOT MACHINE (CX32)                   │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │                    ADMIN BOT SERVICE                     │   │
│  │                                                          │   │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌─────────┐ │   │
│  │  │ Scheduler│  │ Monitors │  │  Maint.  │  │ Alerter │ │   │
│  │  │(APSched) │  │          │  │  Tasks   │  │         │ │   │
│  │  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬────┘ │   │
│  │       │             │             │             │       │   │
│  │       └─────────────┴──────┬──────┴─────────────┘       │   │
│  │                            │                             │   │
│  │                     ┌──────▼──────┐                     │   │
│  │                     │   Core API  │                     │   │
│  │                     │  (FastAPI)  │                     │   │
│  │                     └──────┬──────┘                     │   │
│  │                            │                             │   │
│  └────────────────────────────┼─────────────────────────────┘   │
│                               │                                 │
│  ┌────────────────────────────┼─────────────────────────────┐   │
│  │                            │                             │   │
│  │  ┌──────────┐  ┌───────────▼───────────┐  ┌──────────┐ │   │
│  │  │  SQLite  │  │    GitLab API Client  │  │   SSH    │ │   │
│  │  │  (State) │  │    (python-gitlab)    │  │  Client  │ │   │
│  │  └──────────┘  └───────────────────────┘  └──────────┘ │   │
│  │                                                         │   │
│  │                     INTEGRATIONS                        │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
          │                    │                    │
          ▼                    ▼                    ▼
    ┌──────────┐         ┌──────────┐        ┌──────────┐
    │  GitLab  │         │  Hetzner │        │ Alerting │
    │  Server  │         │   API    │        │ Channels │
    └──────────┘         └──────────┘        └──────────┘
```

### 7.3 Project Structure

```
gitlab-admin-bot/
├── pyproject.toml
├── Dockerfile
├── docker-compose.yml
├── config/
│   ├── config.yaml
│   └── alerts.yaml
├── src/
│   ├── __init__.py
│   ├── main.py                 # Entry point
│   ├── config.py               # Configuration management
│   ├── scheduler.py            # APScheduler setup
│   ├── monitors/
│   │   ├── __init__.py
│   │   ├── base.py             # Base monitor class
│   │   ├── health.py           # GitLab health endpoints
│   │   ├── resources.py        # Disk, CPU, memory
│   │   ├── backup.py           # Backup age and status
│   │   └── services.py         # GitLab services status
│   ├── maintenance/
│   │   ├── __init__.py
│   │   ├── backup.py           # Trigger backups
│   │   ├── cleanup.py          # Artifact/LFS cleanup
│   │   └── registry.py         # Container registry GC
│   ├── alerting/
│   │   ├── __init__.py
│   │   ├── manager.py          # Alert routing, deduplication
│   │   ├── email.py            # Email notifications
│   │   └── webhook.py          # Slack/Mattermost webhooks
│   ├── restore/
│   │   ├── __init__.py
│   │   ├── tester.py           # Automated restore testing
│   │   ├── recovery.py         # DR recovery automation
│   │   └── hetzner.py          # VM provisioning
│   └── utils/
│       ├── __init__.py
│       ├── gitlab_api.py       # python-gitlab wrapper
│       ├── ssh.py              # SSH command execution
│       └── metrics.py          # Prometheus metrics export
├── tests/
│   └── ...
└── scripts/
    ├── install.sh
    └── gitlab-admin-wrapper.sh
```

### 7.4 Monitoring Capabilities

| Monitor | Check | Warning | Critical | Interval |
|---------|-------|---------|----------|----------|
| Disk Space | df -h | 80% | 90% | 5 min |
| CPU Usage | /proc/stat | 70% (15m) | 90% (5m) | 1 min |
| Memory | /proc/meminfo | 80% | 95% | 1 min |
| GitLab Health | /-/health | - | Fail | 30 sec |
| GitLab Readiness | /-/readiness | - | Fail | 1 min |
| Backup Age | File mtime | 2h | 4h | 15 min |
| SSL Expiry | Certificate check | 30 days | 7 days | Daily |

### 7.5 Automated Maintenance

#### Hourly Tasks
- Trigger GitLab backup
- Check backup completion
- Alert if backup fails

#### Daily Tasks (03:00 UTC)
- Sync backups to Storage Box (BorgBackup)
- Rotate logs
- Clean orphaned artifacts
- Generate daily report

#### Weekly Tasks (Sunday 03:00 UTC)
- Container registry garbage collection
- Database vacuum analyze
- Backup restore test (ephemeral VM)
- Generate weekly report

#### Monthly Tasks (1st, 09:00 UTC)
- Security updates check
- SSL certificate expiry check
- Storage growth analysis

### 7.6 Backup Verification

**Weekly automated restore test:**
1. Provision ephemeral Hetzner VM (CX21, ~3 EUR for a few hours)
2. Install GitLab CE (same version as production)
3. Copy latest backup from Storage Box
4. Execute restore
5. Verify:
   - Web UI accessible (HTTP 200 on /-/health)
   - Admin login works (API authentication)
   - Sample project cloneable (git clone test)
   - Database integrity (gitlab:check rake task)
6. Generate report (success/failure, duration, issues)
7. Destroy ephemeral VM
8. Email report to admins

### 7.7 Alerting Configuration

**Severity Levels:**
| Level | Response | Channels |
|-------|----------|----------|
| Critical | Immediate | Email + Webhook |
| Warning | 4 hours | Email |
| Info | Next business day | Email digest |

**Deduplication**: Same alert not repeated within 1 hour cooldown.

### 7.8 Multi-Repository Policy System

> **Full Specification**: See [INTEGRATOR-BOT-PLAN.md](INTEGRATOR-BOT-PLAN.md) Section 7 for complete policy architecture.

The Integrator Bot supports **per-project policy files** that enable distributed, project-aware automation.

#### 7.8.1 Policy File: `.gitlab-bot.yml`

Each GitLab repository can contain a `.gitlab-bot.yml` file that defines project-specific rules:

```yaml
# .gitlab-bot.yml - Per-project bot configuration
version: 1

# Project ownership for alerts
owners:
  primary: alice@example.com
  backup: team-firmware@example.com

# What to monitor
monitors:
  stale_branches:
    enabled: true
    max_age_days: 30
    exclude: [main, develop, release/*]

  dependency_vulnerabilities:
    enabled: true
    severity_threshold: high

  ci_failures:
    alert_after_consecutive: 3

# What the bot can do automatically
automations:
  cleanup_merged_branches: true
  artifact_retention_days: 30
  auto_merge: false  # Dangerous - disabled by default

# Compliance requirements
compliance:
  require_code_review: true
  min_approvers: 1
  required_ci_checks: [lint, test, security-scan]

# Context documents for AI understanding
context:
  architecture: docs/ARCHITECTURE.md
  bot_instructions: BOT-RESPONSIBILITIES.md
```

#### 7.8.2 Natural Language Context

Projects can include a `BOT-RESPONSIBILITIES.md` file with natural language instructions:

```markdown
# Bot Responsibilities for firmware-sensor-v2

## Context
Safety-critical automotive firmware (ISO 26262 / ASIL-B).

## Rules
- NEVER auto-merge any MR
- Alert IMMEDIATELY on security vulnerabilities
- Flag any changes to interrupt handlers
- Monitor binary size (max 256KB)
```

The AI-powered bot reads these documents to make context-aware decisions.

#### 7.8.3 Default Policy

Projects without `.gitlab-bot.yml` receive conservative defaults:
- All automations disabled
- Basic monitoring only (health, critical vulnerabilities)
- Alerts sent to GitLab admin

#### 7.8.4 Security Benefits

| Benefit | Description |
|---------|-------------|
| **Distributed Control** | No single config file to compromise |
| **Version-Controlled** | Policy changes go through merge requests |
| **Auditable** | Full Git history of policy changes |
| **Least Privilege** | Bot actions scoped per-project |
| **Delegated Ownership** | Project teams manage their own rules |

---

## 8. Security Architecture

### 8.1 Authentication

| Component | Method |
|-----------|--------|
| GitLab Web | Azure AD SAML SSO + 2FA |
| GitLab SSH | SSH keys (Ed25519 preferred) |
| Admin Bot | API tokens + SSH keys |
| Server SSH | SSH keys only, no password |

### 8.2 Authorization

| Role | Capabilities |
|------|--------------|
| Admin | Full GitLab admin, server SSH |
| Developer | Project access per group |
| Bot | API read + specific write, restricted SSH commands |

### 8.3 Encryption

| Layer | Method |
|-------|--------|
| Transit | TLS 1.2+ everywhere |
| At Rest (backups) | BorgBackup repokey-blake2 |
| At Rest (volumes) | Hetzner default encryption |
| Secrets | Environment variables (future: Vault) |

### 8.4 Network Security

- All inter-server communication over private network
- Public access only through Load Balancer
- Firewall default deny
- Rate limiting on authentication endpoints

### 8.5 Admin Bot Security

**Principle of Least Privilege:**

```bash
# SSH restricted commands via authorized_keys
command="/usr/local/bin/gitlab-admin-wrapper.sh",no-port-forwarding,no-X11-forwarding ssh-ed25519 AAAA... admin-bot
```

**Wrapper script allows only:**
- `gitlab-ctl status`
- `gitlab-backup create`
- `gitlab-rake gitlab:check`
- Health check endpoints

---

## 9. Ransomware Protection

> **Full Analysis**: See [SECURITY-ASSESSMENT.md](SECURITY-ASSESSMENT.md) for complete threat model and recommendations.

### 9.1 Threat Summary

| Threat | Likelihood | Impact | Mitigation Status |
|--------|------------|--------|-------------------|
| Ransomware encrypts GitLab server | Medium | Critical | ✅ Multi-destination backup |
| Attacker deletes Borg backups | Medium | Critical | ✅ Append-only mode |
| Delayed activation (wait for retention) | Low | Critical | ✅ Extended retention + immutable |
| Backup passphrase theft | Low | Critical | ⚠️ Separate credentials |
| Storage Box failure | Very Low | Critical | ✅ S3 secondary destination |

### 9.2 Defense Layers

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    Ransomware Defense Layers                             │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│   Layer 1: PREVENTION                                                    │
│   ├── 2FA enforced on all accounts                                      │
│   ├── SSO via Azure AD (centralized access control)                     │
│   ├── SSH key-only authentication                                       │
│   ├── Fail2ban on authentication endpoints                              │
│   └── Rate limiting (rack_attack)                                        │
│                                                                          │
│   Layer 2: DETECTION                                                     │
│   ├── AI-powered anomaly detection (Integrator Bot)                     │
│   ├── File change monitoring                                            │
│   ├── Auth log analysis                                                 │
│   ├── Ransomware indicator scanning                                     │
│   └── Backup integrity verification                                      │
│                                                                          │
│   Layer 3: RECOVERY                                                      │
│   ├── Borg backups (append-only, cannot delete)                         │
│   ├── S3 immutable backups (Object Lock WORM)                           │
│   ├── Offline quarterly backups                                         │
│   └── Automated DR orchestration                                         │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

### 9.3 Backup Immutability

| Destination | Delete Protection | Modification Protection | Retention |
|-------------|-------------------|------------------------|-----------|
| Borg Primary | Append-only (sub-account) | Encryption (repokey) | 30 days |
| S3 Immutable | Object Lock Governance | Object Lock WORM | 90 days |
| Offline | Physical separation | Air-gapped | 1 year |

**Critical**: Full-access Borg credentials (for prune/delete) stored OFFLINE only.

### 9.4 Ransomware Detection (via Integrator Bot)

The Integrator Bot continuously monitors for ransomware indicators:

| Indicator | Detection Method | Response |
|-----------|-----------------|----------|
| Mass file changes | File count delta > threshold | Alert + investigate |
| Encrypted extensions | `.encrypted`, `.locked`, `.crypted` | Critical alert |
| Ransom notes | Pattern match in filenames | Critical alert |
| Suspicious processes | Unknown binaries, high CPU | Alert + recommend isolation |
| Backup tampering | Integrity check failure | Critical alert + verify immutable |

### 9.5 Incident Response Procedure

If ransomware is detected:

1. **DO NOT** shut down (preserve forensic evidence)
2. **VERIFY** immutable backup integrity immediately
3. **ISOLATE** network (requires human approval)
4. **ASSESS** damage scope via Integrator Bot
5. **RECOVER** from immutable backup (S3 Object Lock)
6. **INVESTIGATE** root cause
7. **DOCUMENT** incident

See [SECURITY-ASSESSMENT.md](SECURITY-ASSESSMENT.md) for detailed procedures.

---

## 10. Monitoring & Alerting

### 10.1 Metrics Stack

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   GitLab    │────►│ Prometheus  │────►│   Grafana   │
│  Exporters  │     │   (TSDB)    │     │ (Dashboards)│
└─────────────┘     └─────────────┘     └─────────────┘
                           │
                    ┌──────▼──────┐
                    │ Alertmanager│
                    └──────┬──────┘
                           │
              ┌────────────┼────────────┐
              ▼            ▼            ▼
         ┌────────┐  ┌──────────┐  ┌─────────┐
         │ Email  │  │ Webhook  │  │   Log   │
         └────────┘  └──────────┘  └─────────┘
```

### 10.2 Key Dashboards

1. **GitLab Overview**: Users, projects, CI pipelines, response times
2. **Infrastructure**: CPU, memory, disk, network
3. **Backup Status**: Last backup time, size trends, verification results

### 10.3 Alert Rules

```yaml
# Example Prometheus alert rules
groups:
  - name: gitlab
    rules:
      - alert: GitLabDown
        expr: probe_success{job="gitlab-health"} == 0
        for: 2m
        labels:
          severity: critical

      - alert: DiskSpaceLow
        expr: node_filesystem_avail_bytes{mountpoint="/var/opt/gitlab"} / node_filesystem_size_bytes < 0.1
        for: 5m
        labels:
          severity: critical

      - alert: BackupOverdue
        expr: time() - gitlab_backup_last_success_timestamp > 14400
        for: 5m
        labels:
          severity: critical
```

---

## 11. Implementation Plan

### Phase 1: Infrastructure (Week 1)

| Task | Description |
|------|-------------|
| 1.1 | Create Hetzner Cloud project |
| 1.2 | Write Terraform configuration |
| 1.3 | Provision GitLab server and network |
| 1.4 | Set up DNS records |
| 1.5 | Configure firewalls |
| 1.6 | Attach storage volumes |

**Deliverables**: Running infrastructure, SSH access to server

### Phase 2: GitLab Primary (Week 2)

| Task | Description |
|------|-------------|
| 2.1 | Install GitLab CE |
| 2.2 | Configure SSL (Let's Encrypt) |
| 2.3 | Configure object storage |
| 2.4 | Set up Azure AD SSO |
| 2.5 | Configure SMTP |
| 2.6 | Security hardening |

**Deliverables**: Working GitLab with SSO login

### Phase 3: Backup System (Week 3)

| Task | Description |
|------|-------------|
| 3.1 | Set up Storage Box |
| 3.2 | Configure BorgBackup |
| 3.3 | Create backup scripts |
| 3.4 | Set up cron jobs (hourly backup) |
| 3.5 | Test backup and restore |

**Deliverables**: Automated hourly backups, verified restore procedure

### Phase 4: Admin Bot (Weeks 4-6)

| Task | Description |
|------|-------------|
| 4.1 | Set up Python project structure |
| 4.2 | Implement health monitors |
| 4.3 | Implement resource monitors |
| 4.4 | Implement backup monitoring |
| 4.5 | Implement alerting |
| 4.6 | Implement backup verification |
| 4.7 | Deploy as systemd service |

**Deliverables**: Running admin bot with monitoring and alerts

### Phase 5: Testing & Documentation (Week 7)

| Task | Description |
|------|-------------|
| 5.1 | Full system testing |
| 5.2 | DR recovery drill |
| 5.3 | Security review |
| 5.4 | Write operations documentation |
| 5.5 | User onboarding guide |

**Deliverables**: Complete documentation, successful DR drill

---

## 12. Verification & Testing

### 12.1 Test Cases

| ID | Test | Expected Result |
|----|------|-----------------|
| T01 | Access GitLab web UI | HTTPS works, valid certificate |
| T02 | Login via Azure AD SSO | User created, redirected to dashboard |
| T03 | Create project and push code | Repository created successfully |
| T04 | Push large file via LFS | File stored in object storage |
| T05 | Run CI/CD pipeline | Pipeline executes, artifacts stored |
| T06 | Verify backup exists | Backup file in Storage Box |
| T07 | Restore from backup | GitLab functional after restore |
| T08 | Admin bot alert | Email received within 5 minutes |

### 12.2 DR Drill Procedure

1. Schedule maintenance window
2. Notify stakeholders
3. Simulate primary failure (shutdown)
4. Execute recovery procedure (provision + restore)
5. Verify all services
6. Test user access and git operations
7. Document results and lessons learned

---

## 13. Operational Procedures

### 13.1 Daily Checks (Automated by Admin Bot)

- [ ] Health check passing
- [ ] Backup completed in last hour
- [ ] Disk usage < 80%
- [ ] No critical alerts

### 13.2 Weekly Tasks

- [ ] Review weekly report from admin bot
- [ ] Check storage usage trends
- [ ] Verify restore test passed
- [ ] Review security advisories

### 13.3 Monthly Tasks

- [ ] Apply security updates
- [ ] Review access permissions
- [ ] Capacity planning review

### 13.4 Incident Response

1. **Detect**: Alert received or user report
2. **Triage**: Assess severity and impact
3. **Communicate**: Notify stakeholders
4. **Resolve**: Follow runbook or escalate
5. **Document**: Post-incident report

---

## Appendix A: Configuration Files Reference

| File | Location | Purpose |
|------|----------|---------|
| gitlab.rb | /etc/gitlab/gitlab.rb | Main GitLab config |
| gitlab-secrets.json | /etc/gitlab/gitlab-secrets.json | Encryption keys (CRITICAL) |
| config.yaml | /opt/admin-bot/config/ | Admin bot config |

## Appendix B: Useful Commands

```bash
# GitLab status
sudo gitlab-ctl status

# GitLab logs
sudo gitlab-ctl tail

# Reconfigure GitLab
sudo gitlab-ctl reconfigure

# Create backup manually
sudo gitlab-backup create STRATEGY=copy

# List Borg backups
borg list ssh://uXXXXX@uXXXXX.your-storagebox.de:23/./gitlab-borg

# Admin bot logs
journalctl -u gitlab-admin-bot -f
```

## Appendix C: Contact Information

| Role | Contact |
|------|---------|
| GitLab Admin | admin@example.com |
| On-Call | oncall@example.com |
| Hetzner Support | support@hetzner.com |

---

**Document Control**

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2026-02-02 | Claude Code | Initial draft |
| 1.1 | 2026-02-02 | Claude Code | Simplified to CPX31, backup-based DR |
| 1.2 | 2026-02-02 | Claude Code | Added ransomware protection (Section 9), 3-2-1 backup strategy, security assessment integration |
| 1.3 | 2026-02-02 | Claude Code | Added multi-repository policy system (Section 7.8), per-project .gitlab-bot.yml |
