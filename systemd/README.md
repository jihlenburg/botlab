# systemd units

Service + timer pairs for the GitLab server's scheduled jobs. Install during
Phase 4 by copying each unit to `/etc/systemd/system/`, then:

```bash
systemctl daemon-reload
systemctl enable --now gitlab-borg-check.timer
systemctl enable --now gitlab-restore-test.timer
systemctl enable --now gitlab-break-glass-verify.timer
# Optional Layer-2 migration of the hourly backup from cron to systemd:
systemctl enable --now gitlab-backup.timer
# (then remove /etc/cron.d/gitlab-backup)
```

Each unit reads its primary credential via `LoadCredentialEncrypted=` from
`/etc/credstore.encrypted/` per DESIGN.md Appendix C.4 (Layer 2 secrets).
The encrypted credential files are populated once with `systemd-creds
encrypt --with-key=host` — see Appendix C.4 for the commands.

| Unit | Cadence | What it runs |
|------|---------|--------------|
| `gitlab-backup` | hourly | `/usr/local/bin/gitlab-backup-to-borg.sh` |
| `gitlab-borg-check` | weekly (Sun 04:00) | `/opt/botlab/scripts/borg-check.sh` |
| `gitlab-restore-test` | weekly (Sun 02:00) | `/opt/botlab/scripts/restore-test.sh` |
| `gitlab-break-glass-verify` | monthly | `/opt/botlab/scripts/verify-break-glass.sh` |

The `RandomizedDelaySec=` on each timer spreads load if multiple units
ever land in the same minute. `Persistent=true` runs missed jobs on the
next boot (matters when the box was down at the scheduled time).
