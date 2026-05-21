"""Pydantic validation model for seed.yaml configuration."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field, model_validator


# ---------------------------------------------------------------------------
# Placeholder detection
# ---------------------------------------------------------------------------

_PLACEHOLDER_RE = re.compile(r"^SECRET:")


def _has_placeholder(value: str) -> bool:
    return bool(_PLACEHOLDER_RE.match(value))


# ---------------------------------------------------------------------------
# Sub-models
# ---------------------------------------------------------------------------


class OrganizationConfig(BaseModel):
    name: str
    admin_email: str
    environment: Literal["prod", "staging", "dev"] = "prod"
    labels: dict[str, str] = Field(default_factory=dict)


class HetznerConfig(BaseModel):
    api_token: str
    location: Literal["fsn1", "nbg1", "hel1"] = "fsn1"


class TerraformStateConfig(BaseModel):
    """Remote Terraform state backend (Hetzner Object Storage, S3-compatible).

    Closes security review T1.2. NOT the same as backup.s3 (which is the
    immutable backup tier and must live off-Hetzner). State on Hetzner is
    acceptable because we ALSO snapshot to the offline recovery kit after
    every `terraform apply`. See docs/DEPLOY.md §0 and §3.
    """

    bucket: str
    endpoint: str
    access_key: str
    secret_key: str


class ServerSpec(BaseModel):
    type: str
    image: str = "ubuntu-24.04"
    private_ip: str


class ServersConfig(BaseModel):
    gitlab: ServerSpec


class NetworkConfig(BaseModel):
    cidr: str = "10.0.0.0/16"
    subnet_cidr: str = "10.0.1.0/24"


class StorageConfig(BaseModel):
    gitlab_data_volume_gb: int = 200
    gitlab_backup_volume_gb: int = 100


class SSHConfig(BaseModel):
    admin_keys: dict[str, str] = Field(default_factory=dict)
    trusted_ips: list[str] = Field(default_factory=list)


class InfrastructureConfig(BaseModel):
    hetzner: HetznerConfig
    terraform_state: TerraformStateConfig
    servers: ServersConfig
    network: NetworkConfig = Field(default_factory=NetworkConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    ssh: SSHConfig = Field(default_factory=SSHConfig)


class GitLabConfig(BaseModel):
    domain: str
    # Pinned apt package version (e.g. "17.10.0-ce.0"). See seed.template.yaml.
    version: str = "17.10.0-ce.0"
    # NOTE: a global `private_token` field was deliberately removed in v2.2.
    # Per-cron-job tokens should be generated on demand against the live
    # GitLab API with the narrowest scope they need, then stored via
    # systemd-creds for the specific timer that uses them. See DESIGN.md
    # Appendix C ("Layered Secrets Management") for the pattern.


class StorageBoxConfig(BaseModel):
    # ---- Provisioning intent (used to generate terraform.tfvars) -----------
    # These flow into the hcloud_storage_box / hcloud_storage_box_subaccount
    # resources in terraform/storage_box.tf. The Storage Box product is now
    # in the Hetzner Cloud Console (no separate Robot account required, as
    # of provider v1.63.0, May 2026).
    name: str = "acme-gitlab-backups"
    type: Literal["bx11", "bx21", "bx31", "bx41"] = "bx21"
    location: Literal["fsn1", "nbg1", "hel1"] = "fsn1"

    # Primary Storage Box password — used for emergency Hetzner Console
    # access only. Day-to-day Borg backups authenticate via SSH key.
    password: str = ""

    # OPERATOR'S OFFLINE full-access public key. Private half MUST live only
    # in the offline recovery kit (DEPLOY.md §2a, OFFLINE-KIT-TEMPLATE §2).
    ssh_public_key: str = ""

    # Password for the append-only sub-account — used once by
    # setup-borg-append-only.sh to SFTP in and install the forced-command
    # authorized_keys file.
    subaccount_password: str = ""

    # ---- Runtime values (filled in AFTER `terraform apply`) ----------------
    # Operator pastes these from `terraform output storage_box_post_apply`.
    # Optional (empty default) so seed validation passes before first apply;
    # the borg-conf generator refuses to run if they're still empty post-apply.
    host: str = ""
    user: str = ""


class BorgConfig(BaseModel):
    passphrase: str


class RetentionConfig(BaseModel):
    keep_hourly: int = 24
    keep_daily: int = 7
    keep_weekly: int = 4
    keep_monthly: int = 12


class S3BackupConfig(BaseModel):
    enabled: bool = False
    endpoint: str = ""
    bucket: str = ""
    access_key: str = ""
    secret_key: str = ""
    retention_days: int = 90


class BackupConfig(BaseModel):
    storage_box: StorageBoxConfig
    borg: BorgConfig
    retention: RetentionConfig = Field(default_factory=RetentionConfig)
    s3: S3BackupConfig = Field(default_factory=S3BackupConfig)
    local_backup_path: str = "/var/opt/gitlab/backups"
    max_backup_age_hours: int = 4


class EmailAlertConfig(BaseModel):
    enabled: bool = True
    smtp_host: str = "smtp.office365.com"
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    from_address: str = ""
    recipients: list[str] = Field(default_factory=list)


class WebhookAlertConfig(BaseModel):
    enabled: bool = False
    url: str = ""


class AlertingConfig(BaseModel):
    email: EmailAlertConfig = Field(default_factory=EmailAlertConfig)
    webhook: WebhookAlertConfig = Field(default_factory=WebhookAlertConfig)
    cooldown_minutes: int = 60


# ---------------------------------------------------------------------------
# Root model
# ---------------------------------------------------------------------------


class SeedConfig(BaseModel):
    """Root model for seed.yaml — single source of truth for all config."""

    version: int
    organization: OrganizationConfig
    infrastructure: InfrastructureConfig
    gitlab: GitLabConfig
    backup: BackupConfig
    alerting: AlertingConfig = Field(default_factory=AlertingConfig)

    # -- Derived values (computed, not stored) -----------------------------

    @property
    def gitlab_url(self) -> str:
        return f"https://{self.gitlab.domain}"

    @property
    def borg_repo(self) -> str:
        sb = self.backup.storage_box
        return f"ssh://{sb.user}@{sb.host}:23/./gitlab-borg"

    # -- Validators --------------------------------------------------------

    @model_validator(mode="after")
    def _validate_constraints(self) -> SeedConfig:
        errors: list[str] = []

        # Borg passphrase length
        pp = self.backup.borg.passphrase
        if not _has_placeholder(pp) and len(pp) < 20:
            errors.append(
                f"backup.borg.passphrase must be >= 20 characters (got {len(pp)})"
            )

        # Terraform state backend (T1.2): bucket name + endpoint shape
        tfs = self.infrastructure.terraform_state
        if not _has_placeholder(tfs.bucket):
            # S3-compatible bucket naming rules (3-63 chars, lowercase + digits
            # + hyphens + dots, must start/end with alphanumeric)
            if not re.match(r"^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$", tfs.bucket):
                errors.append(
                    f"infrastructure.terraform_state.bucket '{tfs.bucket}' is not a "
                    "valid S3 bucket name (3-63 chars, lowercase alphanumeric + . - , "
                    "must start and end alphanumeric)."
                )
        if not _has_placeholder(tfs.endpoint):
            if not tfs.endpoint.startswith("https://"):
                errors.append(
                    f"infrastructure.terraform_state.endpoint '{tfs.endpoint}' must "
                    "be an https:// URL (the Hetzner Object Storage region endpoint, "
                    "e.g. https://fsn1.your-objectstorage.com)."
                )
        # Reject explicit-empty credentials when they're not placeholders.
        # (Empty + placeholder is the pre-fill state; both empty + non-placeholder
        # means the operator cleared the field.)
        for fname in ("access_key", "secret_key"):
            val = getattr(tfs, fname)
            if val == "":
                errors.append(
                    f"infrastructure.terraform_state.{fname} is empty. Mint S3 "
                    "credentials via Hetzner Console (Security → S3 Credentials → "
                    "Generate credentials) and paste them in. See DEPLOY.md §0."
                )

        # Storage Box passwords — match the validation in terraform/variables.tf
        sb = self.backup.storage_box
        if sb.password and not _has_placeholder(sb.password) and len(sb.password) < 20:
            errors.append(
                f"backup.storage_box.password must be >= 20 characters (got {len(sb.password)})"
            )
        if (
            sb.subaccount_password
            and not _has_placeholder(sb.subaccount_password)
            and len(sb.subaccount_password) < 20
        ):
            errors.append(
                "backup.storage_box.subaccount_password must be >= 20 characters "
                f"(got {len(sb.subaccount_password)})"
            )

        # Storage Box SSH public key format (offline full-access key)
        if sb.ssh_public_key and not _has_placeholder(sb.ssh_public_key):
            if not re.match(
                r"^(ssh-ed25519|ssh-rsa|ecdsa-sha2-nistp\d+) [A-Za-z0-9+/=]+",
                sb.ssh_public_key,
            ):
                errors.append(
                    "backup.storage_box.ssh_public_key must be a valid OpenSSH-format "
                    "public key (ssh-ed25519, ssh-rsa, or ecdsa-sha2-nistp*). "
                    "This is the OFFLINE full-access key — see DEPLOY.md §2a."
                )

        # T2.1 from SECURITY-REVIEW-2026-05-15: refuse Hetzner endpoints for
        # the S3 immutable tier. The whole point of that tier is to live
        # outside the Hetzner account in case of account-level compromise
        # or lockout. Using Hetzner Object Storage as the "immutable" tier
        # defeats it.
        s3 = self.backup.s3
        if s3.enabled and not _has_placeholder(s3.endpoint):
            endpoint_lc = s3.endpoint.lower()
            if (
                "hetzner" in endpoint_lc
                or "your-objectstorage.com" in endpoint_lc  # Hetzner OS hostname
                or "fsn1." in endpoint_lc
                or "nbg1." in endpoint_lc
                or "hel1." in endpoint_lc
            ):
                errors.append(
                    f"backup.s3.endpoint '{s3.endpoint}' looks like Hetzner "
                    "Object Storage. The S3 immutable tier MUST live on a "
                    "different provider (Wasabi, Backblaze B2, AWS S3, etc.) "
                    "to survive Hetzner account-level incidents. "
                    "See docs/DESIGN.md §9.3 and SECURITY-REVIEW-2026-05-15.md T2.1."
                )

        # Placeholder detection — refuse if any SECRET: values remain
        placeholders = _collect_placeholders(self)
        if placeholders:
            paths = ", ".join(placeholders[:10])
            suffix = f" (and {len(placeholders) - 10} more)" if len(placeholders) > 10 else ""
            errors.append(
                f"Placeholder secrets still present: {paths}{suffix}. "
                "Replace all SECRET:* values with real credentials."
            )

        if errors:
            raise ValueError("; ".join(errors))

        return self


def _collect_placeholders(  # noqa: C901
    obj: BaseModel, prefix: str = ""
) -> list[str]:
    """Walk the model tree and return dotted paths of placeholder values."""
    found: list[str] = []
    for name, _field_info in type(obj).model_fields.items():
        value = getattr(obj, name)
        dotted = f"{prefix}.{name}" if prefix else name
        if isinstance(value, str) and _has_placeholder(value):
            found.append(dotted)
        elif isinstance(value, BaseModel):
            found.extend(_collect_placeholders(value, dotted))
        elif isinstance(value, list):
            for i, item in enumerate(value):
                if isinstance(item, str) and _has_placeholder(item):
                    found.append(f"{dotted}[{i}]")
        elif isinstance(value, dict):
            for k, v in value.items():
                if isinstance(v, str) and _has_placeholder(v):
                    found.append(f"{dotted}.{k}")
    return found
