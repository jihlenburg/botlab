# `scripts/vendor/` — third-party scripts pinned by checksum

Vendored copies of upstream scripts that cloud-init runs at first boot.
Pinned here so they cannot change between when we audited them and when
the server runs them. Closes security review **T1.6** (2026-05-15) —
the `curl … | bash` anti-pattern.

## Contents

| File | Upstream | Audited at | sha256 |
|------|----------|-----------:|--------|
| `install-gitlab-repo.sh` | `https://packages.gitlab.com/install/repositories/gitlab/gitlab-ce/script.deb.sh` | 2026-05-18 | `3f6a403e…2e8d30b` (full in `CHECKSUMS`) |

## How cloud-init consumes these

`terraform/servers.tf` reads each vendored file at `terraform apply` time,
base64-encodes it, and passes it into the cloud-init template:

```hcl
user_data = templatefile("…/gitlab-cloud-init.yaml", {
  install_gitlab_repo_sh_b64 = base64encode(file("${path.module}/../scripts/vendor/install-gitlab-repo.sh"))
  …
})
```

The cloud-init template then drops the script at
`/usr/local/bin/install-gitlab-repo.sh` via `write_files` (`encoding: b64`)
and runs it from `runcmd`. No network fetch happens at first boot for the
repo install.

## CI verification

`.github/workflows/test.yml` runs `sha256sum -c CHECKSUMS` from this
directory on every push. If anyone edits a vendored file (intentionally
or otherwise) without refreshing `CHECKSUMS`, CI fails.

## Refresh procedure (quarterly, per security-review cadence)

1. `cd scripts/vendor/`
2. `curl -fsSL https://packages.gitlab.com/install/repositories/gitlab/gitlab-ce/script.deb.sh -o install-gitlab-repo.sh.new`
3. **Diff** against the existing copy: `diff -u install-gitlab-repo.sh install-gitlab-repo.sh.new` — eyeball every change; refuse anything that introduces calls to hosts other than `packages.gitlab.com` / `docs.gitlab.com`, or that adds `eval` / opaque `base64` decoding.
4. If the diff is clean: `mv install-gitlab-repo.sh.new install-gitlab-repo.sh`
5. Recompute checksum: `sha256sum install-gitlab-repo.sh > CHECKSUMS`
6. Update the "Audited at" date and the sha256 short prefix in this README's table.
7. Commit with a message that names the upstream date and the new checksum, e.g. `chore(vendor): refresh install-gitlab-repo.sh (2026-08-15, sha256 abc…)`.
