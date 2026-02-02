# Integrator Bot Architecture Plan

## Using Claude Code CLI as the Bot Foundation

**Status**: Planning
**Date**: 2026-02-02
**Version**: 1.1
**Vision**: Transform the Admin Bot into an extensible "Integrator Bot" powered by Claude Code CLI

---

## Related Documents

| Document | Relationship |
|----------|--------------|
| [DESIGN.md](DESIGN.md) | Master design document - Section 7.8 summarizes policy system |
| [SECURITY-ASSESSMENT.md](SECURITY-ASSESSMENT.md) | Security requirements implemented in Sections 6.4-6.6 |

---

**Security Integration**: This plan incorporates findings from `SECURITY-ASSESSMENT.md`:
- Ransomware protection and detection
- Multi-destination backup verification
- Immutable backup management
- Disaster recovery automation
- Security anomaly detection

**Multi-Repository Policy System**: Per-project `.gitlab-bot.yml` files enable:
- Distributed policy configuration across repositories
- Project-specific monitoring rules and automation
- Context-aware AI decisions based on project documentation
- Scalable management of diverse project requirements

---

## 1. Executive Summary

### The Question
Can we use Claude Code CLI instead of a custom Python bot with direct Anthropic API calls?

### The Answer
**Yes, and it's the better long-term architecture.** Here's why:

| Aspect | Current Design (Python + API) | Claude Code CLI Design |
|--------|-------------------------------|------------------------|
| Tool implementation | Custom SSH, API clients | Built-in + MCP servers |
| Extensibility | Modify Python code | Add MCP servers |
| Intelligence | Single API call analysis | Full conversation with tool use |
| Maintenance | High (custom code) | Low (MCP specs + prompts) |
| Future integrations | Major code changes | New MCP server |
| Interactive mode | Not supported | Native |
| Agent orchestration | Custom implementation | Agent SDK |

---

## 2. Architectural Vision

### Current Admin Bot (What We Built)
```
┌────────────────────────────────────────────────────────────┐
│                    Admin Bot (Python)                       │
├────────────────────────────────────────────────────────────┤
│                                                             │
│   ┌─────────────┐  ┌─────────────┐  ┌─────────────┐       │
│   │  Scheduler  │  │  Monitors   │  │   Alerting  │       │
│   │ (APScheduler)│  │   (SSH)    │  │   (SMTP)    │       │
│   └──────┬──────┘  └──────┬──────┘  └──────┬──────┘       │
│          │                │                │               │
│          └────────────────┼────────────────┘               │
│                           ▼                                 │
│                  ┌────────────────┐                        │
│                  │  Claude API    │                        │
│                  │  (Analysis)    │                        │
│                  └────────────────┘                        │
│                                                             │
│   Problem: Claude only analyzes, doesn't act               │
│   Problem: Every new integration = new Python code         │
│                                                             │
└────────────────────────────────────────────────────────────┘
```

### Future Integrator Bot (Claude Code Core)
```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           Integrator Bot                                     │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│   ┌──────────────────────────────────────────────────────────────────────┐  │
│   │                       Claude Code CLI                                 │  │
│   │                       (Headless Daemon)                               │  │
│   │                                                                       │  │
│   │   "I can read files, run commands, use tools, spawn agents,          │  │
│   │    detect security anomalies, and orchestrate disaster recovery."    │  │
│   │                                                                       │  │
│   └──────────────────────────────────────────────────────────────────────┘  │
│          │           │           │           │           │           │       │
│   ┌──────▼─────┐ ┌───▼────┐ ┌────▼────┐ ┌────▼────┐ ┌────▼────┐ ┌────▼────┐│
│   │MCP: GitLab │ │MCP:    │ │MCP:     │ │MCP:     │ │MCP:     │ │MCP:     ││
│   │            │ │Hetzner │ │Borg     │ │Alerting │ │Metrics  │ │Security ││
│   └────────────┘ └────────┘ └─────────┘ └─────────┘ └─────────┘ └─────────┘│
│                                                                              │
│   ┌──────────────────────────────────────────────────────────────────────┐  │
│   │                    Security & DR Layer                                │  │
│   │  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐             │  │
│   │  │ Immutable│  │  Multi-  │  │ Anomaly  │  │    DR    │             │  │
│   │  │ Backup   │  │  Dest    │  │Detection │  │ Recovery │             │  │
│   │  │ (S3 WORM)│  │ Verify   │  │          │  │ Orchestr │             │  │
│   │  └──────────┘  └──────────┘  └──────────┘  └──────────┘             │  │
│   └──────────────────────────────────────────────────────────────────────┘  │
│                                                                              │
│   ┌──────────────────────────────────────────────────────────────────────┐  │
│   │                    Future Integrations                                │  │
│   │  ┌────────┐  ┌────────┐  ┌────────┐  ┌────────┐  ┌────────┐         │  │
│   │  │  Jira  │  │ Slack  │  │Conflnce│  │  K8s   │  │ GitHub │         │  │
│   │  └────────┘  └────────┘  └────────┘  └────────┘  └────────┘         │  │
│   └──────────────────────────────────────────────────────────────────────┘  │
│                                                                              │
│   Orchestration: systemd + cron invoke Claude Code with prompts             │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Why Claude Code CLI is Superior

### 3.1 Built-in Tool Use

Claude Code already knows how to:
- **Bash**: Run commands, check output, handle errors
- **Read/Write/Edit**: File operations without custom code
- **Glob/Grep**: Search codebase efficiently
- **WebFetch**: Check external APIs and services
- **Task/Agent**: Spawn sub-agents for parallel work

We don't need to implement SSH clients, file parsers, or command execution. Claude Code does it natively.

### 3.2 MCP (Model Context Protocol) Extensibility

MCP is Anthropic's standard for giving Claude access to external tools. Instead of:
```python
# Old way: Custom Python for each integration
class GitLabClient:
    def list_projects(self): ...
    def get_merge_requests(self): ...
    def trigger_pipeline(self): ...
```

We write:
```json
// New way: MCP server specification
{
  "name": "gitlab",
  "tools": [
    {"name": "list_projects", "description": "List GitLab projects", ...},
    {"name": "get_merge_requests", "description": "Get open MRs", ...},
    {"name": "trigger_pipeline", "description": "Trigger CI pipeline", ...}
  ]
}
```

Benefits:
- **Standardized**: Same pattern for all integrations
- **Discoverable**: Claude can see what tools are available
- **Composable**: Claude can use multiple MCP servers together
- **Shareable**: MCP servers can be open-sourced and reused

### 3.3 Conversation Memory and Context

Claude Code maintains conversation context. This means:
- "Yesterday you mentioned disk was trending up. What's the status now?"
- "Last week's backup test failed. Did this week's pass?"
- "There's been a pattern of high memory on Mondays. What do you think?"

The bot develops *situational awareness* over time.

### 3.4 Natural Language Interface

With Claude Code, admins can interact naturally:
```
Admin: "What's the current system status?"
Bot: [Uses MCP tools to check health, resources, backups]
     "GitLab is healthy. Disk at 67%. Last backup 45 minutes ago.
      I noticed CPU spiked yesterday around 14:00 - looks like a large CI job."

Admin: "Can you check if any MRs have been waiting for review more than a week?"
Bot: [Uses GitLab MCP to query MRs]
     "Found 3 MRs open more than 7 days: MR-234, MR-256, MR-271.
      Should I notify the authors?"
```

### 3.5 Agent SDK for Complex Orchestration

When tasks require multiple steps across systems, the Agent SDK provides:
- Sub-agent spawning for parallel work
- State management across steps
- Error handling and recovery
- Human-in-the-loop approval gates

Example: "Deploy the latest release"
```
Main Agent
├── Spawn: Run all tests
├── Spawn: Build Docker image
├── Wait for above
├── Spawn: Deploy to staging
├── Ask human: "Staging looks good. Proceed to production?"
├── Spawn: Deploy to production
├── Spawn: Notify Slack channel
└── Done
```

---

## 4. Implementation Architecture

### 4.1 Component Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                          Integrator Bot                              │
│                                                                      │
│  ┌────────────────────────────────────────────────────────────────┐ │
│  │                    Orchestration Layer                         │ │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐ │ │
│  │  │   Scheduler  │  │   Triggers   │  │   State Manager      │ │ │
│  │  │ (cron/systemd)│  │  (webhooks) │  │ (SQLite/Redis)       │ │ │
│  │  └──────┬───────┘  └──────┬───────┘  └──────────┬───────────┘ │ │
│  │         │                 │                      │             │ │
│  │         └─────────────────┼──────────────────────┘             │ │
│  │                           ▼                                    │ │
│  │  ┌────────────────────────────────────────────────────────┐   │ │
│  │  │                Claude Code CLI Runner                   │   │ │
│  │  │                                                         │   │ │
│  │  │  Invokes Claude Code with:                             │   │ │
│  │  │  - System prompt (role, capabilities, context)         │   │ │
│  │  │  - Current state (from State Manager)                  │   │ │
│  │  │  - Task prompt (what to do now)                        │   │ │
│  │  │                                                         │   │ │
│  │  │  Collects:                                              │   │ │
│  │  │  - Actions taken                                        │   │ │
│  │  │  - Observations                                         │   │ │
│  │  │  - Recommendations                                      │   │ │
│  │  │                                                         │   │ │
│  │  └─────────────────────────┬──────────────────────────────┘   │ │
│  │                            │                                   │ │
│  └────────────────────────────┼───────────────────────────────────┘ │
│                               ▼                                      │
│  ┌────────────────────────────────────────────────────────────────┐ │
│  │                    Claude Code CLI                              │ │
│  │                    (with MCP servers)                           │ │
│  │                                                                 │ │
│  │  Built-in: Bash, Read, Write, Edit, Glob, Grep, WebFetch       │ │
│  │                                                                 │ │
│  │  MCP Servers (Core):                                            │ │
│  │  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐  │ │
│  │  │ GitLab  │ │ Hetzner │ │  Borg   │ │ Alerts  │ │ Metrics │  │ │
│  │  └─────────┘ └─────────┘ └─────────┘ └─────────┘ └─────────┘  │ │
│  │                                                                 │ │
│  │  MCP Servers (Security & DR):                                   │ │
│  │  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐               │ │
│  │  │Security │ │Immutable│ │   DR    │ │ Audit   │               │ │
│  │  │ Scan    │ │ Backup  │ │Recovery │ │  Log    │               │ │
│  │  └─────────┘ └─────────┘ └─────────┘ └─────────┘               │ │
│  │                                                                 │ │
│  │  Future Integrations:                                           │ │
│  │  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐  │ │
│  │  │  Jira   │ │  Slack  │ │Confluenc│ │   K8s   │ │ GitHub  │  │ │
│  │  └─────────┘ └─────────┘ └─────────┘ └─────────┘ └─────────┘  │ │
│  │                                                                 │ │
│  └────────────────────────────────────────────────────────────────┘ │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

### 4.2 MCP Server Design

Each MCP server is a small service that:
1. Implements the MCP protocol (JSON-RPC over stdio)
2. Exposes tools for a specific domain
3. Handles authentication and connection management

Example: `mcp-gitlab`
```
mcp-gitlab/
├── package.json          # or pyproject.toml
├── src/
│   ├── index.ts          # MCP server entry
│   ├── tools/
│   │   ├── projects.ts   # list_projects, get_project, etc.
│   │   ├── merge_requests.ts
│   │   ├── pipelines.ts
│   │   ├── users.ts
│   │   └── system.ts     # health, version, etc.
│   └── auth.ts           # GitLab API authentication
└── README.md
```

### 4.3 Runner Design

The runner is a thin wrapper that:
1. Loads current state from database
2. Constructs the prompt for Claude Code
3. Invokes `claude` CLI in headless mode
4. Parses output and updates state
5. Handles any follow-up actions

```python
# Simplified runner logic
async def run_check(check_type: str):
    # Load state
    state = await state_manager.get_current_state()

    # Construct prompt
    prompt = f"""
You are the ACME Corp Integrator Bot.

Current state:
{json.dumps(state, indent=2)}

Task: Perform {check_type} check.

1. Use your tools to gather current information
2. Compare to previous state
3. Identify any issues or anomalies
4. Take appropriate actions (within your authority)
5. Report findings

Remember:
- Auto-execute safe actions (cleanup, reports)
- Request approval for risky actions (restarts, restores)
- Always update the state with your observations
"""

    # Run Claude Code
    result = await run_claude_code(
        prompt=prompt,
        mcp_servers=["gitlab", "hetzner", "borg", "alerts", "metrics"],
        headless=True,
    )

    # Update state
    await state_manager.update_from_result(result)

    return result
```

### 4.4 State Management

Persistent state enables:
- **Alert deduplication**: Don't spam about the same issue
- **Trend analysis**: Compare to historical data
- **Context continuity**: Remember past conversations
- **Action tracking**: Log what was done and when

```sql
-- State database schema
CREATE TABLE system_state (
    id INTEGER PRIMARY KEY,
    timestamp DATETIME,
    component TEXT,  -- 'gitlab', 'resources', 'backup', etc.
    state_json TEXT,
    UNIQUE(component)
);

CREATE TABLE observations (
    id INTEGER PRIMARY KEY,
    timestamp DATETIME,
    type TEXT,  -- 'metric', 'alert', 'action', 'recommendation'
    severity TEXT,
    message TEXT,
    details_json TEXT
);

CREATE TABLE actions_log (
    id INTEGER PRIMARY KEY,
    timestamp DATETIME,
    action_type TEXT,
    description TEXT,
    result TEXT,
    initiated_by TEXT  -- 'auto', 'human', 'scheduled'
);

CREATE TABLE conversation_summaries (
    id INTEGER PRIMARY KEY,
    date DATE,
    summary TEXT,
    key_observations TEXT,
    pending_items TEXT
);

-- Security & DR tables
CREATE TABLE backup_destinations (
    id INTEGER PRIMARY KEY,
    name TEXT UNIQUE,  -- 'borg-primary', 'borg-secondary', 's3-immutable'
    type TEXT,         -- 'borg', 's3-worm', 'local'
    last_verified DATETIME,
    last_backup DATETIME,
    is_immutable BOOLEAN,
    config_json TEXT
);

CREATE TABLE backup_verification_log (
    id INTEGER PRIMARY KEY,
    timestamp DATETIME,
    destination TEXT,
    archive_name TEXT,
    verification_type TEXT,  -- 'integrity', 'restore-test', 'hash-check'
    success BOOLEAN,
    details_json TEXT
);

CREATE TABLE security_events (
    id INTEGER PRIMARY KEY,
    timestamp DATETIME,
    event_type TEXT,  -- 'anomaly', 'threat', 'policy_violation', 'access_denied'
    severity TEXT,    -- 'critical', 'high', 'medium', 'low'
    source TEXT,      -- 'gitlab', 'hetzner', 'backup', 'network'
    description TEXT,
    indicators_json TEXT,
    resolved BOOLEAN,
    resolution_notes TEXT
);

CREATE TABLE dr_recovery_state (
    id INTEGER PRIMARY KEY,
    initiated_at DATETIME,
    trigger_reason TEXT,
    current_step TEXT,
    completed_steps_json TEXT,
    approval_status TEXT,  -- 'pending', 'approved', 'denied'
    approved_by TEXT,
    completed_at DATETIME,
    result TEXT
);
```

---

## 5. Implementation Phases

### Phase 1: MCP Server Foundation (Weeks 1-2)

Create core MCP servers for existing functionality:

| MCP Server | Tools | Priority |
|------------|-------|----------|
| `mcp-gitlab` | health, projects, users, pipelines, merge_requests | High |
| `mcp-hetzner` | servers, volumes, networks, snapshots, provision | High |
| `mcp-borg` | list_archives, backup_status, verify, restore | High |
| `mcp-system` | disk_usage, memory, cpu, processes | High |
| `mcp-alerts` | send_email, send_webhook, get_history | Medium |

**Security MCP Servers** (from SECURITY-ASSESSMENT.md recommendations):

| MCP Server | Tools | Priority |
|------------|-------|----------|
| `mcp-security` | check_anomalies, verify_integrity, scan_auth_logs, detect_ransomware_indicators | High |
| `mcp-immutable-backup` | create_immutable, verify_immutable, list_immutable, check_retention | High |
| `mcp-dr-recovery` | initiate_recovery, check_status, approve_step, abort_recovery | High |
| `mcp-audit` | get_events, analyze_access, check_compliance | Medium |

**Deliverable**: Claude Code can access all current admin bot capabilities via MCP, including security monitoring.

### Phase 2: Claude Code Runner (Week 3)

Build the orchestration layer:

1. **Runner service**: Invokes Claude Code with prompts
2. **State manager**: SQLite database for persistence
3. **Scheduler**: Cron jobs for periodic checks
4. **Output parser**: Extracts actions/observations from Claude

**Deliverable**: Scheduled checks run automatically via Claude Code.

### Phase 3: Prompt Engineering (Week 4)

Develop effective prompts for different scenarios:

| Scenario | Prompt Focus |
|----------|--------------|
| Health check | Quick status, compare to baseline |
| Resource check | Trends, predictions, cleanup opportunities |
| Backup check | Verify success, test recommendation |
| Daily report | Summarize, highlight issues, recommend actions |
| Incident response | Diagnose, contain, recover, document |
| **Security scan** | Anomaly detection, threat indicators, access patterns |
| **Backup integrity** | Multi-destination verification, immutability check |
| **Ransomware detection** | Encryption patterns, mass file changes, suspicious processes |
| **DR readiness** | Backup freshness across all destinations, recovery path validation |

**Deliverable**: Reliable, consistent bot behavior across scenarios including security.

### Phase 4: Interactive Mode (Week 5)

Enable admin interaction:

1. **Chat interface**: Terminal or web UI for conversations
2. **Context loading**: Inject current state into conversations
3. **Action confirmation**: Human-in-the-loop for risky actions

**Deliverable**: Admins can chat with the bot for ad-hoc queries.

### Phase 5: Integrator Extensions (Future)

Add integrations as needed:

| Integration | MCP Server | Use Cases |
|-------------|------------|-----------|
| Jira | `mcp-jira` | Create tickets for issues, track incidents |
| Slack | `mcp-slack` | Notifications, interactive approvals |
| Confluence | `mcp-confluence` | Auto-document incidents, runbooks |
| GitHub | `mcp-github` | Cross-repo operations, actions |
| Kubernetes | `mcp-kubernetes` | Container orchestration |
| PagerDuty | `mcp-pagerduty` | On-call integration |

---

## 6. MCP Server Specifications

### 6.1 mcp-gitlab

```yaml
name: gitlab
description: GitLab API operations for ACME Corp instance

config:
  gitlab_url: ${GITLAB_URL}
  gitlab_token: ${GITLAB_TOKEN}

tools:
  # Health & Status
  - name: get_health
    description: Check GitLab health status
    returns: { status, version, services }

  - name: get_system_info
    description: Get GitLab system information
    returns: { version, projects_count, users_count, storage }

  # Projects
  - name: list_projects
    description: List GitLab projects
    parameters:
      - name: visibility
        type: string
        enum: [public, internal, private, all]
      - name: limit
        type: integer
        default: 50
    returns: [{ id, name, path, visibility, last_activity }]

  - name: get_project
    description: Get project details
    parameters:
      - name: project_id
        type: string
        required: true
    returns: { id, name, description, statistics, ... }

  # Merge Requests
  - name: list_merge_requests
    description: List merge requests
    parameters:
      - name: state
        type: string
        enum: [opened, closed, merged, all]
      - name: scope
        type: string
        enum: [all, assigned_to_me, created_by_me]
    returns: [{ id, title, author, created_at, updated_at }]

  # Pipelines
  - name: list_pipelines
    description: List CI/CD pipelines
    parameters:
      - name: project_id
        type: string
        required: true
      - name: status
        type: string
        enum: [running, pending, success, failed]
    returns: [{ id, status, ref, created_at, duration }]

  - name: trigger_pipeline
    description: Trigger a new pipeline
    parameters:
      - name: project_id
        type: string
        required: true
      - name: ref
        type: string
        default: main
    returns: { id, status, web_url }

  # Users
  - name: list_users
    description: List GitLab users
    returns: [{ id, username, email, state, is_admin }]

  - name: get_user_activity
    description: Get recent user activity
    parameters:
      - name: username
        type: string
    returns: [{ action, target, timestamp }]
```

### 6.2 mcp-hetzner

```yaml
name: hetzner
description: Hetzner Cloud infrastructure operations

config:
  hetzner_token: ${HETZNER_TOKEN}
  default_location: fsn1

tools:
  # Servers
  - name: list_servers
    description: List all servers
    returns: [{ id, name, status, server_type, datacenter, public_ip }]

  - name: get_server_metrics
    description: Get server metrics (CPU, disk, network)
    parameters:
      - name: server_id
        type: integer
        required: true
      - name: type
        type: string
        enum: [cpu, disk, network]
    returns: { timeseries: [...] }

  - name: create_server
    description: Provision a new server
    parameters:
      - name: name
        type: string
        required: true
      - name: server_type
        type: string
        default: cx21
      - name: image
        type: string
        default: ubuntu-24.04
    returns: { id, name, public_ip, root_password }

  - name: delete_server
    description: Delete a server (requires confirmation)
    parameters:
      - name: server_id
        type: integer
        required: true
      - name: confirm
        type: boolean
        required: true
    returns: { success, message }

  # Volumes
  - name: list_volumes
    description: List block storage volumes
    returns: [{ id, name, size, server, location }]

  - name: create_snapshot
    description: Create volume snapshot
    parameters:
      - name: volume_id
        type: integer
        required: true
      - name: description
        type: string
    returns: { id, description, created }

  # Load Balancers
  - name: get_load_balancer_status
    description: Get load balancer health
    parameters:
      - name: lb_id
        type: integer
    returns: { id, name, targets: [{ healthy, status }] }
```

### 6.3 mcp-borg

```yaml
name: borg
description: BorgBackup operations for GitLab backups

config:
  borg_repo: ${BORG_REPO}
  borg_passphrase: ${BORG_PASSPHRASE}
  ssh_key_path: /root/.ssh/storagebox_key

tools:
  - name: list_archives
    description: List backup archives
    parameters:
      - name: last_n
        type: integer
        default: 10
    returns: [{ name, timestamp, size }]

  - name: get_archive_info
    description: Get detailed archive information
    parameters:
      - name: archive_name
        type: string
        required: true
    returns: { name, start, end, stats, files }

  - name: check_backup_age
    description: Check age of most recent backup
    returns: { archive_name, age_hours, is_healthy }

  - name: verify_archive
    description: Verify archive integrity
    parameters:
      - name: archive_name
        type: string
    returns: { valid, errors }

  - name: trigger_backup
    description: Trigger immediate backup (requires approval)
    returns: { started, archive_name }

  - name: extract_file
    description: Extract specific file from archive
    parameters:
      - name: archive_name
        type: string
        required: true
      - name: file_path
        type: string
        required: true
    returns: { content, size }
```

### 6.4 mcp-security (Ransomware & Threat Detection)

```yaml
name: security
description: Security monitoring, anomaly detection, and ransomware protection

config:
  gitlab_host: ${GITLAB_HOST}
  ssh_key_path: /root/.ssh/admin_bot_key
  baseline_path: /opt/integrator-bot/data/security_baseline.json

tools:
  # Anomaly Detection
  - name: check_file_anomalies
    description: Detect suspicious file changes (mass encryption, unusual extensions)
    parameters:
      - name: path
        type: string
        default: /var/opt/gitlab
      - name: hours_back
        type: integer
        default: 24
    returns: { anomalies: [{ type, path, details }], risk_level }

  - name: check_process_anomalies
    description: Detect suspicious processes (crypto miners, unknown binaries)
    returns: { suspicious_processes: [{ pid, name, user, cpu, memory, indicators }] }

  - name: check_network_anomalies
    description: Detect unusual network activity (data exfiltration, C2 communication)
    returns: { suspicious_connections: [{ local, remote, process, bytes }] }

  # Ransomware Indicators
  - name: detect_ransomware_indicators
    description: Check for known ransomware patterns
    returns:
      indicators:
        mass_file_changes: boolean
        encrypted_extensions: [string]
        ransom_notes_found: boolean
        suspicious_processes: [string]
      risk_score: integer  # 0-100
      recommended_action: string

  # Authentication Security
  - name: analyze_auth_logs
    description: Analyze authentication logs for suspicious activity
    parameters:
      - name: hours_back
        type: integer
        default: 24
    returns:
      failed_logins: [{ user, ip, timestamp, count }]
      brute_force_detected: boolean
      unusual_access_patterns: [{ user, pattern, risk }]

  - name: check_ssh_access
    description: Review SSH access and authorized keys
    returns:
      recent_logins: [{ user, ip, timestamp }]
      authorized_keys_changes: boolean
      suspicious_keys: [{ user, key_fingerprint, added }]

  # Integrity Verification
  - name: verify_system_integrity
    description: Check critical system files against baseline
    returns:
      modified_files: [{ path, expected_hash, actual_hash }]
      new_files: [string]
      deleted_files: [string]
      integrity_score: integer  # 0-100

  - name: verify_gitlab_config_integrity
    description: Verify GitLab configuration hasn't been tampered with
    returns:
      config_modified: boolean
      secrets_modified: boolean
      modifications: [{ file, change_type, timestamp }]
```

### 6.5 mcp-immutable-backup (Ransomware-Resistant Backups)

```yaml
name: immutable-backup
description: Manage immutable backups for ransomware protection (per SECURITY-ASSESSMENT.md)

config:
  # Primary: Borg with append-only mode
  borg_primary_repo: ${BORG_PRIMARY_REPO}
  borg_primary_user: ${BORG_PRIMARY_USER}  # backup-write (append-only)

  # Secondary: S3-compatible with Object Lock
  s3_endpoint: ${S3_ENDPOINT}  # e.g., s3.us-west-001.backblazeb2.com
  s3_bucket: ${S3_BUCKET}
  s3_access_key: ${S3_ACCESS_KEY}
  s3_secret_key: ${S3_SECRET_KEY}
  s3_retention_days: 90  # Object Lock retention

tools:
  # Multi-destination backup status
  - name: get_backup_destinations
    description: List all backup destinations and their status
    returns:
      destinations:
        - name: string
          type: string  # 'borg-append-only', 's3-worm', 'borg-full-access'
          is_immutable: boolean
          last_backup: datetime
          last_verified: datetime
          healthy: boolean

  - name: verify_all_backups
    description: Verify backups exist and are accessible at all destinations
    returns:
      verification_results:
        - destination: string
          latest_archive: string
          age_hours: number
          verified: boolean
          error: string | null

  # Immutable backup operations
  - name: create_immutable_backup
    description: Create backup to immutable storage (S3 with Object Lock)
    parameters:
      - name: backup_source
        type: string
        description: Path to GitLab backup tarball
    returns: { s3_key, object_lock_retain_until, size }

  - name: list_immutable_backups
    description: List all immutable backups in S3
    parameters:
      - name: days_back
        type: integer
        default: 90
    returns: [{ key, created, size, retain_until, legal_hold }]

  - name: verify_immutable_backup
    description: Verify an immutable backup can be retrieved
    parameters:
      - name: s3_key
        type: string
        required: true
    returns: { accessible, size, checksum_valid, retain_until }

  # Append-only Borg verification
  - name: verify_append_only_mode
    description: Verify Borg repository is in append-only mode
    returns:
      append_only_enforced: boolean
      can_delete: boolean  # Should be false
      test_result: string

  # Cross-destination comparison
  - name: compare_backup_destinations
    description: Compare backups across destinations to ensure consistency
    returns:
      in_sync: boolean
      discrepancies: [{ archive, present_in, missing_from }]
      oldest_common_backup: datetime
      recommendation: string
```

### 6.6 mcp-dr-recovery (Disaster Recovery Automation)

```yaml
name: dr-recovery
description: Disaster recovery automation with human-in-the-loop approval

config:
  hetzner_token: ${HETZNER_TOKEN}
  borg_admin_repo: ${BORG_ADMIN_REPO}  # Full access for restore (offline key)
  terraform_state_path: /opt/integrator-bot/terraform
  approval_webhook: ${APPROVAL_WEBHOOK}  # For human approval notifications

tools:
  # DR Status
  - name: get_dr_readiness
    description: Assess disaster recovery readiness
    returns:
      readiness_score: integer  # 0-100
      backup_status:
        primary_age_hours: number
        secondary_age_hours: number
        immutable_age_hours: number
      recovery_estimate_minutes: number
      blockers: [string]
      recommendations: [string]

  - name: estimate_recovery_time
    description: Estimate RTO based on current backup state
    parameters:
      - name: scenario
        type: string
        enum: [server_failure, data_corruption, ransomware, region_outage]
    returns:
      estimated_rto_minutes: number
      steps: [{ name, estimated_minutes }]
      dependencies: [string]
      risks: [string]

  # Recovery Initiation
  - name: initiate_recovery
    description: Start disaster recovery procedure (requires human approval)
    parameters:
      - name: reason
        type: string
        required: true
      - name: target_backup
        type: string
        description: Specific backup to restore (optional, defaults to latest)
    returns:
      recovery_id: string
      status: 'pending_approval'
      approval_url: string
      steps_preview: [string]

  - name: get_recovery_status
    description: Get status of ongoing recovery
    parameters:
      - name: recovery_id
        type: string
        required: true
    returns:
      status: string  # 'pending_approval', 'in_progress', 'completed', 'failed', 'aborted'
      current_step: string
      completed_steps: [string]
      pending_steps: [string]
      started_at: datetime
      estimated_completion: datetime

  # Recovery Steps (each requires approval except status checks)
  - name: approve_recovery_step
    description: Approve the next step in recovery (human action)
    parameters:
      - name: recovery_id
        type: string
        required: true
      - name: step_name
        type: string
        required: true
      - name: approver
        type: string
        required: true
    returns: { approved, next_step }

  - name: execute_recovery_step
    description: Execute a specific recovery step (after approval)
    parameters:
      - name: recovery_id
        type: string
        required: true
      - name: step_name
        type: string
        enum: [provision_server, attach_storage, install_gitlab, restore_config, restore_data, verify, update_dns]
    returns: { success, output, next_step }

  - name: abort_recovery
    description: Abort an in-progress recovery
    parameters:
      - name: recovery_id
        type: string
        required: true
      - name: reason
        type: string
        required: true
    returns: { aborted, cleanup_actions }

  # Recovery Testing
  - name: schedule_dr_test
    description: Schedule a disaster recovery drill
    parameters:
      - name: test_type
        type: string
        enum: [tabletop, partial_restore, full_restore]
      - name: scheduled_time
        type: datetime
    returns: { test_id, scheduled, notification_sent }

  - name: run_restore_test
    description: Run backup restore test on ephemeral VM
    returns:
      test_id: string
      status: string
      server_id: integer
      verification_results: { health, auth, git_clone, data_integrity }
      duration_minutes: number
      cost_estimate: number
```

### 6.7 mcp-audit (Compliance and Audit Logging)

```yaml
name: audit
description: Audit logging, compliance checking, and access review

config:
  gitlab_url: ${GITLAB_URL}
  gitlab_token: ${GITLAB_TOKEN}
  log_retention_days: 90

tools:
  - name: get_audit_events
    description: Get GitLab audit events
    parameters:
      - name: entity_type
        type: string
        enum: [user, group, project, all]
      - name: hours_back
        type: integer
        default: 24
    returns: [{ id, author, entity, action, details, timestamp }]

  - name: analyze_access_patterns
    description: Analyze user access patterns for anomalies
    parameters:
      - name: user
        type: string
    returns:
      typical_hours: [integer]
      typical_ips: [string]
      recent_anomalies: [{ type, details, timestamp }]
      risk_assessment: string

  - name: generate_compliance_report
    description: Generate compliance status report
    returns:
      two_factor_enabled: { total_users, enabled, percentage }
      password_policy_compliant: boolean
      session_timeout_configured: boolean
      audit_logging_enabled: boolean
      backup_compliance: { frequency, retention, encryption }
      recommendations: [string]

  - name: review_admin_access
    description: Review administrative access and permissions
    returns:
      admin_users: [{ username, last_login, mfa_enabled }]
      api_tokens: [{ user, scopes, created, last_used }]
      ssh_keys: [{ user, fingerprint, added }]
      recommendations: [string]
```

---

## 7. Multi-Repository Policy Architecture

### 7.1 Design Philosophy

The Integrator Bot evolves from **infrastructure-focused** to **project-aware** by reading per-repository policy files. This distributes configuration across projects, making the system more scalable, auditable, and secure.

**Key Benefits:**
- **Distributed Policy Control**: No single configuration file to compromise
- **Version-Controlled**: Policy changes go through merge requests with review
- **Project-Scoped Permissions**: Bot actions limited per-project
- **Delegated Ownership**: Project maintainers define their own rules
- **AI-Augmented Understanding**: Claude reads project documentation for context

### 7.2 Policy File Specification

Each GitLab project may contain a `.gitlab-bot.yml` file in the repository root:

```yaml
# .gitlab-bot.yml
# GitLab Integrator Bot Policy Configuration
version: 1

# =============================================================================
# Project Ownership
# =============================================================================
owners:
  primary: alice@example.com
  backup: team-firmware@example.com
  escalation:
    - oncall@example.com
    - cto@example.com

# =============================================================================
# Monitoring Configuration
# =============================================================================
monitors:
  # Branch hygiene
  stale_branches:
    enabled: true
    max_age_days: 30
    exclude:
      - main
      - develop
      - release/*
      - hotfix/*
    action: notify_owners  # notify_owners | auto_delete | create_issue

  # Merge request monitoring
  stale_merge_requests:
    enabled: true
    max_age_days: 14
    action: notify_authors
    reminder_interval_days: 7

  # Dependency vulnerabilities
  dependency_vulnerabilities:
    enabled: true
    severity_threshold: high  # critical | high | medium | low
    action: create_issue
    assignee: security-team

  # CI/CD pipeline monitoring
  ci_failures:
    enabled: true
    alert_after_consecutive: 3
    branches:
      - main
      - develop

  # Code coverage tracking
  code_coverage:
    enabled: true
    minimum_percent: 70
    alert_on_decrease: true
    threshold_decrease: 5  # Alert if coverage drops by 5%

# =============================================================================
# Automated Actions
# =============================================================================
automations:
  # Safe automations (can be enabled)
  cleanup_merged_branches:
    enabled: true
    exclude:
      - release/*
      - hotfix/*

  artifact_retention:
    enabled: true
    max_days: 30

  auto_label_stale_mrs:
    enabled: true
    label: "stale"

  # Dangerous automations (disabled by default, require explicit enable)
  auto_merge:
    enabled: false  # NEVER enable without careful consideration
    require_approvals: 2
    require_ci_pass: true
    allowed_labels:
      - auto-merge-approved

  auto_close_stale_issues:
    enabled: false
    max_age_days: 90
    warning_days_before: 14

# =============================================================================
# Compliance Requirements
# =============================================================================
compliance:
  require_code_review: true
  min_approvers: 1

  required_ci_checks:
    - lint
    - test
    - security-scan

  require_signed_commits: false

  protected_files:
    # Files that trigger extra scrutiny when changed
    - path: "**/*.key"
      action: alert_security
    - path: ".gitlab-ci.yml"
      action: require_codeowner_approval
    - path: "Dockerfile"
      action: require_codeowner_approval

  sensitive_patterns:
    # Patterns that should never be committed
    - pattern: "password\\s*=\\s*['\"][^'\"]+['\"]"
      action: block_merge
    - pattern: "api[_-]?key\\s*=\\s*['\"][^'\"]+['\"]"
      action: block_merge
    - pattern: "BEGIN (RSA |DSA |EC )?PRIVATE KEY"
      action: block_merge

# =============================================================================
# Context Documents (AI reads these for understanding)
# =============================================================================
context:
  # Primary documentation
  readme: README.md
  architecture: docs/ARCHITECTURE.md
  contributing: CONTRIBUTING.md

  # Additional context for the bot
  bot_instructions: BOT-RESPONSIBILITIES.md  # Optional natural language instructions

  # The bot will read these files to understand:
  # - Project purpose and constraints
  # - Coding standards and conventions
  # - Deployment procedures
  # - Critical paths and dependencies

# =============================================================================
# Custom Alerts
# =============================================================================
alerts:
  channels:
    default: email
    critical: [email, slack]

  custom_rules:
    - name: "Large PR Alert"
      condition: "mr.changes_count > 500"
      severity: warning
      message: "Large MR detected ({changes_count} changes). Consider splitting."

    - name: "Direct Push to Main"
      condition: "push.branch == 'main' && !push.via_mr"
      severity: critical
      message: "Direct push to main detected by {push.author}!"

# =============================================================================
# Project Classification
# =============================================================================
classification:
  tier: production  # production | staging | development | experimental
  data_sensitivity: confidential  # public | internal | confidential | restricted
  compliance_frameworks:
    - iso27001
```

### 7.3 Natural Language Policy Files

For nuanced requirements that don't fit structured YAML, projects can include a `BOT-RESPONSIBILITIES.md`:

```markdown
# Bot Responsibilities for firmware-sensor-v2

## Project Context

This firmware project powers the XYZ environmental sensor shipped to automotive
customers. Code quality and security are paramount due to:
- Safety-critical application (automotive ASIL-B)
- Long product lifecycle (10+ year support commitment)
- Regulatory requirements (ISO 26262 compliance)

## Bot Responsibilities

### MUST DO
1. Alert IMMEDIATELY if any security vulnerability is detected in dependencies
2. Block merges to `main` unless ALL CI checks pass
3. Notify firmware-team@example.com on ANY deployment failure
4. Track and report dependency update status weekly
5. Flag any code change that modifies interrupt handlers or memory allocation

### SHOULD DO
1. Remind authors if MRs are open > 7 days
2. Suggest reviewers based on file ownership
3. Monitor binary size and alert if it exceeds 256KB
4. Track technical debt issues and include in reports

### MUST NOT
1. Auto-merge ANY merge request (human review required)
2. Delete ANY branch containing "release" or "hotfix"
3. Modify any file in `/certs` or `/keys` directories
4. Approve or close issues automatically
5. Make any changes without human approval

## Deployment Notes

- Production deployments require sign-off from @firmware-lead AND @quality-lead
- Staging deployments are automated on `develop` branch merge
- The bot should monitor the deployment dashboard at https://deploy.internal/sensor-v2

## Escalation Path

1. First: firmware-team@example.com
2. If no response in 2 hours: firmware-lead@example.com
3. Critical issues: oncall@example.com immediately
```

### 7.4 Policy Scanner Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        INTEGRATOR BOT                                    │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│   ┌──────────────────────────────────────────────────────────────────┐  │
│   │                    PROJECT POLICY SCANNER                         │  │
│   │                                                                   │  │
│   │   GitLab Webhook ──► On file change: .gitlab-bot.yml             │  │
│   │                                     BOT-RESPONSIBILITIES.md       │  │
│   │                                                                   │  │
│   │   Scheduled Scan ──► Daily: Discover new projects                │  │
│   │                      Refresh all policies                        │  │
│   │                                                                   │  │
│   │   For each project:                                              │  │
│   │   1. Check if .gitlab-bot.yml exists                             │  │
│   │   2. Validate YAML schema                                        │  │
│   │   3. Read context documents if specified                         │  │
│   │   4. Parse natural language instructions                         │  │
│   │   5. Cache parsed policies                                       │  │
│   │                                                                   │  │
│   └──────────────────────────────────────────────────────────────────┘  │
│                               │                                          │
│                               ▼                                          │
│   ┌──────────────────────────────────────────────────────────────────┐  │
│   │                    PROJECT POLICY CACHE                           │  │
│   │                                                                   │  │
│   │   {                                                               │  │
│   │     "firmware-sensor-v2": {                                      │  │
│   │       "policy_version": 1,                                       │  │
│   │       "owners": {...},                                           │  │
│   │       "monitors": {...},                                         │  │
│   │       "automations": {...},                                      │  │
│   │       "context_summary": "Safety-critical automotive firmware...",│  │
│   │       "natural_language_rules": [                                │  │
│   │         "Never auto-merge",                                      │  │
│   │         "Alert on interrupt handler changes"                     │  │
│   │       ],                                                         │  │
│   │       "last_updated": "2026-02-02T10:30:00Z"                    │  │
│   │     },                                                           │  │
│   │     "web-frontend": {...},                                       │  │
│   │     "docs-internal": {...}                                       │  │
│   │   }                                                              │  │
│   │                                                                   │  │
│   │   Projects WITHOUT .gitlab-bot.yml → Use DEFAULT policy          │  │
│   │                                                                   │  │
│   └──────────────────────────────────────────────────────────────────┘  │
│                               │                                          │
│                               ▼                                          │
│   ┌──────────────────────────────────────────────────────────────────┐  │
│   │                    CLAUDE ANALYSIS ENGINE                         │  │
│   │                                                                   │  │
│   │   Prompt includes:                                                │  │
│   │   - Infrastructure state (health, resources, backups)            │  │
│   │   - Project-specific policy from .gitlab-bot.yml                 │  │
│   │   - Natural language context from BOT-RESPONSIBILITIES.md        │  │
│   │   - Historical observations for this project                     │  │
│   │                                                                   │  │
│   │   Claude then:                                                    │  │
│   │   - Applies policy rules to current state                        │  │
│   │   - Interprets ambiguous situations using context docs           │  │
│   │   - Generates project-aware recommendations                      │  │
│   │   - Respects project-specific restrictions                       │  │
│   │                                                                   │  │
│   └──────────────────────────────────────────────────────────────────┘  │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

### 7.5 MCP Server: mcp-project-policies

```yaml
name: project-policies
description: Manage per-project policy configurations from .gitlab-bot.yml

config:
  gitlab_url: ${GITLAB_URL}
  gitlab_token: ${GITLAB_TOKEN}
  cache_path: /opt/integrator-bot/data/policy_cache.db
  default_policy_path: /opt/integrator-bot/config/default_policy.yaml

tools:
  # Policy Discovery
  - name: scan_all_projects
    description: Scan all GitLab projects for policy files
    returns:
      projects_with_policy: integer
      projects_without_policy: integer
      scan_errors: [{ project, error }]

  - name: get_project_policy
    description: Get parsed policy for a specific project
    parameters:
      - name: project_id
        type: string
        required: true
    returns:
      has_policy: boolean
      policy: object | null
      context_summary: string | null
      natural_language_rules: [string]
      last_updated: datetime

  - name: validate_policy_file
    description: Validate a .gitlab-bot.yml file
    parameters:
      - name: project_id
        type: string
        required: true
    returns:
      valid: boolean
      errors: [{ line, message }]
      warnings: [{ line, message }]

  # Policy Application
  - name: get_applicable_monitors
    description: Get monitors enabled for a project
    parameters:
      - name: project_id
        type: string
        required: true
    returns:
      monitors: [{ name, config, enabled }]

  - name: get_applicable_automations
    description: Get automations enabled for a project
    parameters:
      - name: project_id
        type: string
        required: true
    returns:
      automations: [{ name, config, enabled }]

  - name: check_compliance
    description: Check if a merge request meets project compliance requirements
    parameters:
      - name: project_id
        type: string
        required: true
      - name: merge_request_iid
        type: integer
        required: true
    returns:
      compliant: boolean
      violations: [{ rule, details }]
      warnings: [{ rule, details }]

  # Context Retrieval
  - name: get_project_context
    description: Get AI-readable context for a project (from context docs)
    parameters:
      - name: project_id
        type: string
        required: true
    returns:
      context_documents: [{ path, content_summary }]
      natural_language_instructions: string | null
      project_classification: { tier, data_sensitivity, compliance_frameworks }

  # Bulk Operations
  - name: list_projects_by_tier
    description: List projects by classification tier
    parameters:
      - name: tier
        type: string
        enum: [production, staging, development, experimental, all]
    returns: [{ project_id, name, tier, has_policy }]

  - name: get_stale_policies
    description: Find projects with outdated or invalid policies
    returns:
      stale: [{ project_id, last_updated, reason }]
      invalid: [{ project_id, validation_errors }]

  # Notification Routing
  - name: get_project_owners
    description: Get notification recipients for a project
    parameters:
      - name: project_id
        type: string
        required: true
      - name: severity
        type: string
        enum: [info, warning, critical]
    returns:
      recipients: [{ email, role }]
      channels: [string]
```

### 7.6 Default Policy

Projects without `.gitlab-bot.yml` receive a conservative default policy:

```yaml
# /opt/integrator-bot/config/default_policy.yaml
# Applied to projects without their own .gitlab-bot.yml

version: 1

owners:
  primary: admin@example.com  # Falls back to GitLab admin

monitors:
  stale_branches:
    enabled: true
    max_age_days: 60  # More lenient than project-specific
    action: notify_owners

  dependency_vulnerabilities:
    enabled: true
    severity_threshold: critical  # Only critical by default
    action: notify_owners

  ci_failures:
    enabled: true
    alert_after_consecutive: 5  # More lenient

automations:
  # ALL automations disabled by default
  cleanup_merged_branches:
    enabled: false
  artifact_retention:
    enabled: false
  auto_merge:
    enabled: false

compliance:
  # Minimal requirements
  require_code_review: true
  min_approvers: 1
  required_ci_checks: []  # No required checks by default

classification:
  tier: unknown
  data_sensitivity: internal  # Assume internal by default
```

### 7.7 Example Prompts with Policy Context

**Project-Aware Health Check:**
```
You are checking the status of project "firmware-sensor-v2".

PROJECT POLICY (from .gitlab-bot.yml):
- Tier: production
- Data sensitivity: confidential
- Required CI checks: lint, test, security-scan
- Min approvers: 2
- Auto-merge: DISABLED

PROJECT CONTEXT (from BOT-RESPONSIBILITIES.md):
"This firmware project powers the XYZ environmental sensor shipped to
automotive customers. Code quality and security are paramount."

NATURAL LANGUAGE RULES:
- Never auto-merge ANY merge request
- Alert on interrupt handler changes
- Monitor binary size (max 256KB)

Current state:
- Open MRs: 3
- Failing CI: MR-156 (security-scan failed)
- Oldest MR: 12 days

Based on the policy and context, what actions should be taken?
```

**Multi-Project Report:**
```
Generate a weekly report across all projects. For each project:
1. Load its policy from the policy cache
2. Evaluate monitors based on project-specific thresholds
3. Group issues by project tier (production first)
4. Use project-specific notification channels

Projects to include:
- firmware-sensor-v2 (production, confidential)
- web-dashboard (production, internal)
- docs-internal (development, internal)
- prototype-ml (experimental, internal)
```

### 7.8 Security Hardening via Policies

The policy system improves security posture:

| Hardening Aspect | Implementation |
|------------------|----------------|
| **Least Privilege** | Bot actions scoped per-project policy |
| **Audit Trail** | Policy changes tracked via Git history |
| **Separation of Duties** | Project owners define their own rules |
| **Secure Defaults** | Default policy is highly restrictive |
| **Sensitive File Protection** | `protected_files` blocks unauthorized changes |
| **Secret Detection** | `sensitive_patterns` prevents credential commits |
| **Compliance Enforcement** | Per-project compliance requirements |

### 7.9 Database Schema Extension

```sql
-- Project policy cache
CREATE TABLE project_policies (
    project_id TEXT PRIMARY KEY,
    project_name TEXT,
    has_policy_file BOOLEAN,
    policy_yaml TEXT,           -- Raw .gitlab-bot.yml content
    policy_parsed_json TEXT,    -- Parsed policy object
    context_summary TEXT,       -- AI-generated summary of context docs
    natural_language_rules TEXT,-- Extracted rules from BOT-RESPONSIBILITIES.md
    classification_tier TEXT,
    classification_sensitivity TEXT,
    last_scanned DATETIME,
    last_updated DATETIME,
    validation_errors TEXT
);

CREATE TABLE policy_events (
    id INTEGER PRIMARY KEY,
    timestamp DATETIME,
    project_id TEXT,
    event_type TEXT,  -- 'policy_updated', 'validation_failed', 'context_read'
    details_json TEXT,
    FOREIGN KEY (project_id) REFERENCES project_policies(project_id)
);

CREATE TABLE project_observations (
    id INTEGER PRIMARY KEY,
    timestamp DATETIME,
    project_id TEXT,
    observation_type TEXT,  -- 'stale_branch', 'ci_failure', 'vulnerability', etc.
    severity TEXT,
    message TEXT,
    policy_rule TEXT,  -- Which policy rule triggered this
    action_taken TEXT,
    FOREIGN KEY (project_id) REFERENCES project_policies(project_id)
);
```

---

## 8. Claude Code Configuration

### 7.1 MCP Server Configuration

```json
// ~/.claude/mcp_servers.json
{
  "servers": {
    "gitlab": {
      "command": "node",
      "args": ["/opt/integrator-bot/mcp-servers/mcp-gitlab/dist/index.js"],
      "env": {
        "GITLAB_URL": "https://gitlab.example.com",
        "GITLAB_TOKEN": "${GITLAB_TOKEN}"
      }
    },
    "hetzner": {
      "command": "node",
      "args": ["/opt/integrator-bot/mcp-servers/mcp-hetzner/dist/index.js"],
      "env": {
        "HETZNER_TOKEN": "${HETZNER_TOKEN}"
      }
    },
    "borg": {
      "command": "python",
      "args": ["-m", "mcp_borg"],
      "env": {
        "BORG_REPO": "${BORG_REPO}",
        "BORG_PASSPHRASE": "${BORG_PASSPHRASE}"
      }
    },
    "alerts": {
      "command": "node",
      "args": ["/opt/integrator-bot/mcp-servers/mcp-alerts/dist/index.js"],
      "env": {
        "SMTP_HOST": "smtp.office365.com",
        "SMTP_USER": "${SMTP_USER}",
        "SMTP_PASSWORD": "${SMTP_PASSWORD}"
      }
    },
    "security": {
      "command": "python",
      "args": ["-m", "mcp_security"],
      "env": {
        "GITLAB_HOST": "10.0.1.10",
        "SSH_KEY_PATH": "/root/.ssh/admin_bot_key",
        "BASELINE_PATH": "/opt/integrator-bot/data/security_baseline.json"
      }
    },
    "immutable-backup": {
      "command": "python",
      "args": ["-m", "mcp_immutable_backup"],
      "env": {
        "BORG_PRIMARY_REPO": "${BORG_APPEND_ONLY_REPO}",
        "S3_ENDPOINT": "${S3_ENDPOINT}",
        "S3_BUCKET": "${S3_BUCKET}",
        "S3_ACCESS_KEY": "${S3_ACCESS_KEY}",
        "S3_SECRET_KEY": "${S3_SECRET_KEY}"
      }
    },
    "dr-recovery": {
      "command": "python",
      "args": ["-m", "mcp_dr_recovery"],
      "env": {
        "HETZNER_TOKEN": "${HETZNER_TOKEN}",
        "TERRAFORM_STATE_PATH": "/opt/integrator-bot/terraform",
        "APPROVAL_WEBHOOK": "${APPROVAL_WEBHOOK}"
      }
    },
    "audit": {
      "command": "python",
      "args": ["-m", "mcp_audit"],
      "env": {
        "GITLAB_URL": "https://gitlab.example.com",
        "GITLAB_TOKEN": "${GITLAB_TOKEN}"
      }
    },
    "project-policies": {
      "command": "python",
      "args": ["-m", "mcp_project_policies"],
      "env": {
        "GITLAB_URL": "https://gitlab.example.com",
        "GITLAB_TOKEN": "${GITLAB_TOKEN}",
        "CACHE_PATH": "/opt/integrator-bot/data/policy_cache.db",
        "DEFAULT_POLICY_PATH": "/opt/integrator-bot/config/default_policy.yaml"
      }
    }
  }
}
```

### 7.2 System Prompt (CLAUDE.md for Bot)

```markdown
# Integrator Bot System Prompt

You are the ACME Corp Integrator Bot, an AI-powered system administrator.

## Your Role

You monitor and maintain the GitLab infrastructure, proactively identifying issues
and taking appropriate action. You have access to tools for:

- **GitLab**: Check health, projects, pipelines, merge requests
- **Hetzner Cloud**: Monitor servers, volumes, manage infrastructure
- **BorgBackup**: Verify backups, check backup age, trigger backups
- **Alerting**: Send notifications to administrators
- **Security**: Detect anomalies, ransomware indicators, verify integrity
- **Immutable Backup**: Manage ransomware-resistant backups (S3 with Object Lock)
- **DR Recovery**: Orchestrate disaster recovery with human approval
- **Audit**: Review access patterns, generate compliance reports
- **Project Policies**: Read per-project .gitlab-bot.yml configurations

## Multi-Repository Awareness

Each GitLab project may have a `.gitlab-bot.yml` file that defines:
- Project-specific monitoring rules
- Allowed/disallowed automations
- Compliance requirements
- Owners and escalation paths

**ALWAYS check the project policy before taking project-specific actions.**
Projects without a policy file use conservative defaults (minimal automation).

You can also read project context documents (README, ARCHITECTURE.md,
BOT-RESPONSIBILITIES.md) to understand project-specific constraints and
make context-aware decisions.

## Security Responsibilities (per SECURITY-ASSESSMENT.md)

You are responsible for detecting and responding to security threats:

1. **Ransomware Detection**: Monitor for mass file changes, encrypted extensions,
   suspicious processes, and ransom notes
2. **Backup Integrity**: Verify backups across ALL destinations (Borg primary,
   Borg secondary, S3 immutable)
3. **Access Anomalies**: Detect brute force attempts, unusual login patterns,
   unauthorized SSH access
4. **Threat Response**: Immediately alert on critical indicators, recommend
   containment actions

## Operating Principles

1. **Proactive Monitoring**: Don't wait for problems—anticipate them
2. **Safe Actions First**: Prefer observation over action when uncertain
3. **Transparency**: Always explain what you're doing and why
4. **Escalation**: Request human approval for destructive or risky actions
5. **Documentation**: Log your observations and actions
6. **Defense in Depth**: Always verify multiple backup destinations
7. **Assume Breach**: Monitor as if attackers may already be present

## Authority Levels

### Auto-Execute (Safe)
- Health checks and status gathering
- Sending informational reports
- Cleanup of old artifacts/logs
- Generating documentation
- Security scans and anomaly detection
- Backup integrity verification

### Request Approval (Risky)
- Restarting services
- Triggering backups
- Modifying configurations
- Provisioning/destroying servers
- Restoring from backup
- **Initiating disaster recovery**
- **Isolating suspected compromised systems**
- **Revoking access credentials**

### Immediate Alert (Critical Security)
When these are detected, alert immediately AND recommend action:
- Ransomware indicators (risk score > 70)
- Backup deletion attempts
- Mass file encryption patterns
- Unauthorized admin access
- Backup age exceeds threshold on ALL destinations

## Communication Style

- Be concise but thorough
- Use structured output for reports
- Highlight critical issues clearly
- Provide actionable recommendations
```

---

## 9. Example Workflows

### 9.1 Scheduled Health Check

**Trigger**: Cron job every 5 minutes

**Prompt**:
```
Perform a quick health check of the GitLab infrastructure.

Check:
1. GitLab health endpoints
2. Server resource usage (disk, memory, CPU)
3. Backup age

If everything is OK, just update state silently.
If there are issues, alert appropriately.
```

**Claude Code Actions**:
```
1. Call mcp-gitlab.get_health() → OK
2. Call mcp-system.get_disk_usage() → 72% (OK)
3. Call mcp-system.get_memory() → 68% (OK)
4. Call mcp-borg.check_backup_age() → 45 minutes (OK)
5. Update state: all_healthy = true
6. No output (silent success)
```

### 9.2 Daily Report

**Trigger**: Cron job at 07:00 UTC

**Prompt**:
```
Generate the daily status report for ACME Corp GitLab.

Include:
1. System health summary
2. Resource usage trends (compare to yesterday)
3. Backup status and verification
4. Any notable events from the last 24 hours
5. Recommendations for the day

Send the report via email to admin@example.com.
```

**Claude Code Actions**:
```
1. Gather metrics from all systems
2. Query observations from last 24h
3. Analyze trends
4. Compose report
5. Call mcp-alerts.send_email(report)
6. Log: daily_report_sent
```

### 9.3 Incident Response

**Trigger**: Alert from monitoring (GitLab health check failed)

**Prompt**:
```
ALERT: GitLab health check failed at 14:32 UTC.

Investigate and respond:
1. Confirm the issue
2. Gather diagnostic information
3. Attempt safe recovery actions
4. If recovery fails, escalate to human
5. Document the incident
```

**Claude Code Actions**:
```
1. Call mcp-gitlab.get_health() → FAILED (timeout)
2. Call mcp-hetzner.get_server_metrics(gitlab_id) → CPU 100%, memory 95%
3. Analysis: Resource exhaustion, likely runaway process
4. Bash: ssh gitlab-admin "ps aux --sort=-%mem | head -10" → sidekiq consuming 90%
5. Decision: Restart sidekiq (safe action)
6. Bash: ssh gitlab-admin "gitlab-ctl restart sidekiq"
7. Wait 30 seconds
8. Call mcp-gitlab.get_health() → OK
9. Call mcp-alerts.send_email("Incident resolved: Sidekiq restarted")
10. Log incident to database
```

### 9.4 Interactive Admin Query

**Trigger**: Admin asks a question

**Admin**: "Which merge requests have been open for more than 2 weeks?"

**Claude Code Actions**:
```
1. Call mcp-gitlab.list_merge_requests(state="opened")
2. Filter: created_at < (now - 14 days)
3. Format response with MR details
4. Offer: "Would you like me to notify the authors?"
```

### 9.5 Security Scan (Ransomware Detection)

**Trigger**: Scheduled every 15 minutes

**Prompt**:
```
Perform a security scan focused on ransomware indicators.

Check for:
1. Mass file changes in the last hour
2. New files with encrypted extensions (.encrypted, .locked, .crypted)
3. Suspicious processes (high CPU, unknown binaries)
4. Ransom note patterns (README.txt, DECRYPT.txt in multiple directories)
5. Backup integrity across ALL destinations

If risk score > 50: Alert with details
If risk score > 70: CRITICAL alert + recommend isolation
```

**Claude Code Actions**:
```
1. Call mcp-security.detect_ransomware_indicators()
   → { risk_score: 15, mass_file_changes: false, ... }
2. Call mcp-immutable-backup.verify_all_backups()
   → All destinations healthy, latest: 23 minutes ago
3. Call mcp-security.check_process_anomalies()
   → No suspicious processes
4. Risk score low, update state silently
5. Log: security_scan_complete, risk_score=15
```

### 9.6 Multi-Destination Backup Verification

**Trigger**: Scheduled every 4 hours

**Prompt**:
```
Verify backup health across ALL destinations per 3-2-1 strategy:

1. Borg Primary (append-only on Storage Box)
2. Borg Secondary (if configured)
3. S3 Immutable (Backblaze B2 with Object Lock)

For each destination:
- Check latest backup age
- Verify integrity (checksum if possible)
- Confirm immutability is enforced

Alert if ANY destination is unhealthy or stale.
```

**Claude Code Actions**:
```
1. Call mcp-immutable-backup.get_backup_destinations()
   → 3 destinations configured
2. Call mcp-immutable-backup.verify_all_backups()
   → borg-primary: 45min ago, OK
   → borg-secondary: 48min ago, OK
   → s3-immutable: 6 days ago (weekly), OK
3. Call mcp-immutable-backup.verify_append_only_mode()
   → Append-only enforced: true
4. All healthy, update state
5. Log: backup_verification_complete, all_healthy=true
```

### 9.7 Ransomware Incident Response

**Trigger**: Alert from security scan (risk_score > 70)

**Prompt**:
```
CRITICAL: Ransomware indicators detected.

Risk score: 85
Indicators:
- 1,247 files changed in last hour
- .encrypted extension on 89 files
- Process 'crypter' consuming 95% CPU

Execute incident response:
1. DO NOT shut down (preserve forensic evidence)
2. Verify backup integrity IMMEDIATELY
3. Recommend network isolation (require human approval)
4. Document all findings
5. Alert security team via all channels
```

**Claude Code Actions**:
```
1. CRITICAL: Call mcp-alerts.send_email(severity="critical", ...)
2. Call mcp-alerts.send_webhook(...)
3. Call mcp-immutable-backup.verify_all_backups()
   → borg-primary: CANNOT CONNECT (may be compromised)
   → s3-immutable: 6 days ago, VERIFIED INTACT ✓
4. Call mcp-security.verify_system_integrity()
   → 1,247 modified files detected
5. Recommend: "ISOLATE NETWORK. Immutable backup from 6 days ago is intact."
6. Call mcp-dr-recovery.initiate_recovery(reason="ransomware",
      target_backup="s3-immutable-latest")
   → recovery_id: "dr-20260202-1432"
   → status: "pending_approval"
7. Log: incident_response_initiated, awaiting_human_approval
```

### 9.8 Policy-Aware Project Monitoring

**Trigger**: Scheduled daily per project

**Prompt**:
```
Monitor project "firmware-sensor-v2" according to its policy.

PROJECT POLICY (loaded from cache):
{
  "monitors": {
    "stale_branches": { "enabled": true, "max_age_days": 30 },
    "ci_failures": { "enabled": true, "alert_after_consecutive": 3 },
    "code_coverage": { "enabled": true, "minimum_percent": 70 }
  },
  "compliance": {
    "require_code_review": true,
    "min_approvers": 2,
    "required_ci_checks": ["lint", "test", "security-scan"]
  }
}

PROJECT CONTEXT (from BOT-RESPONSIBILITIES.md):
"Safety-critical automotive firmware. Never auto-merge. Alert on interrupt
handler changes. Monitor binary size (max 256KB)."

Perform checks defined in policy:
1. Check for stale branches (> 30 days)
2. Check for consecutive CI failures
3. Check code coverage metrics
4. Verify compliance on open MRs
5. Check for interrupt handler changes (from context)
6. Monitor binary size (from context)

Report findings per project alerting channels.
```

**Claude Code Actions**:
```
1. Call mcp-gitlab.list_branches(project="firmware-sensor-v2")
   → Found 2 stale branches: feature/old-sensor, experiment/thermal
2. Call mcp-gitlab.list_pipelines(project="firmware-sensor-v2", status="failed")
   → No consecutive failures
3. Call mcp-gitlab.get_project_statistics(project="firmware-sensor-v2")
   → Coverage: 78% ✓
4. Call mcp-gitlab.list_merge_requests(project="firmware-sensor-v2", state="opened")
   → 2 open MRs
5. For each MR, call mcp-project-policies.check_compliance()
   → MR-156: Missing required approval (needs 2, has 1) ⚠️
   → MR-162: Compliant ✓
6. Check for interrupt handler changes in MR diffs
   → MR-156 modifies src/interrupts.c ⚠️
7. Call mcp-system.get_file_size("/builds/firmware-sensor-v2/latest/firmware.bin")
   → 243KB ✓ (under 256KB limit)
8. Generate report:
   - Stale branches: feature/old-sensor, experiment/thermal
   - MR-156: Needs additional approver + modifies interrupt handlers
9. Call mcp-alerts.send_email(to=policy.owners.primary, ...)
10. Log: project_check_complete, project="firmware-sensor-v2"
```

### 9.9 Disaster Recovery Drill

**Trigger**: Scheduled monthly or manual

**Prompt**:
```
Execute a disaster recovery drill:

1. Provision ephemeral test server (CX21)
2. Restore from SECONDARY backup (not primary, to test redundancy)
3. Verify GitLab functionality
4. Destroy test server
5. Generate drill report

This is a TEST - do not touch production systems.
```

**Claude Code Actions**:
```
1. Call mcp-dr-recovery.run_restore_test()
2. [Spawns agent for test execution]
   → Provision server: 2 min
   → Install GitLab: 12 min
   → Restore backup: 28 min
   → Verify health: PASS
   → Verify auth: PASS
   → Verify git clone: PASS
   → Destroy server: OK
3. Call mcp-alerts.send_email("DR Drill Complete - All Tests PASSED")
4. Log: dr_drill_complete, duration=47min, all_passed=true
```

---

## 10. Comparison: Current vs Future

| Capability | Current Admin Bot | Integrator Bot (Claude Code) |
|------------|-------------------|------------------------------|
| Health monitoring | ✅ Custom Python | ✅ MCP + Claude reasoning |
| Resource monitoring | ✅ SSH commands | ✅ MCP + trend analysis |
| Backup verification | ✅ Custom code | ✅ MCP + intelligent testing |
| Alerting | ✅ Email/webhook | ✅ MCP + context-aware |
| AI analysis | ⚠️ Single API call | ✅ Full conversation with tools |
| Interactive queries | ❌ Not supported | ✅ Natural language |
| Multi-system orchestration | ❌ Not supported | ✅ Agent SDK |
| Adding new integrations | ❌ Major code changes | ✅ Add MCP server |
| Learning from history | ❌ Limited | ✅ Conversation memory |
| Complex workflows | ❌ Not supported | ✅ Agent spawning |
| **Ransomware detection** | ❌ Not implemented | ✅ MCP + pattern analysis |
| **Multi-destination backup** | ❌ Single destination | ✅ 3-2-1 strategy verification |
| **Immutable backup mgmt** | ❌ Not implemented | ✅ S3 Object Lock integration |
| **DR automation** | ⚠️ Manual scripts | ✅ Orchestrated with approvals |
| **Security anomaly detection** | ❌ Not implemented | ✅ Continuous monitoring |
| **Audit & compliance** | ❌ Not implemented | ✅ Automated reporting |
| **Multi-repository awareness** | ❌ Not implemented | ✅ Per-project .gitlab-bot.yml policies |
| **Project-specific rules** | ❌ Not implemented | ✅ Distributed policy configuration |
| **Context-aware decisions** | ❌ Not implemented | ✅ Reads project documentation |

---

## 11. Migration Path

### Step 1: Keep Current Bot Running
Don't disrupt existing functionality. Run both in parallel.

### Step 2: Build MCP Servers
Create MCP equivalents of current functionality.

### Step 3: Test Claude Code Runner
Run Claude Code checks alongside current bot. Compare results.

### Step 4: Gradual Cutover
- Week 1: Health checks via Claude Code
- Week 2: Resource monitoring via Claude Code
- Week 3: Backup monitoring via Claude Code
- Week 4: Alerting via Claude Code
- Week 5: Decommission old bot

### Step 5: Extend to Integrator
Add new MCP servers for additional systems.

---

## 12. Cost Considerations

### API Token Usage

| Check Type | Frequency | Est. Tokens/Check | Monthly Tokens | Monthly Cost* |
|------------|-----------|-------------------|----------------|---------------|
| Health check | 12/hour | ~500 | ~4.3M | ~$13 |
| Resource check | 1/hour | ~1,000 | ~0.7M | ~$2 |
| Backup check | 4/day | ~1,500 | ~0.2M | ~$0.5 |
| **Security scan** | 4/hour | ~800 | ~2.3M | ~$7 |
| **Multi-dest backup verify** | 6/day | ~1,200 | ~0.2M | ~$0.6 |
| Daily report | 1/day | ~3,000 | ~0.1M | ~$0.3 |
| **DR readiness check** | 1/day | ~1,500 | ~0.05M | ~$0.15 |
| **Policy scan** | 1/day | ~2,000 | ~0.06M | ~$0.2 |
| **Project-aware checks** | 4/day | ~1,500 | ~0.18M | ~$0.5 |
| Interactive | ~10/day | ~2,000 | ~0.6M | ~$2 |
| **Incident response** | ~2/month | ~5,000 | ~0.01M | ~$0.03 |
| **Total** | | | **~9M** | **~$27** |

*Estimated based on Claude API pricing. Actual costs may vary.
Security checks add ~$8/month but provide critical ransomware protection.

### Optimization Strategies

1. **Reduce health check frequency**: Every 5 min instead of every 30 sec
2. **Cache state**: Don't re-query unchanged data
3. **Batch operations**: Combine multiple checks into single invocation
4. **Use smaller model for simple checks**: Haiku for health, Sonnet for analysis

---

## 13. Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Claude API outage | Bot can't function | Fallback to basic script-based checks |
| Token cost overrun | Budget exceeded | Set token limits, alerts at thresholds |
| Prompt injection | Malicious actions | Strict input validation, sandboxing |
| Wrong action taken | System damage | Human approval for risky actions |
| State corruption | Lost context | Regular state backups, validation |
| **Bot compromise** | Attacker gains admin access | Restricted permissions, audit logging, MCP sandboxing |
| **False positive ransomware alert** | Unnecessary panic | Tuned thresholds, human verification required |
| **Missed security threat** | Undetected attack | Multiple detection layers, behavioral analysis |
| **S3/backup provider outage** | Can't verify immutable backups | Multiple providers, local integrity cache |
| **Delayed DR response** | Extended downtime | Pre-approved runbooks, regular drills |
| **Malicious policy file** | Bot takes harmful action | Schema validation, sandboxed automations |
| **Policy conflict across projects** | Inconsistent behavior | Hierarchical policy resolution, audit logging |
| **Context document manipulation** | AI misled about project | Checksums, change alerts, human review |

### Security-Specific Mitigations

| Threat (from SECURITY-ASSESSMENT.md) | Bot Mitigation |
|--------------------------------------|----------------|
| Ransomware encrypts server | Continuous monitoring, immutable backup verification |
| Attacker deletes Borg backups | Append-only mode verification, S3 WORM backup |
| Prolonged undetected access | Behavioral analysis, trend detection, integrity checks |
| Backup passphrase theft | Bot uses separate credentials, passphrase not on GitLab server |
| Hetzner account compromise | Offline Terraform state, documented manual recovery |

---

## 14. Conclusion

Using Claude Code CLI as the foundation for the Integrator Bot is the superior architecture because:

1. **Built-in capabilities** replace custom code
2. **MCP extensibility** enables easy integration
3. **Conversation memory** provides context awareness
4. **Natural language** enables admin interaction
5. **Agent SDK** enables complex orchestration
6. **Future-proof** as Claude Code evolves
7. **Security integration** addresses ransomware and DR gaps from SECURITY-ASSESSMENT.md
8. **Multi-destination backup** verification ensures 3-2-1 compliance
9. **Multi-repository awareness** via per-project `.gitlab-bot.yml` policy files
10. **Project-context understanding** by reading project documentation

The migration can be done incrementally, running both systems in parallel until confidence is established.

### Security Posture Improvement

By implementing this plan with the security MCP servers:

| Security Gap (from SECURITY-ASSESSMENT.md) | Resolution |
|--------------------------------------------|------------|
| No immutable backups | `mcp-immutable-backup` manages S3 with Object Lock |
| Passphrase on server | Bot uses separate, restricted credentials |
| No backup integrity monitoring | Continuous verification across all destinations |
| Single backup destination | Multi-destination verification (Borg + S3) |
| Manual DR process | `mcp-dr-recovery` automates with approval gates |
| No ransomware detection | `mcp-security` monitors for indicators |
| Retention enables attack timing | Long-term immutable backups (90+ days) |

---

## Appendix A: Directory Structure

```
integrator-bot/
├── mcp-servers/
│   ├── mcp-gitlab/              # GitLab API operations
│   │   ├── package.json
│   │   ├── src/
│   │   └── tsconfig.json
│   ├── mcp-hetzner/             # Hetzner Cloud operations
│   ├── mcp-borg/                # BorgBackup operations
│   ├── mcp-alerts/              # Email/webhook notifications
│   ├── mcp-metrics/             # System metrics
│   ├── mcp-security/            # Ransomware & threat detection
│   │   ├── pyproject.toml
│   │   ├── src/
│   │   │   ├── anomaly.py       # Anomaly detection
│   │   │   ├── ransomware.py    # Ransomware indicators
│   │   │   ├── integrity.py     # File integrity
│   │   │   └── auth.py          # Auth log analysis
│   │   └── baselines/           # Known-good baselines
│   ├── mcp-immutable-backup/    # S3 WORM + multi-dest verify
│   │   ├── pyproject.toml
│   │   └── src/
│   │       ├── s3_worm.py       # S3 Object Lock operations
│   │       ├── verify.py        # Multi-destination verification
│   │       └── append_only.py   # Borg append-only checks
│   ├── mcp-dr-recovery/         # Disaster recovery automation
│   │   ├── pyproject.toml
│   │   └── src/
│   │       ├── orchestrator.py  # Recovery workflow
│   │       ├── approvals.py     # Human approval gates
│   │       └── testing.py       # DR drill automation
│   ├── mcp-audit/               # Compliance & audit
│   └── mcp-project-policies/    # Per-project policy management
│       ├── pyproject.toml
│       └── src/
│           ├── scanner.py       # Policy file discovery
│           ├── validator.py     # YAML schema validation
│           ├── context.py       # Context document parsing
│           └── cache.py         # Policy cache management
├── runner/
│   ├── pyproject.toml
│   ├── src/
│   │   ├── runner.py
│   │   ├── state.py
│   │   ├── prompts.py
│   │   ├── scheduler.py
│   │   ├── security_state.py    # Security-specific state
│   │   └── policy_loader.py     # Load project policies into prompts
│   └── tests/
├── config/
│   ├── claude.md                # System prompt
│   ├── mcp_servers.json         # MCP configuration
│   ├── schedules.yaml           # Cron schedules
│   ├── default_policy.yaml      # Default policy for projects without config
│   ├── policy_schema.json       # JSON schema for .gitlab-bot.yml validation
│   ├── security_baselines/      # Known-good file hashes
│   └── dr_runbooks/             # Recovery procedures
├── scripts/
│   ├── install.sh
│   ├── health-check.sh
│   └── security-scan.sh         # Manual security scan
├── offline-recovery/            # Kept OFFLINE (not on servers)
│   ├── terraform-state/
│   ├── credentials/
│   └── recovery-keys/
└── docs/
    ├── runbook.md
    ├── security-procedures.md
    └── dr-procedures.md
```

## Appendix B: Implementation Checklist

### Phase 1: Core MCP Servers
- [ ] Create mcp-gitlab server
- [ ] Create mcp-hetzner server
- [ ] Create mcp-borg server
- [ ] Create mcp-system server
- [ ] Create mcp-alerts server
- [ ] Test each server independently
- [ ] Configure Claude Code to use servers

### Phase 1b: Security MCP Servers (Critical - per SECURITY-ASSESSMENT.md)
- [ ] Create mcp-security server
  - [ ] Implement ransomware indicator detection
  - [ ] Implement file anomaly detection
  - [ ] Implement auth log analysis
  - [ ] Create baseline generation tool
- [ ] Create mcp-immutable-backup server
  - [ ] Implement S3 Object Lock integration
  - [ ] Implement multi-destination verification
  - [ ] Implement append-only mode verification
- [ ] Create mcp-dr-recovery server
  - [ ] Implement recovery orchestration
  - [ ] Implement human approval workflow
  - [ ] Implement DR testing automation
- [ ] Create mcp-audit server
- [ ] Test security servers with simulated threats
- [ ] Verify integration with existing MCP servers

### Phase 2: Runner
- [ ] Create state database schema (including security tables)
- [ ] Implement state manager
- [ ] Create runner script
- [ ] Implement prompt templates
- [ ] Set up cron jobs
- [ ] Test scheduled execution

### Phase 2b: Policy System (Multi-Repository)
- [ ] Create mcp-project-policies server
  - [ ] Implement policy file discovery
  - [ ] Implement YAML schema validation
  - [ ] Implement context document parsing
  - [ ] Implement natural language rule extraction
- [ ] Create default_policy.yaml
- [ ] Add policy cache to database schema
- [ ] Implement webhook handler for policy file changes
- [ ] Test policy scanning across multiple projects
- [ ] Document .gitlab-bot.yml specification for project teams

### Phase 3: Prompts
- [ ] Write health check prompt
- [ ] Write resource check prompt
- [ ] Write backup check prompt
- [ ] Write daily report prompt
- [ ] Write incident response prompt
- [ ] **Write security scan prompt**
- [ ] **Write ransomware detection prompt**
- [ ] **Write multi-destination backup verification prompt**
- [ ] **Write DR readiness check prompt**
- [ ] **Write project-aware prompts with policy context**
- [ ] Test and refine all prompts

### Phase 4: Interactive
- [ ] Create chat interface wrapper
- [ ] Implement context loading
- [ ] Add approval workflow
- [ ] Test admin interactions

### Phase 5: Security Hardening
- [ ] Set up Borg append-only mode on Storage Box
- [ ] Configure S3 bucket with Object Lock
- [ ] Create security baselines
- [ ] Test ransomware detection with simulated indicators
- [ ] Run first DR drill
- [ ] Document incident response procedures

### Phase 6: Cutover
- [ ] Run parallel operation
- [ ] Compare results
- [ ] Gradual migration
- [ ] Decommission old bot
- [ ] Final security audit
