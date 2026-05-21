# ACME Corp GitLab Infrastructure - Master Design Document

**Version**: 2.8
**Last Updated**: 2026-05-21
**Status**: Draft - Pending Approval

---

## Related Documents

| Document | Purpose |
|----------|---------|
| [SECURITY-ASSESSMENT.md](SECURITY-ASSESSMENT.md) | Cybersecurity analysis, ransomware protection, DR edge cases |
| [DEPLOY.md](DEPLOY.md) | First-deploy checklist for operators |
| [RUNBOOK-RECOVERY.md](RUNBOOK-RECOVERY.md) | Operator-facing disaster recovery runbook |

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Requirements](#2-requirements)
3. [Architecture Overview](#3-architecture-overview)
4. [Infrastructure Design](#4-infrastructure-design)
5. [GitLab Configuration](#5-gitlab-configuration)
   - 5.1 Installation • 5.2 Core Configuration
   - 5.3 Azure AD SSO — 5.3.1 Azure AD config • 5.3.2 GitLab SAML config • 5.3.3 Break-glass admin • 5.3.4 Access scoping
   - 5.4 Git LFS • 5.6 Version pinning & upgrade runbook
6. [Disaster Recovery Design](#6-disaster-recovery-design)
   - 6.1 Philosophy • 6.2 Objectives • 6.3 Backup strategy • 6.4 Recovery procedure (see RUNBOOK-RECOVERY.md) • 6.5 Backup verification
7. [Monitoring & Alerting](#7-monitoring--alerting)
   - 7.1 Metrics stack • 7.2 Coverage • 7.3 Scheduled maintenance
   - 7.4 Alerting • 7.5 External observer (dead-man's-switch)
8. [Security Architecture](#8-security-architecture)
9. [Ransomware Protection](#9-ransomware-protection)
10. [Implementation Plan](#10-implementation-plan)
11. [Verification & Testing](#11-verification--testing)
12. [Operational Procedures](#12-operational-procedures)
- Appendix A: Config files • Appendix B: Useful commands
- Appendix C: Layered secrets management (sops + age, systemd-creds + Hetzner Cloud's no-TPM ceiling)
- Appendix D: Contact information

---

## 1. Executive Summary

### 1.1 Purpose

This document defines the complete technical architecture for ACME Corp' GitLab infrastructure hosted on Hetzner Cloud. It serves as the **single source of truth** for all implementation decisions.

### 1.2 Scope

- GitLab CE instance for 10-20 developers
- Git LFS support for electronics design files
- SSO integration with Microsoft Azure AD
- Backup-based disaster recovery
- Monitoring and alerting via Prometheus, Grafana, and Alertmanager
- Cron-driven hourly backups with weekly automated restore tests

### 1.3 Constraints

| Constraint | Description |
|------------|-------------|
| **Open Source Only** | No commercial software licenses |
| **Data Protection** | Hourly backups, encrypted offsite storage |
| **Budget** | ~63 EUR/month infrastructure |
| **Scale** | 10-20 developers initially |

### 1.4 Key Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| GitLab Edition | CE (Community) | Open source requirement |
| Hosting | Hetzner Cloud | Cost-effective, EU data residency |
| DR Strategy | Backup-based cold recovery | Simple, robust, cost-effective |
| Server Size | CPX31 (4 vCPU, 16GB) | Right-sized for 10-20 developers |
| Automation Model | Cron + Prometheus/Alertmanager | Deterministic, auditable, low operational risk |
| Backup Strategy | 3-2-1 with immutable tier | Ransomware-resistant (see Section 9) |
| Backup Destinations | Borg (append-only) + S3 (Object Lock) | Defense in depth |

**Design note**: Earlier drafts proposed an "Admin Bot" / LLM-driven "Integrator Bot" to perform administrator duties. That ambition was removed in v2.0 — see the v2.0 row of the document control table. Administration is now performed by humans, supported by deterministic monitoring (Prometheus + Alertmanager) and scheduled scripts (cron).

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
│  │                         ┌─────────────────┐                              │ │
│  │                         │   GITLAB        │                              │ │
│  │                         │   PRIMARY       │                              │ │
│  │                         │   (CPX31)       │                              │ │
│  │                         │                 │                              │ │
│  │                         │    Helsinki     │                              │ │
│  │                         │                 │                              │ │
│  │                         │  + Prometheus   │                              │ │
│  │                         │  + Grafana      │                              │ │
│  │                         │  + Alertmanager │                              │ │
│  │                         │  + cron backups │                              │ │
│  │                         └────────┬────────┘                              │ │
│  │                                  │                                       │ │
│  └──────────────────────────────────┼───────────────────────────────────────┘ │
│                                     │                                         │
│  ┌──────────────────────────────────┼──────────────────────────────────┐    │
│  │                                  │                                  │    │
│  │  ┌──────────────┐     ┌──────────▼────┐     ┌──────────────┐      │    │
│  │  │   OBJECT     │     │  STORAGE BOX  │     │   VOLUMES    │      │    │
│  │  │   STORAGE    │     │   (BACKUPS)   │     │  (300 GB)    │      │    │
│  │  │   (S3)       │     │    BX21       │     │              │      │    │
│  │  └──────────────┘     └───────────────┘     └──────────────┘      │    │
│  │                         STORAGE LAYER                              │    │
│  └────────────────────────────────────────────────────────────────────┘    │
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
| GitLab Primary | Main GitLab instance; also hosts Prometheus/Grafana/Alertmanager and cron-driven backup scripts | Helsinki (hel1) |
| Object Storage | LFS, artifacts, uploads | Helsinki (hel1) |
| Storage Box | Encrypted backups (offsite) | Helsinki (different DC) |
| Load Balancer | TLS termination, health checks | Helsinki (hel1) |

**Notes**:
- No hot standby secondary. Recovery via backup restoration to new server.
- No long-lived automation host: cron jobs and the monitoring stack are co-located on the GitLab server. Administration is performed by humans, augmented by alerts.

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
| **Location** | Helsinki (hel1) | `location` |
| **OS** | Ubuntu 24.04 LTS | `server_image` |
| **Cost** | ~18 EUR/month | - |

**Rationale**: CPX31 provides adequate resources for 10-20 developers. GitLab recommends 4+ vCPU and 8+ GB RAM for this scale.

**Scaling Options**:
- Small team (5-10): `cx31` (2 vCPU, 8GB) ~8 EUR/month
- Medium team (10-20): `cpx31` (4 vCPU, 16GB) ~18 EUR/month (default)
- Large team (20-50): `cpx41` (8 vCPU, 32GB) ~35 EUR/month

### 4.2 Network Architecture

#### 4.2.1 IP Addressing

```
Private Network: 10.0.0.0/16

Subnet: 10.0.1.0/24 (Production)
└── 10.0.1.10  GitLab Primary

Subnet: 10.0.2.0/24 (Future CI Runners)
└── Reserved for scaling
```

#### 4.2.2 Firewall Rules

**Public Firewall (gitlab-public-fw)**

| Direction | Protocol | Port | Source | Purpose |
|-----------|----------|------|--------|---------|
| Inbound | TCP | 443 | 0.0.0.0/0 | HTTPS |
| Inbound | TCP | 22 | Trusted admin IPs (CIDR) | SSH (admin + Git) |
| Inbound | TCP | 80 | 0.0.0.0/0 | HTTP→HTTPS redirect |

**Internal Firewall (gitlab-internal-fw)**

| Direction | Protocol | Port | Source | Purpose |
|-----------|----------|------|--------|---------|
| Inbound | ALL | ALL | 10.0.1.0/24 | Internal services / LB health checks |

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
| **Location** | Helsinki (different datacenter) |
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
| Block Storage | 300 GB | ~13 |
| Object Storage | ~2 TB | ~10 |
| Storage Box | BX21 (5 TB) | ~16 |
| Load Balancer | LB11 | ~6 |
| **Total** | | **~63** |

The previous design also provisioned a dedicated admin-bot server (CX32, ~7 EUR/month). That server was removed in v2.0 along with the bot itself.

---

## 5. GitLab Configuration

### 5.1 Installation

**Method**: Omnibus package (gitlab-ce)
**Version**: **Pinned** in `seed.yaml` (`gitlab.version`) and re-pinned with `apt-mark hold` on the server. Default `17.10.0-ce.0`. See §5.6 for the upgrade runbook.
**OS**: Ubuntu 24.04 LTS

```bash
curl https://packages.gitlab.com/install/repositories/gitlab/gitlab-ce/script.deb.sh | sudo bash
sudo EXTERNAL_URL="https://gitlab.example.com" apt-get install "gitlab-ce=17.10.0-ce.0"
sudo apt-mark hold gitlab-ce
```

The pin is threaded automatically by cloud-init: Terraform reads `gitlab_version` (generated from `seed.yaml`) and renders it into the apt install command, then holds the package.

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
  'endpoint' => 'https://hel1.your-objectstorage.com',
  'aws_access_key_id' => '<ACCESS_KEY>',
  'aws_secret_access_key' => '<SECRET_KEY>',
  'region' => 'hel1',
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

#### 5.3.3 Break-Glass Local Admin Account

`omniauth_auto_sign_in_with_provider = 'saml'` makes every login attempt redirect to Azure AD. If Azure AD is unavailable — outage, expired IdP cert, SAML metadata change, M365 tenant suspension — every login fails and no operator can reach the GitLab admin UI to fix the SSO configuration.

We mitigate this with a **single local-auth admin account** used only for SSO recovery.

**Properties of the break-glass account:**

| Attribute | Value |
|-----------|-------|
| Username | Non-obvious (e.g. `recovery-${random6}`) — recorded ONLY in the offline kit, never in this document or in `seed.yaml` |
| Email | `break-glass-${random}@<your-local-domain>` — must NOT match any Azure AD identity (prevents accidental SSO auto-link) |
| Password | 32+ chars, generated with `openssl rand -base64 24`. Stored in offline kit. |
| 2FA | TOTP enabled at creation. TOTP secret seed + 10 backup codes stored in offline kit. (Not WebAuthn — a physical hardware token cannot be assumed present during recovery; the offline kit is the only thing we guarantee is reachable.) Any standard RFC 6238 TOTP app works for routine use (Apple Passwords, 1Password, Bitwarden, Aegis, Google Authenticator, etc.) — but the **authoritative source of truth is the seed in the offline kit**, not the app. The app is a convenience overlay; if it (or the Apple/1Password/etc. account behind it) is unavailable, you re-seed any TOTP app from the offline kit. |
| Admin level | GitLab Administrator |
| State in normal operation | Active but unused. Any login generates a critical alert. |

**How to reach it during an SSO outage:**

```
https://<domain>/users/sign_in?auto_sign_in=false
```

The `?auto_sign_in=false` query parameter is a standard GitLab pattern. It bypasses the auto-redirect to Azure AD for that one login flow, presents the local-auth username/password form, then proceeds through normal 2FA. No changes to `gitlab.rb` are required to use it.

**Backup-to-the-backup** — if even the break-glass account is broken (forgotten password, lost TOTP, stolen kit), the server-side last-resort path is:

```bash
ssh root@<gitlab-server>
gitlab-rake "gitlab:password:reset[recovery-${random6}]"
# Prompted for new password; updates the account directly via Rails console.
```

This requires SSH access and works regardless of SSO state. Document it in the runbook but treat it as truly last-resort — every routine break-glass use should go through the bypass URL so the audit trail is consistent.

**Detection** — `monitoring/alerts.yml` defines a `BreakGlassLoginUsed` alert that fires on any login by the break-glass username. The intended dispatch:

- **You** used it (real SSO outage) → you see the alert, confirm, move on
- **Anyone else** used it → critical incident, rotate the break-glass credentials immediately, audit access to the offline kit

The metric this alert depends on is a GitLab-audit-log-to-Prometheus bridge that is not yet wired (see TODO.md). Until that bridge exists, detection is by periodic manual log review — much weaker. Implementing the bridge is on the same TODO line as the alert itself.

**Lifecycle** — see DESIGN.md Appendix C.8 (credential rotation matrix):
- **Quarterly**: log in once via the bypass URL to verify the kit still works. Rotate password and update kit. Record the verification date in the offline kit and as a comment in `seed.yaml`.
- **After any real use**: rotate password immediately, update kit, log the event in the post-incident report.
- **Operator turnover**: rotate immediately if the departing operator had ever held the offline kit.

**What this account is NOT for**: routine administration. Day-to-day admin actions go through SSO so that the audit trail names the actual operator. The break-glass exists to *restore SSO*, not to bypass it.

#### 5.3.4 Access Scoping (Who Can Use SSO)

By default, an Entra Enterprise App accepts authentication from **any user in your tenant**. For a self-hosted GitLab holding source code and CI secrets, that's almost always too permissive. Apply this in layers:

**Floor (must-do)**: Enterprise App → Properties → **Assignment required = Yes**. Without this, rejection of un-assigned users happens at GitLab after the SAML assertion is already issued. With it, rejection happens at Entra before SAML — cleaner audit, less attack surface.

**Standard pattern**: assign a security group, not individual users. Create `gitlab-users` (and tiered groups like `gitlab-readonly` if you want different roles) in Entra and assign the group to the app. Onboarding becomes "add to group" — same flow as every other Entra-managed resource. Removing someone from the group revokes GitLab SSO access immediately.

**Conditional Access (premium-tier)**: requires Entra ID P1 or P2 licensing — **NOT included in standard M365 Business Basic/Standard**; typically needs M365 Business Premium, E3/E5, or a standalone P1 license. If you have it, the single most valuable policy is **require MFA on this Enterprise App**: adds an Authenticator prompt independent of GitLab's own 2FA. Other useful policies: restrict to office/VPN IP ranges, require Intune-compliant device, block legacy auth.

**GitLab-side defence in depth (optional, currently off)**: `gitlab_rails['omniauth_block_auto_created_users'] = true` makes auto-created SSO users land blocked; a GitLab admin must unblock. Belt-and-braces if someone is added to `gitlab-users` who shouldn't be. The cost is friction — every new developer waits on a manual approval. At ACME's scale (10-20 devs, low turnover) we leave it off and trust Entra group membership as the gate. Revisit if turnover patterns change.

| Control | Cost | Recommendation at our scale |
|---------|------|------------------------------|
| Assignment Required toggle | Free | **Always on** |
| `gitlab-users` security group | Free | **Always** — never assign individuals directly |
| Conditional Access "require MFA on app" | Entra P1 (~6 EUR/user/mo if not bundled) | If licensing permits |
| Conditional Access geo/IP/device policies | Entra P1 | Optional; depends on threat model |
| `omniauth_block_auto_created_users` | Free | Off at this scale (friction > benefit) |
| `omniauth_external_providers = ['saml']` | Free | Off; doesn't fit our "one team" usage pattern |

**Sequencing risk**: if Assignment Required is enabled AND `gitlab-users` is empty, no one can SSO. Add yourself to the group BEFORE flipping the toggle, then verify your own SSO works before adding anyone else. The break-glass admin (§5.3.3) is reachable via the bypass URL regardless of Entra state, so this isn't a lockout risk — but it would be an embarrassing way to start a deploy.

**Interaction with `omniauth_auto_link_saml_user = true` (§5.3.2)**: SAML responses are matched to existing GitLab accounts by email. This is why the break-glass account's email is required to NOT match any Entra identity (§5.3.3). For routine users in `gitlab-users`, auto-link is what makes "first SSO = account created in GitLab" work correctly.

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

### 5.6 Version Pinning & Upgrade Runbook

GitLab CE is pinned to a specific apt package version in `seed.yaml` (`gitlab.version`), threaded into Terraform (`gitlab_version`), and held on the server with `apt-mark hold gitlab-ce`. This prevents `unattended-upgrades` or a stray `apt-get upgrade` from silently rolling the major version forward and breaking the schema migrations or omnibus configuration.

**Why pinning matters:**
- GitLab has had backwards-incompatible migrations *within* minor releases. A surprise upgrade during a backup window can leave the DB in an unrunnable state.
- The weekly restore-test (§6.5) installs the same pinned version on the ephemeral VM, so restore is tested against the version actually deployed — not whatever happens to be "latest stable" that week.
- Skipping required intermediate versions is unsupported by GitLab; pinning forces a deliberate upgrade path.

**Upgrade procedure** (operator-driven, typically once per minor release):

1. **Read the release notes** for every version between current and target. Pay special attention to:
   - Required upgrade stops (GitLab publishes a [version-paths matrix](https://docs.gitlab.com/ee/update/index.html#upgrade-paths))
   - Deprecated features your team uses
   - Background-migration warnings
2. **Take a fresh backup**: `sudo gitlab-backup create STRATEGY=copy` and verify it landed in Borg
3. **Run the restore-test cron manually** with the *current* pinned version to confirm rollback is possible
4. **Update the pin** in `seed.yaml` (`gitlab.version`), regenerate `terraform.tfvars`:
   ```bash
   python scripts/seed_bootstrap.py seed.yaml --target terraform
   ```
5. **Stage the upgrade** on the GitLab server:
   ```bash
   ssh root@<gitlab-server>
   sudo apt-mark unhold gitlab-ce
   sudo apt-get update
   sudo apt-get install gitlab-ce=<new-version>
   sudo apt-mark hold gitlab-ce
   ```
6. **Wait for background migrations** to complete:
   ```bash
   sudo gitlab-rake gitlab:background_migrations:status
   ```
   Do not start a second upgrade step until this returns clean.
7. **Verify**:
   ```bash
   sudo gitlab-rake gitlab:check SANITIZE=true
   sudo gitlab-ctl status
   curl -fsS https://<domain>/-/health
   ```
8. **Commit the seed change** so the pin in version control matches reality

**If the upgrade fails:**
- The append-only Borg backup taken in step 2 is the rollback. Run `scripts/restore-gitlab.sh` against a freshly provisioned server (or the same one after `gitlab-ctl cleanse`).
- Do NOT attempt to `apt-get install gitlab-ce=<old-version>` over a partially-upgraded omnibus — the schema may be ahead of the binary.

**Cadence**: at minimum, follow GitLab's [security release cadence](https://about.gitlab.com/releases/) (patches monthly). For minor versions, batch quarterly. Pin to the patch level always.

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
| BorgBackup sync | Hourly | 12 months (monthlies) | Storage Box (append-only) |
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

**Provisioning** (as of v2.7 — provider hcloud v1.63.0, May 2026):

Storage Boxes and their sub-accounts are now Terraform resources in
the unified Hetzner Cloud surface — no separate Hetzner Robot account
required. See `terraform/storage_box.tf` for the actual definitions.
Both the primary box and the append-only sub-account have
`lifecycle { prevent_destroy = true }` so a careless `terraform
destroy` cannot wipe the backup destination.

**Append-only enforcement is at the SSH command layer**, not the
Hetzner sub-account permission layer. The sub-account API only offers
`readonly = true` (blocks writes too — useless for backups) or full
read/write/delete. So the constraint is installed by
`scripts/setup-borg-append-only.sh`, which SFTPs the sub-account's
`~/.ssh/authorized_keys` to:

```
command="borg serve --append-only --restrict-to-repository /gitlab-borg",no-pty,no-port-forwarding,...  ssh-ed25519 AAAA...
```

The forced command means: any SSH session with this key can ONLY run
`borg serve --append-only`, restricted to the one repo. A root
compromise of the GitLab server cannot delete archives — only add new
ones. Initial `borg init` runs against an unconstrained key
(installed by `setup-borg-backup.sh`); the constraint is applied
immediately after, by `setup-borg-append-only.sh`.

```bash
# Both scripts on the GitLab server, run back-to-back, supplying the
# sub-account password (NOT a long-lived server secret — used twice for
# SFTP install, then rotated in the Hetzner Console):
sudo STORAGEBOX_SUBACCOUNT_PASSWORD='...' /opt/botlab/scripts/setup-borg-backup.sh
sudo STORAGEBOX_SUBACCOUNT_PASSWORD='...' /opt/botlab/scripts/setup-borg-append-only.sh
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

# Prune old backups (retention sourced from /etc/gitlab-backup.conf, generated
# from seed.yaml via `python scripts/seed_bootstrap.py seed.yaml --target borg-conf`)
borg prune \
    --keep-hourly="$BACKUP_KEEP_HOURLY" \
    --keep-daily="$BACKUP_KEEP_DAILY" \
    --keep-weekly="$BACKUP_KEEP_WEEKLY" \
    --keep-monthly="$BACKUP_KEEP_MONTHLY" \
    "$BORG_REPO"

# Clean local backups older than 24h
find /var/opt/gitlab/backups -name "*_gitlab_backup.tar" -mtime +1 -delete
```

**Cron schedule** (`/etc/cron.d/gitlab-backup`):
```
0 * * * * root /usr/local/bin/gitlab-backup-to-borg.sh >> /var/log/gitlab-backup.log 2>&1
```

### 6.4 Recovery Procedure

The operator-facing step-by-step procedure lives in [RUNBOOK-RECOVERY.md](RUNBOOK-RECOVERY.md). This section captures only the design-level summary.

| Step | Duration | What happens |
|------|----------|--------------|
| 1 | 5 min | Triage — confirm recovery is needed, not in-place repair |
| 2 | 10 min | Verify backup integrity on the recovery workstation (Borg or S3 fallback) |
| 3 | 5 min | Provision replacement CPX31 via `terraform apply -target=...` |
| 4 | 5 min | Restore `gitlab.rb` and `gitlab-secrets.json` from Borg |
| 5 | 30-60 min | Restore GitLab tarball (`gitlab-backup restore`) |
| 6 | 5 min | `gitlab-ctl reconfigure` and verification (`gitlab:check`, sample clone, login) |
| 7 | 5 min | Re-point LB target (or update DNS if LB also lost) |
| 8 | — | Post-recovery: rotate every credential, capture forensic image if compromise suspected, run a fresh backup, write the post-incident report |
| **Total** | **~1-2 hours** | |

Design notes:
- Recovery is **operator-driven**. There is no autonomous agent; a human runs the runbook end-to-end.
- The Borg full-access key required for step 4-5 lives **offline only** — the append-only key on the GitLab server cannot decrypt archives. Step 4-5 happen on a recovery workstation, not the new server.
- If the entire Hetzner account is lost, Terraform state from the offline kit drives a rebuild in a fresh account. RTO doubles to ~3 hours in that case (Appendix B in the runbook).

Supporting tools:
- `scripts/restore-gitlab.sh` — opinionated wrapper around runbook steps 4-6
- `scripts/verify-backup.sh` — JSON-output sanity check on a candidate backup
- `terraform apply -target=...` — provisions the replacement

### 6.5 Backup Verification (Weekly Automated)

Weekly restore test driven by cron on the GitLab server (or run manually from an operator workstation):

1. Provision ephemeral CX21 server via Terraform / `hcloud` CLI
2. Install GitLab CE (same version as production)
3. Restore latest backup from Borg
4. Verify:
   - Web UI accessible (HTTP 200 on `/-/health`)
   - Sample repo cloneable
   - Database integrity (`gitlab-rake gitlab:check`)
5. Emit Prometheus metric `gitlab_restore_test_success{...}` via the textfile collector
6. Destroy ephemeral VM
7. Alertmanager fires if the metric is missing or `0` for the current week

Alerting on the metric gives the same "did the restore test pass?" signal previously produced by the bot, without long-lived automation credentials.

---

## 7. Monitoring & Alerting

### 7.1 Metrics Stack

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

Prometheus, Alertmanager, and Grafana run on the GitLab primary server (systemd units). The textfile collector exposes outputs of cron scripts (backup age, restore-test result, borg integrity check) as Prometheus metrics.

### 7.2 Monitoring Coverage

| Signal | Source | Warning | Critical |
|--------|--------|---------|----------|
| GitLab health endpoint | blackbox_exporter on `/-/health` | — | down for 2m |
| Disk usage (`/var/opt/gitlab`) | node_exporter | 80% | 90% |
| Memory | node_exporter | 80% | 95% |
| CPU (15m load) | node_exporter | 70% | 90% |
| Backup age | cron + textfile collector | > 2h | > 4h |
| Borg repo integrity | weekly cron + textfile | — | last check failed |
| Weekly restore-test | weekly cron + textfile | — | last run failed or missing |
| SSL certificate expiry | blackbox_exporter / cert script | 30 days | 7 days |

### 7.3 Scheduled Maintenance (cron)

Hourly:
- `gitlab-backup-to-borg.sh` — create GitLab backup, ship to Borg, prune local

Daily (03:00 UTC):
- Log rotation, orphaned-artifact cleanup
- Optional weekly S3 immutable backup (Sundays, see `scripts/backup-to-s3.sh`)

Weekly (Sunday):
- Container registry garbage collection (`gitlab-ctl registry-garbage-collect`)
- `borg check --repository-only` (integrity)
- Restore test on ephemeral VM (see 6.5)

Monthly:
- `unattended-upgrades` security patches review
- Storage growth report (Grafana dashboard snapshot, emailed)

### 7.4 Alerting

Alertmanager handles routing and deduplication. Operators receive:

| Severity | Channel | Repeat |
|----------|---------|--------|
| Critical | Email + webhook | Every 1h until resolved |
| Warning | Email | Every 12h until resolved |
| Info | Email digest | Daily |

Alert rules live in `monitoring/alerts.yml` (committed in this repo). Load them via Prometheus's `rule_files:` directive.

### 7.5 External Observer (Dead-Man's-Switch)

Prometheus, Alertmanager, and Grafana all run on the GitLab server itself. That's the right trade-off at this scale (one box to patch, no extra credentials) but it creates a blind spot: if the GitLab server is unreachable, on fire, or compromised, **the very thing that would alert you about that is also down**.

The mitigation is a small external observer that lives outside this Hetzner account and watches the stack from the outside.

**What it watches:**

1. **Public LB endpoint** — HTTPS probe of `https://<domain>/-/health` every 1–5 minutes. Alerts if probes fail for ≥ 5 minutes. This catches "GitLab itself is down" even when our own Alertmanager can't tell us.
2. **Alertmanager Watchdog** — `monitoring/alerts.yml` defines a `Watchdog` alert that fires constantly (`expr: vector(1)`, severity `none`). Alertmanager dispatches it to a webhook on the external observer. The observer alerts on its *absence* for > 5 minutes — that's how we learn the on-box monitoring stack has stopped working.

**Where it runs** — the observer must not share a failure domain with what it observes:

| Option | Cost | Pros / cons |
|--------|------|-------------|
| Public uptime service (UptimeRobot, BetterStack, HetrixTools, etc.) free tier | 0 EUR/mo | Easiest. Solves the LB probe. Some free tiers don't accept inbound webhooks, which limits the Watchdog half. |
| Tiny VPS on a non-Hetzner provider (Vultr / Linode / OVH, 1 vCPU / 1 GB) running blackbox_exporter + a webhook receiver | ~5 EUR/mo | Full coverage of both signals. Survives a Hetzner-wide outage or account lockout. **Recommended.** |
| Dedicated monitoring node on Hetzner in a different DC (Nuremberg/Helsinki) | ~4 EUR/mo | Cheaper, but does not survive Hetzner account-level problems. Only worth it if you also want full Prometheus+Grafana off-box. |

**What it does NOT do:**

- It is not a second Prometheus/Grafana. It runs *only* the two probes above. Any temptation to give it credentials, cron jobs, or "while we're here, let's also..." should be resisted — that is how you slowly rebuild the admin-bot we just removed.
- It does not solve Hetzner account compromise on its own. The cross-provider S3 immutable backup tier is still the right control for that.

**Implementation status**: not yet provisioned. The `Watchdog` alert is committed; Alertmanager routing for the watchdog webhook and the external probe itself are tracked in `TODO.md` under Phase 4.

---

## 8. Security Architecture

### 8.1 Authentication

| Component | Method |
|-----------|--------|
| GitLab Web | Azure AD SAML SSO + 2FA |
| GitLab SSH | SSH keys (Ed25519 preferred) |
| Server SSH | SSH keys only, no password; restricted by `trusted_ssh_ips` |

### 8.2 Authorization

| Role | Capabilities |
|------|--------------|
| Admin | Full GitLab admin, server SSH |
| Developer | Project access per group |

### 8.3 Encryption

| Layer | Method |
|-------|--------|
| Transit | TLS 1.2+ everywhere |
| At Rest (backups) | BorgBackup repokey-blake2 |
| At Rest (volumes) | Hetzner default encryption |
| Secrets | Stored in `seed.yaml` (encrypted via sops/age recommended); rendered into `gitlab.rb` and `/etc/gitlab-backup.conf` at provisioning time |

### 8.4 Network Security

- All inter-server communication over private network
- Public access only through Load Balancer
- Firewall default deny
- SSH restricted to trusted CIDRs
- Rate limiting on authentication endpoints (rack_attack)

---

## 9. Ransomware Protection

> **Full Analysis**: See [SECURITY-ASSESSMENT.md](SECURITY-ASSESSMENT.md) for complete threat model and recommendations.
>
> **Implementation status**: Append-only Borg setup (`scripts/setup-borg-append-only.sh`), S3 immutable backups (`scripts/backup-to-s3.sh`), and extended retention (12 months) are implemented. Weekly `borg check --repository-only` integrity verification is wired through cron + the Prometheus textfile collector (see Section 7). Seed configuration supports S3 via `backup.s3` section.

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
│   ├── Backup integrity verification (weekly `borg check`)               │
│   ├── Restore-test success metric (weekly)                              │
│   ├── Auth log analysis (fail2ban)                                      │
│   └── Prometheus alerts on disk/file anomalies                          │
│                                                                          │
│   Layer 3: RECOVERY                                                      │
│   ├── Borg backups (append-only, cannot delete)                         │
│   ├── S3 immutable backups (Object Lock WORM)                           │
│   ├── Offline quarterly backups                                         │
│   └── Operator-driven DR runbook (`scripts/restore-gitlab.sh`)          │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

### 9.3 Backup Immutability

| Destination | Delete Protection | Modification Protection | Retention |
|-------------|-------------------|------------------------|-----------|
| Borg Primary | Append-only (sub-account) | Encryption (repokey) | 12 months (monthlies) |
| S3 Immutable | Object Lock Governance | Object Lock WORM | 90 days |
| Offline | Physical separation | Air-gapped | 1 year |

**Critical**: Full-access Borg credentials (for prune/delete) stored OFFLINE only.

### 9.4 Ransomware Detection

Detection is deterministic and signal-based, not behavioural:

| Indicator | Detection Method | Response |
|-----------|-----------------|----------|
| Backup tampering | Weekly `borg check --repository-only`, metric → Alertmanager | Critical alert; verify immutable copy on S3 |
| Backup absent | Backup-age metric > 4h | Critical alert |
| Restore test fails | Weekly restore-test metric == 0 | Critical alert |
| Mass file changes | Optional auditd / AIDE on `/var/opt/gitlab` | Critical alert |
| Auth anomalies | fail2ban, SSH log review | Manual triage |

Behavioural / heuristic detection of in-progress ransomware (encrypted file extensions, ransom notes, suspicious processes) is **out of scope** for this design — the recovery posture is the primary control. Operators may layer AIDE or auditd onto the server if desired.

### 9.5 Incident Response Procedure

If ransomware is suspected or confirmed:

1. **DO NOT** shut down (preserve forensic evidence)
2. **VERIFY** immutable backup integrity immediately (`borg check`, S3 listing)
3. **ISOLATE** network (operator detaches LB target or revokes firewall)
4. **ASSESS** damage scope (read-only inspection from a fresh workstation)
5. **RECOVER** from immutable backup (S3 Object Lock) onto a new server
6. **INVESTIGATE** root cause
7. **DOCUMENT** incident

See [SECURITY-ASSESSMENT.md](SECURITY-ASSESSMENT.md) for detailed procedures.

---

## 10. Implementation Plan

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

### Phase 4: Monitoring & Alerting (Week 4)

| Task | Description |
|------|-------------|
| 4.1 | Install Prometheus, Alertmanager, Grafana (systemd) |
| 4.2 | Install node_exporter, blackbox_exporter, gitlab-exporter |
| 4.3 | Configure alert rules (`monitoring/alerts.yml`) |
| 4.4 | Configure Alertmanager email/webhook routes |
| 4.5 | Install textfile collector + cron-emitted metrics (backup age, borg check, restore test) |
| 4.6 | Wire weekly restore-test cron to ephemeral VM |

**Deliverables**: Working monitoring stack with email alerts on failures

### Phase 5: Testing & Documentation (Week 5-6)

| Task | Description |
|------|-------------|
| 5.1 | Full system testing |
| 5.2 | DR recovery drill |
| 5.3 | Security review |
| 5.4 | Write operations documentation |
| 5.5 | User onboarding guide |

**Deliverables**: Complete documentation, successful DR drill

---

## 11. Verification & Testing

### 11.1 Test Cases

| ID | Test | Expected Result |
|----|------|-----------------|
| T01 | Access GitLab web UI | HTTPS works, valid certificate |
| T02 | Login via Azure AD SSO | User created, redirected to dashboard |
| T03 | Create project and push code | Repository created successfully |
| T04 | Push large file via LFS | File stored in object storage |
| T05 | Run CI/CD pipeline | Pipeline executes, artifacts stored |
| T06 | Verify backup exists | Backup file in Storage Box |
| T07 | Restore from backup | GitLab functional after restore |
| T08 | Alertmanager fires on simulated failure | Email/webhook received within 5 minutes |

### 11.2 DR Drill Procedure

1. Schedule maintenance window
2. Notify stakeholders
3. Simulate primary failure (shutdown)
4. Execute recovery procedure (provision + restore)
5. Verify all services
6. Test user access and git operations
7. Document results and lessons learned

---

## 12. Operational Procedures

### 12.1 Daily Checks (Automated via Prometheus/Grafana)

- [ ] GitLab `/-/health` returning 200
- [ ] Most recent Borg archive < 4h old
- [ ] Disk usage < 80% on `/var/opt/gitlab`
- [ ] No firing alerts in Alertmanager

### 12.2 Weekly Tasks

- [ ] Review Grafana dashboards for capacity / response trends
- [ ] Confirm weekly restore-test metric is `1`
- [ ] Confirm weekly `borg check` metric is `1`
- [ ] Review GitLab security advisories

### 12.3 Monthly Tasks

- [ ] Apply security updates (unattended-upgrades + reboot window)
- [ ] Review access permissions
- [ ] Capacity planning review

### 12.4 Incident Response

1. **Detect**: Alertmanager notification or user report
2. **Triage**: Assess severity and impact
3. **Communicate**: Notify stakeholders
4. **Resolve**: Follow runbook (`scripts/restore-gitlab.sh` for data-loss cases) or escalate
5. **Document**: Post-incident report

---

## Appendix A: Configuration Files Reference

| File | Location | Purpose |
|------|----------|---------|
| gitlab.rb | /etc/gitlab/gitlab.rb | Main GitLab config |
| gitlab-secrets.json | /etc/gitlab/gitlab-secrets.json | Encryption keys (CRITICAL) |
| gitlab-backup.conf | /etc/gitlab-backup.conf | Borg repo, passphrase, retention |
| gitlab-s3-backup.conf | /etc/gitlab-s3-backup.conf | S3 immutable backup credentials |
| prometheus.yml | /etc/prometheus/prometheus.yml | Prometheus scrape config |
| alerts.yml | /etc/prometheus/alerts.yml | Alert rules |
| alertmanager.yml | /etc/alertmanager/alertmanager.yml | Routing/receivers |

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

# Alertmanager / Prometheus
systemctl status prometheus alertmanager grafana-server
journalctl -u prometheus -f
```

## Appendix C: Layered Secrets Management

### C.1 Why layered

"Encrypt secrets at rest" sounds airtight but on a single-server deployment, encryption at rest mostly protects against **stolen disk** and **backup leak** — it does *not* protect against **root compromise of the running server**. If an attacker gets root, they can read process memory, the kernel keyring, the systemd credentials directory, and any file a running service can read. Encryption at rest cannot prevent that, by definition: the running service must be able to decrypt.

So this appendix decomposes secrets by access pattern and treats each layer separately. The goal isn't "encrypt everything"; it's "minimise what the server needs at runtime, and harden what's unavoidable."

### C.2 The decomposition

| Secret | Read when | Read by | Lives on server? |
|--------|-----------|---------|------------------|
| `infrastructure.hetzner.api_token` | `terraform apply` only | Operator workstation | **No.** Laptop only. |
| Borg full-access key + admin passphrase | Disaster recovery only | Recovery workstation | **No.** Offline recovery kit only. |
| Operator SSH private keys | Every SSH login | Operator | **No.** Workstation, ideally hardware-token-resident. |
| Borg encryption passphrase | Hourly backup cron | Backup script on server | **Yes.** Layer 2 protected. |
| Storage Box append-only SSH key | Hourly backup cron | Backup script on server | **Yes.** Layer 2 protected. |
| S3 access key + secret | Weekly S3 cron | S3 backup script on server | **Yes.** Layer 2 protected. |
| `gitlab-secrets.json` | Every GitLab boot + every encrypted-column access | `gitlab-rails` service | **Yes.** Layer 3 protected. |
| `smtp_password` | Every email sent | `gitlab-rails` service | **Yes.** Layer 3 protected. |
| Azure AD SAML cert | Every SSO callback | `gitlab-rails` service | **Yes.** Layer 3 protected. |

### C.3 Layer 1 — Eliminate secrets that don't need to be on the server

This is the highest-leverage step and costs nothing in operational complexity.

**`hcloud_token`** is read only during `terraform apply` from the operator workstation. The generated `terraform/terraform.tfvars` is gitignored and never copied to the server. Verify in your runbook that no script ever `scp`s `terraform.tfvars` or the rendered token to the GitLab box. The cloud-init template does not need it; Terraform itself uses it from the laptop.

**Borg full-access key and admin passphrase** live only in the offline recovery kit (USB / safe / password manager). `scripts/setup-borg-append-only.sh` Step 7 securely deletes the on-server copies (`/root/.ssh/storagebox_key` and `/root/.ssh/storagebox_admin_key`) once you confirm the offline copy is verified. **The append-only design is only real once this step runs to completion** — running setup-borg-backup.sh without running setup-borg-append-only.sh through to deletion leaves the server with full Storage Box credentials.

**Per-cron-job GitLab API tokens** are *not* stored in `seed.yaml`. When a future script needs API access (e.g. the weekly restore-test querying the running GitLab), generate a token at the *narrowest* scope it needs (project-level + specific permissions, not global `api` scope), store it via systemd-creds for that one timer's service, and rotate it with the script (a fresh token on every install). A global `gitlab.private_token` field is a false convenience — it grows access rather than scoping it.

**Operator SSH private keys** belong on the operator's workstation only, ideally backed by a hardware token (YubiKey-resident SSH key with PIN + presence). Public halves are uploaded via `infrastructure.ssh.admin_keys.*` in `seed.yaml` — the server only ever sees the public side.

### C.4 Layer 2 — `systemd-creds` for unavoidable server-side runtime secrets

For secrets that *must* be readable by something on the server (Borg passphrase, S3 keys), use [`systemd-creds`](https://www.freedesktop.org/software/systemd/man/systemd-creds.html). It encrypts a credential at rest and decrypts it only when loading into a specific service unit's `$CREDENTIALS_DIRECTORY`. Credentials are not visible to other processes, not in environment variables, not in `/proc/PID/environ`.

**Hetzner Cloud caveat — no TPM available.** Hetzner Cloud Servers do not expose TPM/vTPM ([Hetzner FAQ](https://docs.hetzner.com/de/cloud/servers/faq/)). systemd-creds therefore falls back to a per-host key at `/var/lib/systemd/credential.secret`. We accept this trade-off: it's a meaningfully diminished protection compared to TPM-sealing, but it still closes the most likely real-world leak vector (Borg archives or other backups escaping). See C.4a for the "if you ever care enough to move to dedicated hardware" path.

**What Layer 2 actually protects against on Hetzner Cloud:**

| Threat | Without Layer 2 | With Layer 2 (host-key fallback) |
|--------|-----------------|----------------------------------|
| Borg backup leak — `/etc/gitlab/` extracted from a stolen archive | Secrets exposed | Encrypted credential is not in our Borg backups (the backup script only ships `gitlab.rb` + `gitlab-secrets.json`); host key not in any backup. **Secrets safe.** |
| Operator accidentally `scp`s `/etc/gitlab-backup.conf` somewhere | Secrets exposed | The file no longer contains secrets — only structural config. **Safe.** |
| Non-root filesystem read on the server | Both files are 0600 root — already protected | Same |
| Hetzner-side disk image exfiltration (full disk handed to attacker) | Secrets exposed | Both encrypted credential and host key on the same disk → **secrets exposed** |
| Root compromise on running server | Secrets exposed | Secrets exposed (Layer 4 is the only answer) |

The first two rows are the realistic wins and the reason to bother. The fourth row is the residual risk Hetzner Cloud forces on us; closing it would require dedicated hardware (C.4a). The fifth row is the same as it always was: nothing in this appendix prevents root compromise — Layer 4 does.

**Operational invariant for future maintainers**: do NOT add `/var/lib/systemd/credential.secret` or `/etc/credstore.encrypted/` to any backup script. The whole point of the host-key fallback is that the key lives only on the running host and not in the backup that contains the encrypted credentials.

**One-time encryption** (run on the GitLab server as root):

```bash
# Borg passphrase
read -rsp "Borg passphrase: " BORG_PASS && echo
printf '%s' "$BORG_PASS" | sudo systemd-creds encrypt \
    --name=borg_passphrase \
    --with-key=host \
    - /etc/credstore.encrypted/borg_passphrase
unset BORG_PASS

# S3 access key
read -rp "S3 access key: " S3_AK
printf '%s' "$S3_AK" | sudo systemd-creds encrypt \
    --name=s3_access_key --with-key=host \
    - /etc/credstore.encrypted/s3_access_key

# S3 secret key
read -rsp "S3 secret key: " S3_SK && echo
printf '%s' "$S3_SK" | sudo systemd-creds encrypt \
    --name=s3_secret_key --with-key=host \
    - /etc/credstore.encrypted/s3_secret_key
unset S3_SK

sudo chmod 600 /etc/credstore.encrypted/*
```

`--with-key=host` explicitly selects the host-key path. Omitting it lets systemd-creds choose (`auto`), which on a TPM-equipped host would use TPM. Pinning to `host` makes the code behave the same way regardless of the underlying hardware, which matters when you might later test the same scripts on a TPM-equipped machine.

**Consuming the credential** — convert the cron into a systemd timer (this also closes TODO T2.3):

```ini
# /etc/systemd/system/gitlab-backup.service
[Unit]
Description=Hourly GitLab backup to Borg
After=network-online.target gitlab-runsvdir.service
Wants=network-online.target

[Service]
Type=oneshot
LoadCredentialEncrypted=borg_passphrase
ExecStart=/usr/local/bin/gitlab-backup-to-borg.sh
# The script reads via: BORG_PASSPHRASE="$(cat "$CREDENTIALS_DIRECTORY/borg_passphrase")"

# /etc/systemd/system/gitlab-backup.timer
[Unit]
Description=Hourly GitLab backup

[Timer]
OnCalendar=hourly
Persistent=true
RandomizedDelaySec=300

[Install]
WantedBy=timers.target
```

The Borg passphrase exists in plaintext only inside the backup script's process memory while it runs (typically a few minutes per hour). No other process can read it; no on-disk plaintext copy exists.

**`/etc/gitlab-backup.conf` becomes structural-only** — repo URL, key path, retention numbers. No secret material. The `BORG_PASSPHRASE` line is removed; the script gets it from `$CREDENTIALS_DIRECTORY` instead. `seed_bootstrap.py --target borg-conf` should be updated to stop emitting `BORG_PASSPHRASE` when Layer 2 is in effect.

### C.4a — If you ever need TPM-grade sealing

The disk-exfiltration row in the C.4 table is the residual risk Hetzner Cloud cannot close. If your threat model genuinely requires protection against Hetzner-side disk image leak, the only path is dedicated hardware:

- **Hetzner Dedicated (Robot)** servers ship with physical TPM2. AX-class machines are ~47 EUR/mo and up, broadly competitive with the cloud setup once you add Storage Box and Object Storage — but the operational profile is very different: bare-metal install, hours-long provisioning, no `hcloud_load_balancer`, the Robot Terraform provider is more limited than the Cloud one. Migration is a non-trivial project, not a flag flip.
- Other EU providers with TPM2 on bare metal (OVHcloud, Scaleway Elastic Metal, Leaseweb) are options if you'd rather diversify.

The migration to TPM, once on appropriate hardware, is a one-shot re-encryption of each credential with `--with-key=auto --tpm2-pcrs=7+11`. The consuming service units (`LoadCredentialEncrypted=...`) don't change. So **Layer 2 today is forward-compatible with a future TPM-equipped host** — implementing it now is not throwaway work.

For the ACME deployment as specified (~63 EUR/mo, 10-20 devs, EU residency, accepted Hetzner-vendor risk), the operational cost of dedicated hardware is disproportionate to the marginal security gain. We document this choice rather than make it silently.

### C.5 Layer 3 — GitLab's own runtime secrets (SMTP, SAML, `gitlab-secrets.json`)

GitLab Omnibus reads `/etc/gitlab/gitlab.rb` at every `gitlab-ctl reconfigure` and `/etc/gitlab/gitlab-secrets.json` at every Rails boot. We use two techniques:

**`gitlab.rb`** can read individual values from files using normal Ruby:

```ruby
gitlab_rails['smtp_password'] = File.read('/run/gitlab-secrets/smtp_password').strip
gitlab_rails['omniauth_providers'] = [
  {
    name: "saml",
    args: {
      idp_cert: File.read('/run/gitlab-secrets/saml_idp_cert'),
      # ... other args ...
    }
  }
]
```

Populate `/run/gitlab-secrets/` (a tmpfs — never touches disk) at boot from systemd-creds via a oneshot unit that runs before `gitlab-runsvdir.service`:

```ini
# /etc/systemd/system/gitlab-secrets-populate.service
[Unit]
Description=Materialise GitLab runtime secrets from systemd-creds
DefaultDependencies=no
After=local-fs.target
Before=gitlab-runsvdir.service

[Service]
Type=oneshot
RemainAfterExit=yes
LoadCredentialEncrypted=smtp_password
LoadCredentialEncrypted=saml_idp_cert
ExecStartPre=/usr/bin/mkdir -p /run/gitlab-secrets
ExecStartPre=/usr/bin/mount -t tmpfs -o size=1m,mode=0700 tmpfs /run/gitlab-secrets
ExecStart=/bin/sh -c 'cp $CREDENTIALS_DIRECTORY/* /run/gitlab-secrets/ && chmod 600 /run/gitlab-secrets/*'

[Install]
WantedBy=multi-user.target
```

**`gitlab-secrets.json`** is the awkward case — GitLab expects it at a fixed path and re-reads it on every reconfigure. Two options:

1. **Pragmatic**: leave it at `/etc/gitlab/gitlab-secrets.json` with `chmod 600 root:root`. Accept that root compromise reveals it. Mitigate root-compromise risk via Layer 4 (below) rather than trying to encrypt this specific file.

2. **Stronger but operationally annoying**: bind-mount `/etc/gitlab/gitlab-secrets.json` from the same tmpfs populated by the unit above. Requires fighting omnibus during upgrades because `gitlab-ctl reconfigure` may rewrite the file. Defer until you have a tested workaround.

We currently recommend (1) and put the energy into Layer 4.

### C.6 Layer 4 — Prevent root compromise (because encryption at rest can't)

Every layer above falls apart under root compromise on the running server. So invest equally in preventing it. The relevant TODO items:

- **T1.4** — `trusted_ssh_ips` required, no wildcard fallback
- **T1.5** — monitoring stack bound to 127.0.0.1, reached via SSH port-forward
- **T1.6** — vendor + checksum the GitLab repo install script
- **T2.3** — `sshd` fail2ban jail (in addition to the GitLab-auth jail)
- **T2.7** — AIDE file integrity monitoring on `/var/opt/gitlab` and `/etc/gitlab`
- **T2.8** — break-glass local admin account model documented
- Disable root SSH; require sudo with logging
- Configure `unattended-upgrades` for security patches with a controlled reboot window

These do more for your *actual* secrets safety than any amount of encryption-at-rest cleverness.

### C.7 Operator-side: sops + age for `seed.yaml`

`seed.yaml` on the operator's workstation contains every laptop-side secret (`hcloud_token`, the Borg passphrase before you encrypt it on the server, SMTP password, SAML cert, etc.). Encrypt it with [sops](https://github.com/getsops/sops) + [age](https://age-encryption.org/):

```bash
# One-time per operator
age-keygen -o ~/.config/sops/age/keys.txt        # writes private key; prints public key
# Share the public key with other operators who need access

# Configure sops for this repo (.sops.yaml at repo root)
cat > .sops.yaml <<'EOF'
creation_rules:
  - path_regex: ^seed\.yaml$
    age: >-
      age1<operator-1-public-key>,
      age1<operator-2-public-key>
EOF

# Encrypt the seed in place
sops --encrypt --in-place seed.yaml

# Edit it: decrypts to $EDITOR, re-encrypts on save
sops seed.yaml

# Use at deploy time without leaving plaintext on disk
sops exec-file --no-fifo seed.yaml \
  'python scripts/seed_bootstrap.py {} --target all'
```

The encrypted `seed.yaml` is safe to keep on USB drives, in password managers, or even (controversially) committed to the repo. We default to gitignoring it because committing-encrypted-things is a choice you should make deliberately.

### C.8 Credential rotation cadence

| Secret | Cadence | How |
|--------|---------|-----|
| Borg encryption passphrase | 12 months OR operator turnover | `borg key change-passphrase` on recovery workstation; update offline kit; re-encrypt with systemd-creds on server |
| Storage Box **append-only** SSH key (on server) | 12 months OR after suspected compromise | re-run `setup-borg-append-only.sh` on the server — generates a fresh keypair and SFTPs the new constrained `authorized_keys`, replacing the old. Old key revoked atomically by the SFTP overwrite. |
| Storage Box **sub-account password** | After every `setup-borg-*.sh` run (one-shot use) and after any operator turnover | Hetzner Cloud Console → Storage Box → Sub-accounts → Reset password. No server-side update needed; the server uses the SSH key, not the password. |
| Storage Box **primary** (OFFLINE) SSH key | 24 months OR operator turnover | regenerate keypair offline; update offline kit; replace via Hetzner Console (the Terraform resource has `ignore_changes = [ssh_keys]` because the create-only API would otherwise force destroy/replace and lose the repo). |
| Storage Box primary password | 12 months OR operator turnover | Hetzner Cloud Console → Storage Box → Reset password. Update `seed.yaml` + offline kit. Used only for Console access. |
| `hcloud_token` | 6 months OR operator turnover | Hetzner Cloud console → rotate; update seed.yaml. **NB:** this token now controls Storage Boxes too (since the Cloud Console unification in v2.7), so its blast radius grew — treat with extra care. |
| GitLab per-script API tokens | At each script install | scripted; generate fresh on every install |
| SMTP password | 12 months | rotate at provider; update seed; re-encrypt via systemd-creds |
| Azure AD SAML cert | per Azure cert lifetime | follow Azure AD rotation procedure; update seed |
| SSH host keys | OS reinstall only | OS-managed |
| Operator SSH keys | per operator policy | operator responsibility; hardware tokens preferred |

Track "last rotated" dates either in `seed.yaml` as comments next to each value or in a separate `docs/CREDENTIAL-LEDGER.md`. The point is that *somewhere* records when each credential was last touched.

### C.9 What this appendix deliberately rejects

- **HashiCorp Vault**: the right tool for 50+ servers, not for a single GitLab box. The operational overhead (HA cluster, unsealing, audit log integration, network dependency on every secret read) exceeds the security benefit at this scale.
- **Cloud KMS** (AWS/GCP/Azure): introduces vendor concentration we've explicitly designed against. Network round-trip for every secret read. Adds a credential to access the credential store.
- **Hardware HSM** (YubiHSM2, etc.): meaningful for signing keys; doesn't help with password-shaped secrets. Wrong fit.
- **Manual passphrase unseal at boot**: incompatible with the ~99% uptime target and unattended-upgrades reboots.
- **Clevis + Tang**: requires running a Tang server somewhere reachable at boot. The external observer (§7.5) could double as Tang, but its compromise then releases all our keys. Defers the problem.

---

## Appendix D: Contact Information

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
| 2.0 | 2026-05-12 | Claude Code | Dropped the Admin Bot and the (planned) LLM-driven Integrator Bot. Monitoring/automation replaced by Prometheus + Alertmanager + cron on the GitLab server. Removed the dedicated admin-bot CX32 instance from infrastructure (~7 EUR/month savings). Removed Section 7.8 (per-repo bot policies). |
| 2.1 | 2026-05-15 | Claude Code | Pinned GitLab version (new §5.6 upgrade runbook); added §7.5 external dead-man's-switch observer; reconciled backup retention numbers (12-month monthlies everywhere); fixed cloud-init backup script to honour `/etc/gitlab-backup.conf`. Extracted DR steps to `RUNBOOK-RECOVERY.md`; added first-deploy `DEPLOY.md`; added Appendix C (sops + age secrets management); shipped starter `monitoring/alerts.yml` including the `Watchdog` dead-man alert. |
| 2.2 | 2026-05-15 | Claude Code | Rewrote Appendix C as **Layered Secrets Management** (Layer 1 server-side elimination → Layer 2 systemd-creds + TPM2 → Layer 3 GitLab runtime via tmpfs → Layer 4 root-compromise prevention). Removed unused `gitlab.private_token` from seed schema. Added DEPLOY.md §2a clarifying which secret belongs where. Closed Security Review finding T1.1a: `setup-borg-append-only.sh` now securely shreds the full-access SSH keys (with operator confirmation) instead of leaving them on disk with manual cleanup instructions. |
| 2.2.1 | 2026-05-15 | Claude Code | **Correction**: v2.2 Appendix C.4 incorrectly assumed Hetzner Cloud Servers expose TPM/vTPM. They do not (per [Hetzner FAQ](https://docs.hetzner.com/de/cloud/servers/faq/)). C.4 rewritten around `systemd-creds` with the per-host-key fallback, with an explicit threat-properties table showing what this does and does not protect against. New C.4a documents the dedicated-hardware path for users who genuinely need TPM-grade sealing. SECURITY-ASSESSMENT.md §4.1 gained an explicit "Hetzner-side disk image exfiltration" row. SECURITY-REVIEW T1.1 Layer 2 status updated to reflect the host-key-only ceiling. |
| 2.3 | 2026-05-15 | Claude Code | Closed Security Review T2.8 — break-glass local admin account. New §5.3.3 documents the account model (non-obvious username, email outside Entra tenant, 32-char password + TOTP with offline backup codes, single-purpose use). DEPLOY.md §5 split into 5a-5d to enforce correct ordering: create break-glass BEFORE enabling `omniauth_auto_sign_in_with_provider` to avoid the chicken-and-egg lockout. New RUNBOOK-RECOVERY.md Appendix D covers SSO failure recovery end-to-end (bypass URL, TOTP backup codes, `gitlab-rake` last-resort reset, common SAML failure modes). New `BreakGlassLoginUsed` alert rule committed. Sub-finding T2.8a opened: alert depends on a not-yet-wired GitLab audit-log → Prometheus bridge. |
| 2.4 | 2026-05-15 | Claude Code | Fleshed out break-glass from "designed" to "scripted, verified, operator-proof". New `scripts/setup-break-glass.sh` provisions the account (with server-side TOTP) via `gitlab-rails runner`, eliminating the UI click-through. New `scripts/verify-break-glass.sh` performs quarterly verification: confirms account state (exists, admin, confirmed, 2FA, not blocked), confirms the bypass URL serves the local-auth form, and emits Prometheus textfile metrics. Three new Alertmanager rules: `BreakGlassAccountMissing`, `BreakGlassKitVerificationStale` (100d), `BreakGlassKitVerificationCritical` (180d), plus `BreakGlassVerifyScriptNotRunning`. New `docs/OFFLINE-KIT-TEMPLATE.md` centralises the kit's contents and rotation cadence in one copyable template. RUNBOOK Appendix D extended: §D.6 (account doesn't exist at all), §D.7 (TOTP secret rotation), §D.8 (manual audit-log query). RUNBOOK §7 gained a post-recovery line clarifying that the break-glass account survives a normal restore. |
| 2.5 | 2026-05-15 | Claude Code | New §5.3.4 "Access Scoping (Who Can Use SSO)" documents the layered controls — Assignment Required (must-do), `gitlab-users` security group (recommended pattern), Conditional Access (premium tier with explicit licensing caveat — NOT in M365 Business Basic/Standard), `omniauth_block_auto_created_users` (defence-in-depth, recommended off at our scale due to friction). Decision table per control + costs + scale-appropriate recommendation. DEPLOY.md §5a expanded with the specific Entra admin-centre clicks: create Enterprise App, create `gitlab-users` group with self added first (sequencing safety), flip Assignment Required, assign group, optional Conditional Access policy for MFA, verification that a non-assigned user is rejected at Entra. |
| 2.6 | 2026-05-15 | Claude Code | **Project-wide refactor.** Fixes per security-review sweep: corrected §1.3 cost (70 → 63 EUR), added "Phase 4 prerequisite" disclaimers to monitoring/alerts.yml entries whose metric sources don't yet exist, reframed README's monitoring section as target state rather than current state. New scripts close the implementation gap: `scripts/borg-check.sh` (weekly Borg integrity → `gitlab_backup_integrity` metric) and `scripts/restore-test.sh` (weekly ephemeral-CX21 restore drill with cost-safety trap → `gitlab_restore_test_success` metric). New `systemd/` directory with timer+service units for all scheduled jobs (hourly backup, weekly borg-check, weekly restore-test, monthly break-glass verify) reading credentials via `LoadCredentialEncrypted=`. New `external-observer/` directory with `setup-observer.sh` for provisioning the dead-man's-switch on a non-Hetzner VPS (blackbox_exporter + Watchdog webhook receiver + Caddy TLS). Security hygiene: new `SECURITY.md` (responsible disclosure), gitleaks added to CI (was pre-commit-only — bypassable), unused `tls`/`local` provider pins removed from `terraform/versions.tf`, T2.1 seed validator now refuses Hetzner endpoints for the S3 immutable tier. Doc consolidation: ToC expanded with subsections, DEPLOY.md §9 shortened to a pointer at `OFFLINE-KIT-TEMPLATE.md`, status terminology normalised in TODO.md, CLAUDE.md section anchors prefixed with `§`. Closed T1.5 (partial), T2.1, T2.6, T2.8b, T3.6, T3.7. New TODOs T4.1-T4.3 opened. |
| 2.7 | 2026-05-18 | Claude Code | **Storage Box migration: Hetzner Robot → Hetzner Cloud Console + Terraform.** As of hcloud provider v1.63.0 (May 2026), Storage Boxes and their sub-accounts are managed in the unified Cloud Console with Terraform support. New `terraform/storage_box.tf` provisions both the primary box and the append-only sub-account, with `lifecycle { prevent_destroy = true }` on both and `ignore_changes = [ssh_keys]` on the primary (the API forces replace on key updates, which would wipe the repo). Append-only enforcement remains at the SSH command layer (forced `borg serve --append-only --restrict-to-repository` in `authorized_keys`) because the Hetzner sub-account API only offers `readonly` or full-rw — neither matches the append-only requirement. `scripts/setup-borg-backup.sh` and `scripts/setup-borg-append-only.sh` shrunk to ~150 lines each: no more Robot UI prompts; they SFTP the authorized_keys file using sshpass + the sub-account's initial password (passed via env var, NOT persisted on the server). DEPLOY.md §0 drops the Robot prerequisite; §1 repurposed to "generate offline credentials" (the OFFLINE SSH keypair + the two passwords); §3 gains a "paste-back" step where the operator copies `terraform output storage_box_post_apply` values into `seed.yaml.backup.storage_box.host/user`; §6 documents the env-var-supplied password and immediate post-run rotation. Appendix C.8 rotation matrix split into five Storage-Box-specific rows (was two) and adds a note that the `hcloud_token` blast radius grew because one token now controls both the cloud server and the backups. SECURITY-ASSESSMENT.md §2.1 threat-model updated: "Storage Box credential theft" and "Hetzner account compromise" are now closer to the same row. Closes the pre-deploy gap that the previous workflow opened: no procurement step is now unmanaged by IaC. Also landed in this commit: pre-deploy security fixes T1.4 (required `trusted_ssh_ips`, fail-loud), T1.6 (vendored `packages.gitlab.com` install script at `scripts/vendor/install-gitlab-repo.sh` with CI checksum verification), T2.3 (`sshd` fail2ban jail in cloud-init). |
| 2.8 | 2026-05-21 | Claude Code | **Remote Terraform state backend (closes security review T1.2).** State now lives in Hetzner Object Storage (S3-compatible) instead of `terraform.tfstate` on the operator laptop. New `terraform/backend.tf` declares an `s3` partial-config backend with the static "this is a non-AWS S3 implementation" flags (`skip_credentials_validation`, `use_path_style`, `skip_s3_checksum`, etc.) plus `encrypt = true` for server-side encryption at rest. Operator-specific values (bucket name, region, endpoint, S3 credentials) flow from a new `infrastructure.terraform_state` section in `seed.template.yaml` through `seed_bootstrap.py --target tf-backend` into a gitignored `terraform/backend.tfbackend`, consumed at `terraform init -backend-config=`. Bucket creation and S3-credential minting are Console-only — the Hetzner Cloud API does not expose either (probed and confirmed). DEPLOY.md §0 documents both Console click-paths; §2/§2a list the new seed fields and secret-location row; §3 updates the init command. Phase 2 of T1.2 (offline-kit snapshot of state) lands as `make tf-snapshot`: pulls current state via `terraform state pull`, writes a dated file the operator copies onto the FDE USBs and shreds locally. Also new: `make tf-init-reconfigure` for the S3-key rotation case. Schema-side validation in `seed_schema.py` (`TerraformStateConfig` model): bucket must match S3 naming rules (3-63 chars, lowercase alphanumeric + `.`/`-`, start/end alphanumeric); endpoint must be https://; credentials cannot be empty strings. Hetzner S3 credentials are PROJECT-scoped (not bucket-scoped) — DEPLOY.md §2a documents this caveat and recommends naming the credentials clearly at generation time. |
