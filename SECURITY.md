# Security Policy

## Reporting a vulnerability

If you believe you've found a security issue in this infrastructure code — Terraform, scripts, cloud-init templates, or operational design — please report it privately.

**Email**: security@example.com  (replace with your operational mailbox)

**PGP key**: optional — publish a fingerprint here if you accept encrypted reports.

Please do **not** open a public GitHub issue or PR for a security-sensitive finding. The repo is small enough that a public report effectively gives an attacker a head start.

Please include:

- A description of the issue and the security impact
- The file(s) and line(s) affected (or the design decision in `docs/DESIGN.md` you're challenging)
- Steps to reproduce (if applicable), or a clear walk-through of the attack
- Any proof-of-concept (optional but appreciated)

We'll acknowledge receipt within 5 business days and aim to triage within 10.

## Scope

In scope:

- This repository's Terraform, shell scripts, cloud-init templates, and seed bootstrap code
- The operational design in `docs/DESIGN.md` and the threat model in `docs/SECURITY-ASSESSMENT.md`
- The Prometheus alert rules in `monitoring/alerts.yml`

Out of scope (please report to the upstream project instead):

- GitLab CE itself → https://about.gitlab.com/security/
- Hetzner Cloud platform → security@hetzner.com
- BorgBackup → https://borgbackup.readthedocs.io/en/stable/security.html
- Terraform providers, exporters, and other third-party tools

## What we treat as a vulnerability

- Anything that lets an unauthorised actor read, modify, or delete production data
- Anything that bypasses our authentication or authorisation controls (Azure AD SSO, GitLab 2FA, break-glass account model)
- Anything that defeats the documented ransomware protections (append-only Borg, S3 Object Lock, offline recovery kit)
- Configuration patterns in this repo that would produce an insecure deployment if followed as documented
- Operational instructions that, if followed, would leak credentials or weaken the threat model

## What we don't treat as a vulnerability

- Findings that the design explicitly documents as accepted trade-offs (see `docs/SECURITY-ASSESSMENT.md` §4 and the `docs/SECURITY-REVIEW-*.md` artifacts). These are conscious choices, not gaps. Examples: Hetzner-side disk image exfiltration, single-region deployment, single-operator bus factor.
- Generic best-practice deviations that don't map to a concrete attack at this project's scale.

## Process

1. Reporter sends details via the email above.
2. We acknowledge within 5 business days.
3. We triage and respond within 10 business days with: classification (security / not / out-of-scope), severity, and our planned timeline.
4. For confirmed issues we'll work on a fix; we'll keep the reporter updated.
5. Once a fix is deployed, we'll add a dated entry to `docs/SECURITY-REVIEW-YYYY-MM-DD.md` referencing the finding (with credit to the reporter if they want it).

## Reviews on our side

The project runs internal security reviews on a documented cadence — see `CLAUDE.md` § "Security Reviews" for the event triggers (new component, CVE in the stack, operator turnover, incident, major version bump) and the periodic baseline (annually full, quarterly checkpoint). The most recent review is `docs/SECURITY-REVIEW-2026-05-15.md`.
