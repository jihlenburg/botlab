# Security Assessment & Disaster Recovery Analysis

**Document Version**: 1.1
**Date**: 2026-02-02
**Classification**: Internal - Technical Review

---

## Related Documents

| Document | Relationship |
|----------|--------------|
| [DESIGN.md](DESIGN.md) | Master design document - implements recommendations from this assessment |
| [INTEGRATOR-BOT-PLAN.md](INTEGRATOR-BOT-PLAN.md) | Integrator Bot implements security monitoring and DR automation |

**Implementation Status**: Recommendations from this assessment are incorporated into:
- DESIGN.md Section 6.3.3 (3-2-1 Backup Strategy)
- DESIGN.md Section 9 (Ransomware Protection)
- INTEGRATOR-BOT-PLAN.md Sections 6.4-6.6 (Security MCP Servers)

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Threat Model](#2-threat-model)
3. [Ransomware Protection Analysis](#3-ransomware-protection-analysis)
4. [Disaster Recovery Edge Cases](#4-disaster-recovery-edge-cases)
5. [Security Controls Assessment](#5-security-controls-assessment)
6. [Recommendations](#6-recommendations)
7. [Risk Matrix](#7-risk-matrix)

---

## 1. Executive Summary

This document provides a comprehensive security assessment of the ACME Corp GitLab infrastructure, with particular focus on:
- Ransomware attack vectors and mitigations
- Disaster recovery completeness for various failure scenarios
- Security control effectiveness

### Key Findings

| Area | Current State | Risk Level | Action Required | Implementation Status |
|------|---------------|------------|-----------------|----------------------|
| Ransomware Protection | Improved | **MEDIUM** | Verify append-only setup in prod | **Implemented** — append-only Borg script, S3 immutable backup script |
| Backup Isolation | Improved | **MEDIUM** | Deploy S3 immutable bucket | **Implemented** — `scripts/backup-to-s3.sh` with Object Lock |
| DR Coverage | Good | **MEDIUM** | Address identified edge cases | In progress |
| Access Control | Good | **LOW** | Minor improvements | Unchanged |
| Network Security | Good | **LOW** | Already implemented | Unchanged |

---

## 2. Threat Model

### 2.1 Attack Vectors

| Vector | Likelihood | Impact | Current Mitigation |
|--------|------------|--------|-------------------|
| **Ransomware via compromised credentials** | Medium | Critical | 2FA required, SSO |
| **Ransomware via supply chain (GitLab vulnerability)** | Low | Critical | Regular updates, monitoring |
| **Ransomware via Admin Bot compromise** | Low | Critical | Restricted SSH commands |
| **Insider threat (malicious admin)** | Low | Critical | Audit logging, separation of duties |
| **Storage Box credential theft** | Low | Critical | Key-based auth, but keys on server |
| **Hetzner account compromise** | Very Low | Critical | 2FA, but single point of failure |

### 2.2 Attack Scenarios

#### Scenario A: Ransomware Encrypts GitLab Server
- **Attack**: Attacker gains access to GitLab server, encrypts all data
- **Current Protection**: Backups exist on Storage Box
- **Gap**: If attacker has prolonged access, they may:
  1. Delete/encrypt Borg backups (have the passphrase from server)
  2. Wait for old backups to be pruned before attacking
  3. Compromise admin bot and delete backups via automation

#### Scenario B: Ransomware via Admin Bot
- **Attack**: Attacker compromises Admin Bot, pivots to GitLab
- **Current Protection**: SSH command restrictions, separate server
- **Gap**: Admin Bot has Borg passphrase and SSH access to GitLab

#### Scenario C: Supply Chain Attack
- **Attack**: Malicious GitLab update or dependency
- **Current Protection**: None specific
- **Gap**: Auto-updates could introduce compromised code

---

## 3. Ransomware Protection Analysis

### 3.1 Current Backup Architecture

```
GitLab Server                Admin Bot              Storage Box
     │                           │                       │
     │ hourly backup             │                       │
     ├──────────────────────────►│                       │
     │                           │ borg create           │
     │                           ├──────────────────────►│
     │                           │                       │
     │                           │ borg prune            │
     │                           ├──────────────────────►│
     │                           │                       │

PROBLEM: If GitLab server is compromised, attacker has:
- /etc/gitlab-backup.conf (Borg passphrase)
- SSH key to Storage Box
- Ability to delete ALL backups including offsite
```

### 3.2 Ransomware Protection Gaps

| Gap | Severity | Description |
|-----|----------|-------------|
| **No immutable backups** | CRITICAL | Borg repository is mutable; attacker can delete all backups |
| **Passphrase on server** | HIGH | Borg passphrase stored in /etc/gitlab-backup.conf |
| **No air-gapped backup** | HIGH | All backups accessible via network |
| **No backup integrity monitoring** | MEDIUM | Would not detect tampering until restore |
| **Retention enables attack timing** | MEDIUM | 30-day retention allows attacker to wait |

### 3.3 Recommended Ransomware Mitigations

#### 3.3.1 Implement Borg Append-Only Mode (Critical)

Storage Box can be configured for append-only access:

```bash
# On Storage Box, create sub-account with append-only
# Then modify backup script to use append-only connection
export BORG_REPO="ssh://uXXXXX-sub1@uXXXXX.your-storagebox.de:23/./gitlab-borg"

# Separate admin key (for prune/delete) stored OFFLINE only
# Never on any server
```

**Implementation**: Create two Storage Box sub-accounts:
1. `backup-write`: Can create archives, cannot delete (used by automation)
2. `backup-admin`: Full access (offline key for emergencies only)

#### 3.3.2 Implement Offline Backup Verification (High)

Add a quarterly offline backup:
1. Download backup to air-gapped machine
2. Verify integrity
3. Store on offline media (USB/external drive)
4. Keep in physically separate location

#### 3.3.3 Add Immutable Object Storage Backup (High)

Supplement Borg with immutable object storage:

```bash
# Add S3 backup with Object Lock (WORM)
# Hetzner doesn't support Object Lock, but alternatives:
# - Backblaze B2 (S3-compatible with Object Lock)
# - AWS S3 with Object Lock
# - Wasabi with Object Lock

# Weekly backup to immutable storage
0 3 * * 0 /usr/local/bin/backup-to-immutable.sh
```

#### 3.3.4 Remove Passphrase from Server (Medium)

Instead of storing Borg passphrase in config file:

```bash
# Option 1: Use environment variable from external secret manager
# Requires: External secrets management (HashiCorp Vault, etc.)

# Option 2: Use key-based encryption (more complex setup)
borg init --encryption=keyfile-blake2 $BORG_REPO
# Keep keyfile offline, only upload for restores

# Option 3: Admin Bot fetches passphrase from secure API at backup time
# Adds dependency but removes passphrase from disk
```

---

## 4. Disaster Recovery Edge Cases

### 4.1 Failure Scenarios Analysis

| Scenario | Current Plan Handles? | Gap | Mitigation |
|----------|----------------------|-----|------------|
| GitLab server hardware failure | ✅ Yes | None | Terraform + restore |
| GitLab server OS corruption | ✅ Yes | None | Terraform + restore |
| GitLab data corruption | ✅ Yes | None | Restore from backup |
| Admin Bot failure | ✅ Partial | No manual monitoring | Document manual procedures |
| Storage Box failure | ❌ **No** | Single backup destination | Add secondary backup target |
| Storage Box data corruption | ❌ **No** | No redundancy | Add secondary backup target |
| Hetzner region outage | ❌ **No** | All resources in Falkenstein | Multi-region backup |
| Hetzner account lockout | ❌ **No** | Cannot provision new servers | Offline Terraform state, documented manual recovery |
| Both servers compromised simultaneously | ✅ Partial | If backups deleted, total loss | Immutable backups |
| Borg repository corruption | ✅ Partial | Single Borg repo | Regular integrity checks |
| DNS provider failure | ⚠️ Partial | Can update, but if provider down... | Secondary DNS |
| Azure AD outage (SSO) | ⚠️ Partial | Users cannot login | Ensure local admin account exists |
| Object storage failure | ⚠️ Partial | LFS/artifacts unavailable | Objects not backed up |

### 4.2 Critical Edge Cases Requiring Attention

#### Edge Case 1: Storage Box Failure/Corruption

**Current State**: Single backup destination
**Risk**: Total data loss if Storage Box fails before detection

**Recommendation**:
```
Add secondary backup target:
- Option A: Second Hetzner Storage Box in different datacenter
- Option B: Backblaze B2 (cheap, S3-compatible)
- Option C: AWS Glacier Deep Archive (cheapest for cold storage)

Implement 3-2-1 backup rule:
- 3 copies of data
- 2 different storage types
- 1 offsite/offline
```

#### Edge Case 2: Hetzner Account Compromise/Lockout

**Current State**: All infrastructure in single Hetzner account
**Risk**: If Hetzner account is compromised or locked, cannot:
- Access servers
- Access Storage Box
- Provision new infrastructure

**Recommendation**:
```
1. Store Terraform state externally (S3, Terraform Cloud)
2. Document manual recovery without Hetzner API
3. Consider backup Hetzner account (separate credentials)
4. Keep offline copy of:
   - Terraform configuration
   - SSH keys
   - Borg passphrase
   - GitLab gitlab-secrets.json
```

#### Edge Case 3: Ransomware with Delayed Activation

**Current State**: 30-day backup retention
**Risk**: Attacker plants malware, waits 30+ days, then activates
- All backups would contain the dormant malware
- Clean restore impossible

**Recommendation**:
```
1. Extend retention for monthly backups (6-12 months)
2. Keep quarterly offline backups (USB/external drive)
3. Implement backup integrity monitoring:
   - Hash validation
   - Size anomaly detection
   - Content sampling
```

#### Edge Case 4: Object Storage Data Loss

**Current State**: LFS/artifacts in Hetzner Object Storage, not backed up
**Risk**: Object storage failure = permanent loss of large files

**Recommendation**:
```
1. Enable Object Storage versioning (provides some protection)
2. Add replication to secondary region/provider for critical buckets
3. Consider periodic sync to Storage Box for LFS bucket

# Example sync script
rclone sync hetzner:gitlab-acme-lfs backup:gitlab-lfs-backup --checksum
```

#### Edge Case 5: Simultaneous Multi-Component Failure

**Current State**: Assumed single component failures
**Risk**: Fire/flood at Falkenstein datacenter affects all components

**Recommendation**:
```
Geographic diversification:
1. Backups to different Hetzner region (Nuremberg or Helsinki)
2. Or: External provider (Backblaze, AWS)
3. Monthly offline backup stored physically elsewhere
```

### 4.3 Recovery Procedure Gaps

| Gap | Impact | Recommendation |
|-----|--------|----------------|
| No documented manual recovery | Can't recover if Admin Bot unavailable | Write manual runbook |
| Recovery requires internet | Can't recover in network isolation | Document offline recovery |
| Terraform state on local machine | Can't recover if state lost | Use remote state backend |
| SSL certificates regenerated | Clients may have certificate pinning | Document cert migration |
| Azure AD may need reconfiguration | SSO may break after recovery | Document SSO recovery steps |

---

## 5. Security Controls Assessment

### 5.1 Authentication & Access Control

| Control | Status | Notes |
|---------|--------|-------|
| 2FA for GitLab | ✅ Enforced | 7-day grace period |
| SSO via Azure AD | ✅ Configured | SAML 2.0 |
| SSH key-only access | ✅ Enforced | No password auth |
| Admin Bot restricted commands | ✅ Implemented | Wrapper script |
| API token rotation | ⚠️ Manual | Should automate |

### 5.2 Network Security

| Control | Status | Notes |
|---------|--------|-------|
| Private network isolation | ✅ Configured | 10.0.0.0/16 |
| Firewall rules | ✅ Implemented | Default deny |
| TLS 1.2+ only | ✅ Configured | In gitlab.rb |
| Rate limiting | ✅ Configured | rack_attack |
| DDoS protection | ⚠️ Basic | Hetzner's default only |

### 5.3 Audit & Monitoring

| Control | Status | Notes |
|---------|--------|-------|
| GitLab audit events | ✅ Enabled | Default CE logging |
| SSH access logging | ✅ Enabled | /var/log/auth.log |
| Backup success monitoring | ✅ Implemented | Admin Bot |
| Intrusion detection | ❌ Not implemented | Consider fail2ban |
| File integrity monitoring | ❌ Not implemented | Consider AIDE |

---

## 6. Recommendations

### 6.1 Critical (Implement Immediately)

1. **Implement append-only Borg backup** — **IMPLEMENTED**
   - Prevents ransomware from deleting backups
   - Script: `scripts/setup-borg-append-only.sh`
   - Creates restricted SSH key (append-only) and separate admin key (stored offline)

2. **Add secondary backup destination** — **IMPLEMENTED**
   - Script: `scripts/backup-to-s3.sh` (weekly S3 upload with Object Lock)
   - Supports Backblaze B2, AWS S3, Wasabi

3. **Create offline backup recovery kit**
   - Store offline: Borg passphrase, SSH keys, Terraform config
   - Effort: 2 hours
   - Cost: $0

### 6.2 High Priority (Implement Within 30 Days)

4. **Extend backup retention** — **IMPLEMENTED**
   - Monthly backups kept for 12 months (changed from 6)
   - Updated in: `seed_schema.py`, `setup-borg-backup.sh`, `seed.example.yaml`

5. **Implement backup integrity monitoring** — **IMPLEMENTED**
   - `BackupMonitor.verify_integrity()` runs `borg check --repository-only`
   - Prometheus gauge `gitlab_backup_integrity` (1=ok, 0=fail)
   - Designed for weekly scheduled invocation

6. **Document manual recovery procedures**
   - Enable recovery without Admin Bot
   - Effort: 4 hours
   - Cost: $0

### 6.3 Medium Priority (Implement Within 90 Days)

7. **Add immutable backup tier** — **IMPLEMENTED**
   - Script: `scripts/backup-to-s3.sh` (weekly, Object Lock COMPLIANCE mode)
   - Seed config: `backup.s3` section in `seed.example.yaml`
   - Config generator: `seed_bootstrap.py --target s3-conf`

8. **Implement file integrity monitoring**
   - AIDE or similar on GitLab server
   - Effort: 4 hours
   - Cost: $0

9. **Geographic backup diversification**
   - Replicate backups to different region
   - Effort: 4-8 hours
   - Cost: Varies

### 6.4 Lower Priority (Implement Within 6 Months)

10. **External secrets management**
    - HashiCorp Vault or similar
    - Effort: 16+ hours
    - Cost: Varies

11. **Enhanced monitoring and SIEM**
    - Centralized logging and alerting
    - Effort: 16+ hours
    - Cost: Varies

---

## 7. Risk Matrix

### 7.1 Current Risk Profile

```
                  Low Impact    Medium Impact    High Impact    Critical Impact
               ┌─────────────┬───────────────┬──────────────┬─────────────────┐
Likely         │             │               │              │                 │
               ├─────────────┼───────────────┼──────────────┼─────────────────┤
Possible       │             │ Object Store  │ Backup       │                 │
               │             │ failure       │ deletion     │                 │
               ├─────────────┼───────────────┼──────────────┼─────────────────┤
Unlikely       │             │               │ Storage Box  │ Ransomware      │
               │             │               │ failure      │ (total loss)    │
               ├─────────────┼───────────────┼──────────────┼─────────────────┤
Rare           │             │               │ Region       │ Hetzner account │
               │             │               │ outage       │ compromise      │
               └─────────────┴───────────────┴──────────────┴─────────────────┘
```

### 7.2 Target Risk Profile (After Recommendations)

```
                  Low Impact    Medium Impact    High Impact    Critical Impact
               ┌─────────────┬───────────────┬──────────────┬─────────────────┐
Likely         │             │               │              │                 │
               ├─────────────┼───────────────┼──────────────┼─────────────────┤
Possible       │ Object Store│               │              │                 │
               │ (replicated)│               │              │                 │
               ├─────────────┼───────────────┼──────────────┼─────────────────┤
Unlikely       │             │ Storage Box   │              │ Ransomware      │
               │             │ (has backup)  │              │ (immutable bkp) │
               ├─────────────┼───────────────┼──────────────┼─────────────────┤
Rare           │             │ Region outage │              │ Account         │
               │             │ (multi-region)│              │ compromise      │
               └─────────────┴───────────────┴──────────────┴─────────────────┘
```

---

## Appendix A: Borg Append-Only Configuration

```bash
# On Storage Box, create restricted sub-account via Hetzner Robot
# Name: backup-write (or similar)
# Permissions: Read, Write (no Delete)

# Update backup script to use restricted account
export BORG_REPO="ssh://uXXXXX-sub1@uXXXXX.your-storagebox.de:23/./gitlab-borg"

# Pruning requires separate, offline-stored credentials
# Only run prune manually or from air-gapped machine with full credentials
```

## Appendix B: 3-2-1 Backup Implementation

```
Primary: GitLab local backups (hourly, 24h retention)
    └── Media: Local SSD
    └── Location: GitLab server

Secondary: Borg to Storage Box (hourly, 30 day retention)
    └── Media: HDD array
    └── Location: Hetzner Falkenstein (different DC)

Tertiary: Immutable S3 (weekly, 12 month retention)
    └── Media: Cloud object storage with WORM
    └── Location: Different provider/region

Quaternary: Offline backup (quarterly)
    └── Media: USB/external drive
    └── Location: Physical office safe or bank vault
```

## Appendix C: Emergency Recovery Checklist

If all online systems are compromised:

1. [ ] Do NOT connect to compromised systems
2. [ ] Retrieve offline recovery kit from secure storage
3. [ ] Provision new Hetzner servers using offline Terraform
4. [ ] Restore from immutable backup (S3 with Object Lock)
5. [ ] If no immutable backup, use offline backup
6. [ ] Change ALL credentials before bringing online
7. [ ] Perform forensic analysis of compromised systems

---

**Document End**
