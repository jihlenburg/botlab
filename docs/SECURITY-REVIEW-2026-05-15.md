# Security Review — 2026-05-15

**Reviewer**: Claude (under the security-first / devil's-advocate working style codified in `CLAUDE.md`)
**Scope**: full design at `docs/DESIGN.md` v2.1, plus supporting docs, Terraform, scripts, and cloud-init.
**Trigger**: codification of the security-first mindset; first baseline review under the new policy.

---

## Methodology

1. Re-read `DESIGN.md`, `SECURITY-ASSESSMENT.md`, `RUNBOOK-RECOVERY.md`, `DEPLOY.md`.
2. Walked the v1.1 threat model in `SECURITY-ASSESSMENT.md` §2 against the v2.1 design (which removed the Admin Bot and added the external observer / Watchdog).
3. For every component, asked: *how would this be attacked, and what is the blast radius?*
4. Categorised findings by tier of urgency.

Findings tiers:

- **T1 — Fix sooner**: realistic, high blast radius, or low effort to mitigate. Should be on a sprint plan.
- **T2 — Should fix**: meaningful improvement to posture, but the current state isn't actively bleeding.
- **T3 — Hardening polish**: defence in depth; do these after T1/T2 are clear.

---

## Accepted risks (NOT findings — context only)

These risks the design explicitly accepts. They are revisited only when the underlying constraint changes.

- **Single Hetzner region.** Mitigated *only* when the cross-provider S3 immutable tier is configured.
- **~1-2h RTO with operator-driven recovery.** No hot standby.
- **One human operator** (bus factor 1). Mitigated by complete documentation in `DEPLOY.md` and `RUNBOOK-RECOVERY.md` — but a documented runbook does not bring back a single operator who is hit by a bus.
- **~63 EUR/month budget** precludes WAF, HSM, EDR agents, SIEM, dedicated SOC tooling.
- **Open Source only** — no commercial security products in scope.
- **No autonomous automation** — no bot-driven response. All actions are human-gated.

---

## Findings

### T1 — Fix sooner

**T1.1 — Plaintext secrets on disk**
- *Current state*: Borg passphrase in `/etc/gitlab-backup.conf`, S3 creds in `/etc/gitlab-s3-backup.conf`, SMTP password in `/etc/gitlab/gitlab.rb`, `hcloud_token` in `terraform/terraform.tfvars`. `seed.yaml` itself is plaintext on the operator's laptop.
- *Blast radius*: any unauthorised filesystem read on the GitLab server → instant backup-destination access (read), SMTP relay (send-as), and ability to inject poisoned archives. Operator-laptop compromise → entire infrastructure.
- *Recommendation*: implement DESIGN.md Appendix C (sops + age) for `seed.yaml`. For server-side configs, use `systemd-creds` to load `BORG_PASSPHRASE` and AWS keys at unit-start time so they exist only in process memory.
- *TODO.md*: already tracked (Phase 5 Security Hardening).
- *Target*: before first production traffic.

**T1.2 — Terraform state lives on operator laptop**
- *Current state*: `terraform.tfstate` is local; loss of laptop = loss of state = inability to do partial `terraform apply` during DR.
- *Blast radius*: an attacker who steals the state file gets resource IDs (useful for reconnaissance) but not credentials. The greater risk is *availability*: if state is lost, DR slows from ~1-2h to "rebuild from scratch."
- *Recommendation*: configure a remote state backend. Hetzner Object Storage supports S3-API → use `terraform { backend "s3" {} }` against the existing object-storage bucket, with state encryption enabled. State file lives in the same Hetzner account that the resources do, which doesn't help against Hetzner account lockout — so *also* keep a periodic state snapshot in the offline recovery kit.
- *Target*: before next `terraform apply`.

**T1.3 — Recovery-workstation security model undefined**
- *Current state*: `RUNBOOK-RECOVERY.md` says "do this on a recovery workstation that is not the compromised server" but never defines what that workstation is, who hardens it, or where the offline Borg full-access key lives.
- *Blast radius*: if the "recovery workstation" is just the operator's daily-driver laptop, the offline Borg key is effectively online whenever the laptop is on the network.
- *Recommendation*: define a recovery-workstation profile in `RUNBOOK-RECOVERY.md`: dedicated machine OR live-USB Linux image, FDE on, network-isolated when not actively recovering, offline kit loaded from encrypted media only. Document who owns it and where it lives.
- *Target*: before first DR drill.

**T1.4 — `trusted_ssh_ips` defaults to wildcard if empty**
- *Current state*: `terraform/firewalls.tf` has a `dynamic "rule"` that opens SSH to `0.0.0.0/0` if `trusted_ssh_ips` is left empty. This is documented as "NOT recommended for production" but is the *default*.
- *Blast radius*: a forgotten variable produces a deny→allow flip — silent.
- *Recommendation*: make `trusted_ssh_ips` a required variable with no default. `terraform plan` will fail loudly if it's missing, instead of silently exposing SSH. Update `terraform.tfvars.example` to make the requirement explicit.
- *Target*: this week. ~30 minutes of work.

**T1.5 — Monitoring stack exposure model undocumented**
- *Current state*: Prometheus, Alertmanager, and Grafana run on the GitLab server (DESIGN.md §7). Nowhere is it stated what *port* they listen on, what *auth* they require, or whether they're reachable from the public IP.
- *Blast radius*: Grafana with default admin/admin → metric exfiltration, dashboard tampering, and (with `Image Renderer`) potential RCE depending on version. Alertmanager with no auth → an attacker can silence the very alerts that would expose them.
- *Recommendation*: document in DESIGN.md §7 that all three bind to `127.0.0.1` only and are reached via SSH port-forward; OR via a reverse proxy on a non-public path with basic auth. Grafana admin password set at first boot from `seed.yaml`. Alertmanager API write endpoints disabled (`--web.config.file` with auth required for silences). The Watchdog webhook receiver on the external observer must authenticate the incoming alert (shared secret or mTLS), otherwise an attacker can spoof "all clear."
- *Target*: before standing up the monitoring stack (Phase 4).

**T1.6 — `curl https://... | bash` for GitLab repo install**
- *Current state*: cloud-init runs `curl https://packages.gitlab.com/install/repositories/gitlab/gitlab-ce/script.deb.sh | bash` at first boot. Standard GitLab pattern; still a known anti-pattern.
- *Blast radius*: if `packages.gitlab.com` (or our DNS resolution for it) is compromised at the moment of install, arbitrary code runs as root with the server's network access. The window is small (one install per server) but the consequence is total.
- *Recommendation*: download the script once, vendor it into `scripts/install-gitlab-repo.sh`, verify checksum in CI, and have cloud-init run the vendored copy. Refresh + re-verify the checksum quarterly (it's now a T1 review trigger). This is what GitLab themselves recommend for production deployments.
- *Target*: within 30 days.

---

### T2 — Should fix

**T2.1 — Hetzner vendor concentration of immutable tier**
- *Current state*: `backup.s3.enabled` defaults to `false`. Even when `true`, `seed.example.yaml`'s example endpoint is `s3.us-west-002.backblazeb2.com` but nothing prevents using Hetzner Object Storage as the "immutable" tier — which is in the same account being protected against.
- *Recommendation*: in `seed_schema.py`, refuse to validate when `backup.s3.enabled: true` AND `backup.s3.endpoint` matches a Hetzner Object Storage hostname. Force a non-Hetzner provider for this tier.
- *TODO.md*: already tracked (Phase 5: "Move S3 immutable copy to a non-Hetzner provider").
- *Target*: before first production traffic.

**T2.2 — No CVE monitoring process between minor versions**
- *Current state*: `DESIGN.md` §5.6 documents how to upgrade GitLab. It does not document *when* — i.e., how we learn that a CVE patch needs applying.
- *Recommendation*: document in §5.6: subscribe an alias (e.g. `gitlab-security@example.com`) to GitLab's security RSS / mailing list; treat GitLab "critical" releases as on-call-pageable events; patch within the published security release window (typically 7 days for critical).
- *Target*: same time as Phase 4 monitoring rollout.

**T2.3 — No SSH-side `fail2ban` jail**
- *Current state*: cloud-init configures fail2ban with a GitLab-auth jail only. SSH brute-force protection on port 22 is not configured.
- *Recommendation*: add the default `sshd` jail to `/etc/fail2ban/jail.d/`. Trivial.
- *Target*: rolled in with next cloud-init change.

**T2.4 — TLS hardening not specified**
- *Current state*: `gitlab.rb` sets `nginx['ssl_protocols'] = "TLSv1.2 TLSv1.3"` and HSTS 1y. No cipher-suite policy, no OCSP stapling instruction, no HSTS preload submission.
- *Recommendation*: pin a Mozilla "Intermediate" cipher suite list explicitly; enable OCSP stapling; document HSTS preload submission as an operator one-time task in `DEPLOY.md`.
- *Target*: with the next `gitlab.rb` refresh.

**T2.5 — LB sticky-session cookie flags not specified**
- *Current state*: `terraform/load_balancer.tf` sets `cookie_name = "GITLABLB"` but doesn't configure `Secure`, `HttpOnly`, `SameSite` flags. Default Hetzner LB behaviour is undocumented in the design.
- *Recommendation*: confirm Hetzner LB defaults; if it doesn't set `Secure; HttpOnly; SameSite=Lax` by default, raise it as a vendor-provided gap and document the residual risk.
- *Target*: this quarter.

**T2.6 — Credential rotation cadence only defined for Borg passphrase**
- *Current state*: Appendix C documents `borg key change-passphrase` and recommends 12-month rotation. No equivalent for: `hcloud_token`, GitLab `private_token`, Azure AD SAML cert, SMTP password, SSH host keys, operator SSH keys.
- *Recommendation*: extend Appendix C with a credential-rotation matrix: what, how often, how (command), how to verify. Track "last rotated" in `seed.yaml` as comments.
- *Target*: with next DESIGN.md revision.

**T2.7 — No file integrity monitoring**
- *Current state*: `SECURITY-ASSESSMENT.md` §5.3 lists AIDE as "❌ Not implemented". Without FIM, in-progress malware encryption or tampering with `/etc/gitlab/gitlab.rb` goes undetected until the next backup-age or restore-test alert.
- *Recommendation*: install AIDE in cloud-init with a baseline taken after first reconfigure; nightly cron compares against baseline and emits a Prometheus textfile metric on diff. Quiet during legitimate `gitlab-ctl reconfigure` windows by re-baselining as part of the upgrade runbook.
- *Target*: with monitoring stack rollout.

**T2.8 — Break-glass account model undefined**
- *Current state*: GitLab 2FA enforced; SSO via Azure AD. If Azure AD is down or our SAML cert expires, login fails. No documented break-glass account.
- *Recommendation*: define a local-only admin account with 2FA *enabled* (TOTP, with backup codes stored in the offline recovery kit). Never used except for SSO recovery. Document the procedure in `RUNBOOK-RECOVERY.md`.
- *Target*: with first deploy.

---

### T3 — Hardening polish

**T3.1 — Commit signing not specified.** No design statement on whether commits must be signed (`gpg.requireSigned`, sigstore, ssh-signed). For a CAD/firmware shop with regulated outputs, this is worth a decision even if the answer is "no."

**T3.2 — No SBOM / supply-chain integrity check** beyond apt's package signing. Considering `apt-mark` is now in play and we pin a specific GitLab version, periodically verify the installed package's signature is what we expect (`apt-cache policy gitlab-ce`, `debsums gitlab-ce`).

**T3.3 — LFS pre-signed URL TTL not specified.** `gitlab.rb` enables LFS-to-S3 but doesn't constrain pre-signed URL lifetime. Default is 10 minutes; shorten if practical.

**T3.4 — No defined log retention.** `journalctl` defaults are install-dependent; `auth.log` rotates per OS default. Document a retention policy aligned with the audit posture (90 days minimum recommended for an SSO-fronted system).

**T3.5 — No tabletop exercises beyond DR drill.** The DR drill exercises infrastructure recovery; it doesn't exercise *security incidents* (suspected breach, leaked token, lost laptop with offline key). Schedule one annually.

**T3.6 — No responsible-disclosure path.** No `SECURITY.md` at repo root telling external researchers how to report a vulnerability in this infrastructure. Low traffic likely, but free to add.

**T3.7 — Pre-commit hook `detect-private-key` enabled but no broader secret-scanning history check.** Gitleaks is in `.pre-commit-config.yaml`; confirm it runs in CI as well (not only as pre-commit, which can be bypassed with `--no-verify`).

---

## Cross-cutting observations

- The most concerning *pattern* across these findings is **plaintext credentials in multiple files on multiple machines**. Closing T1.1 closes the largest single class of risk. Everything else is incremental compared to that.
- The **external observer** (DESIGN.md §7.5) is the one component most likely to be deployed casually and forgotten about. Its auth model (T1.5) should be designed *with* the observer, not after.
- We've added a lot of *process* (devil's advocate, security mindset, security reviews). Process degrades into theater unless it produces visible artifacts. The pattern of dated `SECURITY-REVIEW-YYYY-MM-DD.md` files is the simplest enforcement mechanism — if the next one isn't there by 2027-05-15, somebody noticed.

---

## Actions opened against TODO.md

The following new entries are added to `TODO.md` under Phase 5 (Security Hardening) as a result of this review:

- T1.2 — Configure remote Terraform state backend (Hetzner Object Storage, encrypted) + offline snapshot in recovery kit
- T1.3 — Define recovery-workstation profile in `RUNBOOK-RECOVERY.md`
- T1.4 — Make `trusted_ssh_ips` a required Terraform variable (no default)
- T1.5 — Document monitoring stack exposure & auth model in DESIGN.md §7
- T1.6 — Vendor the GitLab repo install script + checksum verify
- T2.2 — Document GitLab CVE monitoring/patching cadence in DESIGN.md §5.6
- T2.3 — Add `sshd` fail2ban jail to cloud-init
- T2.4 — TLS hardening (ciphers, OCSP, HSTS preload) in `gitlab.rb`
- T2.5 — Confirm/configure LB sticky-cookie flags
- T2.6 — Credential rotation matrix in DESIGN.md Appendix C
- T2.7 — AIDE file-integrity monitoring in cloud-init
- T2.8 — Document break-glass admin account in DESIGN.md §5 + RUNBOOK
- T3.x items folded into a single "T3 hardening polish backlog" entry

---

## Next review

- **Quarterly check (2026-08-15)**: verify T1 items are closed or in progress with owners and target dates; verify offline recovery kit is readable; verify last weekly restore-test ran.
- **Annual baseline (2027-05-15)**: full re-read; produce `SECURITY-REVIEW-2027-05-15.md`.

Event triggers (per `CLAUDE.md`) may move the next review earlier.
