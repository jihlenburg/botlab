#!/bin/bash
# =============================================================================
# external-observer/setup-observer.sh
# =============================================================================
#
# Provision the dead-man's-switch observer on a fresh Debian 12+ /
# Ubuntu 22.04+ VPS, ideally on a non-Hetzner provider for genuine
# failure-domain independence. See DESIGN.md §7.5 and
# external-observer/README.md.
#
# Installs:
#   - blackbox_exporter — HTTPS probe of the GitLab LB endpoint
#   - prometheus — scrapes blackbox + receives the Watchdog webhook
#   - alertmanager — dispatches alerts on probe failure / watchdog stale
#   - caddy — TLS terminator for the inbound Watchdog webhook
#
# Run on the VPS as root, after assigning a DNS name to it (caddy needs
# this for automatic Let's Encrypt).

set -euo pipefail

if [[ $EUID -ne 0 ]]; then
    echo "Must run as root" >&2; exit 1
fi

# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------

read -rp "GitLab domain to probe (e.g. gitlab.acme.example): " GITLAB_DOMAIN
read -rp "DNS name of THIS observer (for Let's Encrypt) (e.g. observer.acme.example): " OBSERVER_DOMAIN
read -rp "Alerting email (or webhook URL): " ALERT_DEST
read -rsp "Watchdog webhook shared secret (32+ chars; will be required on the GitLab server's Alertmanager too): " WEBHOOK_SECRET
echo

for v in GITLAB_DOMAIN OBSERVER_DOMAIN ALERT_DEST WEBHOOK_SECRET; do
    if [[ -z "${!v}" ]]; then
        echo "ERROR: $v is required" >&2; exit 1
    fi
done
if [[ ${#WEBHOOK_SECRET} -lt 32 ]]; then
    echo "ERROR: webhook secret must be >= 32 chars" >&2; exit 1
fi

# ---------------------------------------------------------------------------
# Install packages
# ---------------------------------------------------------------------------

apt-get update -qq
apt-get install -y prometheus prometheus-blackbox-exporter prometheus-alertmanager \
    debian-keyring debian-archive-keyring apt-transport-https curl jq

# Caddy from the official repo (Debian's `caddy` package lags)
curl -fsS https://dl.cloudsmith.io/public/caddy/stable/gpg.key \
    | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -fsS https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt \
    | tee /etc/apt/sources.list.d/caddy-stable.list
apt-get update -qq
apt-get install -y caddy

# ---------------------------------------------------------------------------
# blackbox_exporter probe module: HTTPS to GitLab
# ---------------------------------------------------------------------------

cat > /etc/prometheus/blackbox.yml <<'BBE'
modules:
  http_2xx:
    prober: http
    timeout: 10s
    http:
      preferred_ip_protocol: ip4
      valid_http_versions: [HTTP/1.1, HTTP/2]
      valid_status_codes: [200]
      method: GET
      fail_if_ssl: false
      fail_if_not_ssl: true
      tls_config:
        insecure_skip_verify: false
BBE
systemctl restart prometheus-blackbox-exporter

# ---------------------------------------------------------------------------
# Prometheus: scrape blackbox + load alert rules
# ---------------------------------------------------------------------------

cat > /etc/prometheus/alerts.yml <<'ALERTS'
groups:
  - name: observer
    interval: 30s
    rules:
      - alert: GitLabUnreachableFromInternet
        expr: probe_success{job="gitlab-http"} == 0
        for: 5m
        labels: { severity: critical }
        annotations:
          summary: "GitLab is unreachable from the public internet (5min+)"

      - alert: WatchdogStale
        expr: time() - watchdog_received_timestamp > 10 * 60
        for: 1m
        labels: { severity: critical }
        annotations:
          summary: "On-box Alertmanager Watchdog has not arrived in > 10 min"
          description: "The GitLab server's monitoring stack appears to have stopped dispatching alerts."

      - alert: WatchdogNeverSeen
        expr: absent(watchdog_received_timestamp)
        for: 15m
        labels: { severity: critical }
        annotations:
          summary: "Observer has NEVER received a Watchdog alert"
          description: "Likely the on-box Alertmanager is misconfigured (wrong webhook URL or secret), or the on-box stack has never started."
ALERTS

cat > /etc/prometheus/prometheus.yml <<PROM
global:
  scrape_interval: 30s
  evaluation_interval: 30s

rule_files:
  - /etc/prometheus/alerts.yml

alerting:
  alertmanagers:
    - static_configs:
        - targets: ['127.0.0.1:9093']

scrape_configs:
  - job_name: gitlab-http
    metrics_path: /probe
    params:
      module: [http_2xx]
    static_configs:
      - targets:
          - https://${GITLAB_DOMAIN}/-/health
    relabel_configs:
      - source_labels: [__address__]
        target_label: __param_target
      - source_labels: [__param_target]
        target_label: instance
      - target_label: __address__
        replacement: 127.0.0.1:9115

  - job_name: watchdog-receiver
    static_configs:
      - targets: ['127.0.0.1:9099']
PROM
systemctl restart prometheus

# ---------------------------------------------------------------------------
# Watchdog webhook receiver — tiny Python service that records the most
# recent Watchdog arrival as a Prometheus-scrapeable metric
# ---------------------------------------------------------------------------

apt-get install -y python3 python3-pip
pip3 install --break-system-packages flask prometheus_client 2>/dev/null \
    || pip3 install flask prometheus_client

cat > /usr/local/bin/watchdog-receiver.py <<PYRECV
#!/usr/bin/env python3
"""Tiny webhook receiver for the GitLab-side Alertmanager Watchdog.

POST /watchdog?secret=<WEBHOOK_SECRET>
  - Records the current time as watchdog_received_timestamp.

GET /metrics
  - Prometheus scrape endpoint.

Listens on 127.0.0.1:9099 behind Caddy.
"""
import os
import time
from flask import Flask, request, abort
from prometheus_client import Gauge, generate_latest, CONTENT_TYPE_LATEST

WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "")
if not WEBHOOK_SECRET:
    raise SystemExit("WEBHOOK_SECRET env var not set")

app = Flask(__name__)
last_seen = Gauge("watchdog_received_timestamp",
                  "Unix time the last Watchdog alert was received")

@app.route("/watchdog", methods=["POST"])
def watchdog():
    if request.args.get("secret") != WEBHOOK_SECRET:
        abort(403)
    last_seen.set(time.time())
    return "ok\n"

@app.route("/metrics")
def metrics():
    return generate_latest(), 200, {"Content-Type": CONTENT_TYPE_LATEST}

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=9099)
PYRECV
chmod +x /usr/local/bin/watchdog-receiver.py

# Bake the secret into a systemd EnvironmentFile (root-only)
install -o root -g root -m 0600 /dev/null /etc/watchdog-receiver.env
cat > /etc/watchdog-receiver.env <<ENV
WEBHOOK_SECRET=${WEBHOOK_SECRET}
ENV

cat > /etc/systemd/system/watchdog-receiver.service <<'WSVC'
[Unit]
Description=Watchdog webhook receiver for GitLab observer
After=network-online.target

[Service]
Type=simple
EnvironmentFile=/etc/watchdog-receiver.env
ExecStart=/usr/local/bin/watchdog-receiver.py
DynamicUser=yes
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true

[Install]
WantedBy=multi-user.target
WSVC
systemctl daemon-reload
systemctl enable --now watchdog-receiver

# ---------------------------------------------------------------------------
# Caddy: TLS termination, reverse-proxy to the receiver
# ---------------------------------------------------------------------------

cat > /etc/caddy/Caddyfile <<CADDY
${OBSERVER_DOMAIN} {
    reverse_proxy /watchdog* 127.0.0.1:9099
    respond /healthz 200
    encode gzip
}
CADDY
systemctl restart caddy

# ---------------------------------------------------------------------------
# Alertmanager: dispatch to the operator destination
# ---------------------------------------------------------------------------

cat > /etc/alertmanager/alertmanager.yml <<AM
route:
  receiver: operator
  group_by: [alertname]
  group_wait: 30s
  group_interval: 5m
  repeat_interval: 1h

receivers:
  - name: operator
    webhook_configs:
      - url: ${ALERT_DEST}
        send_resolved: true
AM
# If ALERT_DEST is an email, replace webhook_configs with email_configs and
# fill in SMTP details. This script defaults to webhook for portability.
systemctl restart prometheus-alertmanager

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------

cat <<DONE

====================================================================
Observer installed.

Next steps (on the GITLAB server):

1. Configure on-box Alertmanager to dispatch the Watchdog alert to:
     https://${OBSERVER_DOMAIN}/watchdog?secret=<the secret you typed>

   Example alertmanager.yml route:
     route:
       routes:
         - matchers: [ alertname="Watchdog" ]
           receiver: external-observer
           group_interval: 5m
           repeat_interval: 5m
     receivers:
       - name: external-observer
         webhook_configs:
           - url: https://${OBSERVER_DOMAIN}/watchdog?secret=<SECRET>
             send_resolved: false

2. Wait ~10 minutes. Confirm the WatchdogNeverSeen alert clears on the
   observer (you'll see it transiently and then it goes away once the
   first Watchdog webhook arrives).

3. Test by stopping Alertmanager on the GitLab server for 11 minutes.
   The observer should fire WatchdogStale.

====================================================================
DONE
