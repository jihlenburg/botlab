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
    servers: ServersConfig
    network: NetworkConfig = Field(default_factory=NetworkConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    ssh: SSHConfig = Field(default_factory=SSHConfig)


class GitLabConfig(BaseModel):
    domain: str
    private_token: str
    # Pinned apt package version (e.g. "17.10.0-ce.0"). See seed.example.yaml.
    version: str = "17.10.0-ce.0"


class StorageBoxConfig(BaseModel):
    host: str
    user: str


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
