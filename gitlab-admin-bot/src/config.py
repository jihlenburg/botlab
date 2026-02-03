"""Configuration management for GitLab Admin Bot."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class GitLabSettings(BaseSettings):
    """GitLab connection settings."""

    url: str = Field(default="https://gitlab.example.com")
    private_token: SecretStr = Field(default=...)
    ssh_host: str = Field(default="10.0.1.10")
    ssh_user: str = Field(default="gitlab-admin")
    ssh_key_path: Path = Field(default=Path("/root/.ssh/admin_bot_key"))


class HetznerSettings(BaseSettings):
    """Hetzner Cloud settings."""

    api_token: SecretStr = Field(default=...)
    location: str = Field(default="fsn1")


class BackupSettings(BaseSettings):
    """Backup configuration."""

    borg_repo: str = Field(default="")
    borg_passphrase: SecretStr = Field(default=SecretStr(""))
    local_backup_path: Path = Field(default=Path("/var/opt/gitlab/backups"))
    max_backup_age_hours: int = Field(default=4)


class AlertingSettings(BaseSettings):
    """Alerting configuration."""

    email_enabled: bool = Field(default=True)
    email_smtp_host: str = Field(default="smtp.office365.com")
    email_smtp_port: int = Field(default=587)
    email_smtp_user: str = Field(default="")
    email_smtp_password: SecretStr = Field(default=SecretStr(""))
    email_from: str = Field(default="gitlab-admin-bot@example.com")
    email_recipients: list[str] = Field(default_factory=list)

    webhook_enabled: bool = Field(default=False)
    webhook_url: str = Field(default="")

    cooldown_minutes: int = Field(default=60)


class ClaudeSettings(BaseSettings):
    """Claude API settings for AI-powered admin decisions."""

    enabled: bool = Field(default=True)
    api_key: SecretStr = Field(default=...)
    model: str = Field(default="claude-sonnet-4-20250514")
    max_tokens: int = Field(default=4096)
    analysis_interval_minutes: int = Field(default=30)

    # CLI mode settings (use Claude Code CLI instead of SDK)
    use_cli: bool = Field(default=False, description="Use Claude Code CLI instead of SDK")
    cli_path: str = Field(default="claude", description="Path to Claude CLI executable")
    cli_timeout: int = Field(default=120, description="CLI invocation timeout in seconds")


class MonitoringSettings(BaseSettings):
    """Monitoring thresholds."""

    disk_warning_percent: int = Field(default=80)
    disk_critical_percent: int = Field(default=90)
    memory_warning_percent: int = Field(default=80)
    memory_critical_percent: int = Field(default=95)
    cpu_warning_percent: int = Field(default=70)
    cpu_critical_percent: int = Field(default=90)
    health_check_interval_seconds: int = Field(default=30)
    resource_check_interval_seconds: int = Field(default=60)
    backup_check_interval_minutes: int = Field(default=15)


class Settings(BaseSettings):
    """Main application settings."""

    model_config = SettingsConfigDict(
        env_prefix="ADMIN_BOT_",
        env_nested_delimiter="__",
        env_file=".env",
    )

    # Application
    app_name: str = Field(default="GitLab Admin Bot")
    debug: bool = Field(default=False)
    log_level: str = Field(default="INFO")

    # API server
    api_host: str = Field(default="0.0.0.0")
    api_port: int = Field(default=8080)

    # Data storage
    data_dir: Path = Field(default=Path("/opt/gitlab-admin-bot/data"))
    db_path: Path = Field(default=Path("/opt/gitlab-admin-bot/data/admin_bot.db"))

    # Nested settings
    gitlab: GitLabSettings = Field(default_factory=GitLabSettings)
    hetzner: HetznerSettings = Field(default_factory=HetznerSettings)
    backup: BackupSettings = Field(default_factory=BackupSettings)
    alerting: AlertingSettings = Field(default_factory=AlertingSettings)
    claude: ClaudeSettings = Field(default_factory=ClaudeSettings)
    monitoring: MonitoringSettings = Field(default_factory=MonitoringSettings)


def load_config(config_path: Path | None = None) -> Settings:
    """Load configuration from YAML file and environment variables.

    YAML values are used as defaults; environment variables take precedence
    (handled by pydantic-settings).
    """
    if config_path and config_path.exists():
        with open(config_path) as f:
            yaml_config = yaml.safe_load(f)
            if yaml_config and isinstance(yaml_config, dict):
                return Settings.model_validate(yaml_config)

    return Settings()


# Global settings instance
_settings: Settings | None = None


def get_settings() -> Settings:
    """Get the global settings instance."""
    global _settings
    if _settings is None:
        _settings = load_config()
    return _settings
