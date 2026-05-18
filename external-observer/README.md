# external-observer

Minimal scaffolding for the dead-man's-switch observer described in
`docs/DESIGN.md` §7.5.

## Purpose

The GitLab server runs its own Prometheus and Alertmanager. If the server is
down, on fire, or has lost network, the very thing that would alert you about
that is also down. The external observer lives **outside** the GitLab server's
failure domain and watches two signals:

1. **HTTPS probe** of `https://<your-domain>/-/health` every minute. Fires
   if probes fail for ≥ 5 minutes. This catches "GitLab is down" when our
   own Alertmanager can't tell us.
2. **Watchdog dead-man** — Alertmanager on the GitLab server dispatches a
   `Watchdog` alert constantly via webhook to the observer. The observer
   fires its own alert when the watchdog **stops** arriving. This catches
   the case where the GitLab server is up but its monitoring stack has
   died.

## Where to run it

This deliberately must NOT live on the GitLab server. Options:

- **Recommended**: a tiny non-Hetzner VPS (Vultr / Linode / OVH / etc.,
  1 vCPU / 1 GB, ~5 EUR/mo). Survives a Hetzner-wide outage AND a Hetzner
  account-lockout incident.
- Acceptable: another Hetzner Cloud server in a different DC (Nuremberg /
  Helsinki). Cheaper but does NOT survive account-level Hetzner problems.
- For a smaller setup: a free uptime-monitoring service (UptimeRobot,
  BetterStack, HetrixTools). Solves the LB probe but typically not the
  Watchdog half — most free tiers don't accept inbound webhooks.

## What's in this directory

- `setup-observer.sh` — installs `blackbox_exporter` + a tiny webhook
  receiver on a fresh Debian/Ubuntu VPS. Configures the HTTPS probe.
  Writes a Prometheus + Alertmanager config that watches for the Watchdog
  webhook from the GitLab server. Sends alerts (LB down, watchdog stale)
  to your chosen email/webhook.

## What's deliberately NOT here

- Terraform. The provider depends on which VPS host you pick.
- A Docker Compose. Single static binary install is simpler at this scale.
- TLS certs. The webhook receiver listens on the VPS's public IP with
  HTTPS via a small `caddy` reverse-proxy (handled by `setup-observer.sh`).

## Required inputs

When you run `setup-observer.sh` you'll be prompted for:

- The GitLab domain to probe (e.g. `gitlab.acme.example`)
- The webhook shared secret (random, 32+ chars; ALSO configured on the
  GitLab server's Alertmanager so it includes the secret when posting
  the Watchdog alert)
- The alerting destination (email address or webhook URL — typically
  the operator's personal phone-reachable notification channel,
  ideally NOT the same Microsoft account that runs the GitLab SSO,
  for true independence)

## After install

The observer alerts you when:

- `gitlab.acme.example/-/health` returns non-200 for 5 minutes (GitLab
  unreachable from the public internet)
- The Watchdog alert has not arrived in 10 minutes (the on-box
  monitoring stack has stopped working)

It does NOT take any action — alerting only. The remediation is
documented in `docs/RUNBOOK-RECOVERY.md`.

## What this does NOT solve

- Hetzner account compromise (helps detect, doesn't prevent)
- Operator personal account compromise (the alerting destination should
  be independent of the operator's daily identity — this is up to you
  to configure)
- The observer's own death (no second-order observer — if you care,
  layer a free uptime service on top of the observer's own health
  endpoint)
