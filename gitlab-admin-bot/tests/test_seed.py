"""Tests for the unified seed configuration system."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

# Allow importing from project-root scripts/
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_SCRIPTS_DIR = _PROJECT_ROOT / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import seed_bootstrap  # noqa: E402
import seed_schema  # noqa: E402

_generate_borg_conf = seed_bootstrap._generate_borg_conf
_generate_bot_config = seed_bootstrap._generate_bot_config
_generate_bot_env = seed_bootstrap._generate_bot_env
_generate_terraform_tfvars = seed_bootstrap._generate_terraform_tfvars
bootstrap_main = seed_bootstrap.main
SeedConfig = seed_schema.SeedConfig
_collect_placeholders = seed_schema._collect_placeholders

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_seed_dict(**overrides: Any) -> dict[str, Any]:
    """Return a minimal valid seed dict. Apply nested overrides via dotted keys."""
    seed: dict[str, Any] = {
        "version": 1,
        "organization": {
            "name": "Test Corp",
            "admin_email": "admin@test.com",
            "environment": "dev",
            "labels": {"project": "test"},
        },
        "infrastructure": {
            "hetzner": {
                "api_token": "hc-real-token-abcdef123456",
                "location": "fsn1",
            },
            "servers": {
                "gitlab": {"type": "cpx31", "image": "ubuntu-24.04", "private_ip": "10.0.1.10"},
                "admin_bot": {"type": "cx32", "image": "ubuntu-24.04", "private_ip": "10.0.1.30"},
            },
            "network": {"cidr": "10.0.0.0/16", "subnet_cidr": "10.0.1.0/24"},
            "storage": {"gitlab_data_volume_gb": 200, "gitlab_backup_volume_gb": 100},
            "ssh": {
                "admin_keys": {"alice": "ssh-ed25519 AAAAC3test alice@test.com"},
                "trusted_ips": ["10.0.0.1/32"],
            },
        },
        "gitlab": {
            "domain": "gitlab.test.com",
            "private_token": "glpat-realtoken12345678",
        },
        "backup": {
            "storage_box": {"host": "u12345.your-storagebox.de", "user": "u12345"},
            "borg": {"passphrase": "this-is-a-very-long-borg-passphrase-for-testing"},
            "retention": {
                "keep_hourly": 24,
                "keep_daily": 7,
                "keep_weekly": 4,
                "keep_monthly": 6,
            },
            "local_backup_path": "/var/opt/gitlab/backups",
            "max_backup_age_hours": 4,
        },
        "alerting": {
            "email": {
                "enabled": True,
                "smtp_host": "smtp.test.com",
                "smtp_port": 587,
                "smtp_user": "noreply@test.com",
                "smtp_password": "smtp-real-password",
                "from_address": "bot@test.com",
                "recipients": ["admin@test.com"],
            },
            "webhook": {"enabled": False, "url": ""},
            "cooldown_minutes": 60,
        },
        "claude": {
            "enabled": True,
            "api_key": "sk-ant-real-key-for-testing",
            "model": "claude-sonnet-4-20250514",
            "max_tokens": 4096,
            "analysis_interval_minutes": 30,
        },
        "bot": {
            "debug": False,
            "log_level": "INFO",
            "api_host": "0.0.0.0",
            "api_port": 8080,
        },
        "monitoring": {
            "disk_warning_percent": 80,
            "disk_critical_percent": 90,
            "memory_warning_percent": 80,
            "memory_critical_percent": 95,
            "cpu_warning_percent": 70,
            "cpu_critical_percent": 90,
            "health_check_interval_seconds": 30,
            "resource_check_interval_seconds": 60,
            "backup_check_interval_minutes": 15,
        },
    }
    # Apply simple top-level overrides (not nested dotted keys for simplicity)
    seed.update(overrides)
    return seed


@pytest.fixture()
def valid_seed_dict() -> dict[str, Any]:
    return _make_seed_dict()


@pytest.fixture()
def valid_seed(valid_seed_dict: dict[str, Any]) -> SeedConfig:
    return SeedConfig(**valid_seed_dict)


# ---------------------------------------------------------------------------
# Parsing & validation
# ---------------------------------------------------------------------------


class TestSeedValidation:
    def test_valid_seed_parses(self, valid_seed_dict: dict[str, Any]) -> None:
        seed = SeedConfig(**valid_seed_dict)
        assert seed.version == 1
        assert seed.organization.name == "Test Corp"

    def test_missing_required_field_fails(self, valid_seed_dict: dict[str, Any]) -> None:
        del valid_seed_dict["gitlab"]
        with pytest.raises((ValueError, TypeError)):
            SeedConfig(**valid_seed_dict)

    def test_missing_nested_required_field_fails(self, valid_seed_dict: dict[str, Any]) -> None:
        del valid_seed_dict["infrastructure"]["hetzner"]["api_token"]
        with pytest.raises((ValueError, TypeError)):
            SeedConfig(**valid_seed_dict)

    def test_invalid_environment_fails(self, valid_seed_dict: dict[str, Any]) -> None:
        valid_seed_dict["organization"]["environment"] = "invalid"
        with pytest.raises((ValueError, TypeError)):
            SeedConfig(**valid_seed_dict)

    def test_invalid_location_fails(self, valid_seed_dict: dict[str, Any]) -> None:
        valid_seed_dict["infrastructure"]["hetzner"]["location"] = "us-east-1"
        with pytest.raises((ValueError, TypeError)):
            SeedConfig(**valid_seed_dict)

    def test_short_borg_passphrase_fails(self, valid_seed_dict: dict[str, Any]) -> None:
        valid_seed_dict["backup"]["borg"]["passphrase"] = "tooshort"
        with pytest.raises(ValueError, match="borg.passphrase must be >= 20 characters"):
            SeedConfig(**valid_seed_dict)

    def test_borg_passphrase_exactly_20_passes(self, valid_seed_dict: dict[str, Any]) -> None:
        valid_seed_dict["backup"]["borg"]["passphrase"] = "a" * 20
        seed = SeedConfig(**valid_seed_dict)
        assert len(seed.backup.borg.passphrase) == 20

    def test_placeholder_secrets_fail(self) -> None:
        d = _make_seed_dict()
        d["infrastructure"]["hetzner"]["api_token"] = "SECRET:hetzner-api-token"
        with pytest.raises(ValueError, match="Placeholder secrets still present"):
            SeedConfig(**d)

    def test_placeholder_in_list_detected(self) -> None:
        d = _make_seed_dict()
        d["alerting"]["email"]["recipients"] = ["SECRET:alert-recipient"]
        with pytest.raises(ValueError, match="Placeholder secrets"):
            SeedConfig(**d)

    def test_placeholder_in_dict_detected(self) -> None:
        d = _make_seed_dict()
        d["infrastructure"]["ssh"]["admin_keys"] = {"alice": "SECRET:ssh-key"}
        with pytest.raises(ValueError, match="Placeholder secrets"):
            SeedConfig(**d)


# ---------------------------------------------------------------------------
# Derived values
# ---------------------------------------------------------------------------


class TestDerivedValues:
    def test_gitlab_url(self, valid_seed: SeedConfig) -> None:
        assert valid_seed.gitlab_url == "https://gitlab.test.com"

    def test_gitlab_ssh_host(self, valid_seed: SeedConfig) -> None:
        assert valid_seed.gitlab_ssh_host == "10.0.1.10"

    def test_borg_repo(self, valid_seed: SeedConfig) -> None:
        assert valid_seed.borg_repo == "ssh://u12345@u12345.your-storagebox.de:23/./gitlab-borg"


# ---------------------------------------------------------------------------
# Placeholder collector
# ---------------------------------------------------------------------------


class TestPlaceholderCollector:
    def test_no_placeholders_in_valid_seed(self, valid_seed: SeedConfig) -> None:
        # valid_seed passed validation, so this should be empty
        assert _collect_placeholders(valid_seed) == []

    def test_collects_scalar_placeholder(self) -> None:
        d = _make_seed_dict()
        # Bypass the model validator to test the collector directly
        d["infrastructure"]["hetzner"]["api_token"] = "real-token"
        d["gitlab"]["private_token"] = "SECRET:gitlab-token"
        # We can't create a SeedConfig (validator would reject), so test the
        # sub-model independently
        from seed_schema import GitLabConfig

        gl = GitLabConfig(**d["gitlab"])
        found = _collect_placeholders(gl)
        assert "private_token" in found


# ---------------------------------------------------------------------------
# Generators
# ---------------------------------------------------------------------------


class TestTerraformGenerator:
    def test_contains_hcloud_token(self, valid_seed: SeedConfig) -> None:
        content = _generate_terraform_tfvars(valid_seed)
        assert 'hcloud_token = "hc-real-token-abcdef123456"' in content

    def test_contains_domain(self, valid_seed: SeedConfig) -> None:
        content = _generate_terraform_tfvars(valid_seed)
        assert 'domain      = "gitlab.test.com"' in content

    def test_contains_ssh_keys(self, valid_seed: SeedConfig) -> None:
        content = _generate_terraform_tfvars(valid_seed)
        assert "alice" in content
        assert "ssh-ed25519" in content

    def test_contains_storage_box(self, valid_seed: SeedConfig) -> None:
        content = _generate_terraform_tfvars(valid_seed)
        assert 'storage_box_host = "u12345.your-storagebox.de"' in content

    def test_contains_server_types(self, valid_seed: SeedConfig) -> None:
        content = _generate_terraform_tfvars(valid_seed)
        assert 'gitlab_server_type    = "cpx31"' in content
        assert 'admin_bot_server_type = "cx32"' in content


class TestBotEnvGenerator:
    def test_contains_all_secrets(self, valid_seed: SeedConfig) -> None:
        content = _generate_bot_env(valid_seed)
        assert "GITLAB_PRIVATE_TOKEN=glpat-realtoken12345678" in content
        assert "HETZNER_API_TOKEN=hc-real-token-abcdef123456" in content
        assert "BORG_PASSPHRASE=this-is-a-very-long-borg-passphrase-for-testing" in content
        assert "SMTP_PASSWORD=smtp-real-password" in content
        assert "CLAUDE_API_KEY=sk-ant-real-key-for-testing" in content

    def test_contains_log_level(self, valid_seed: SeedConfig) -> None:
        content = _generate_bot_env(valid_seed)
        assert "LOG_LEVEL=INFO" in content


class TestBotConfigGenerator:
    def test_no_secrets_in_config(self, valid_seed: SeedConfig) -> None:
        content = _generate_bot_config(valid_seed)
        assert "glpat-" not in content
        assert "hc-real-token" not in content
        assert "borg-passphrase" not in content
        assert "smtp-real-password" not in content
        assert "sk-ant-" not in content

    def test_valid_yaml(self, valid_seed: SeedConfig) -> None:
        content = _generate_bot_config(valid_seed)
        parsed = yaml.safe_load(content)
        assert parsed is not None
        assert parsed["gitlab"]["url"] == "https://gitlab.test.com"
        assert parsed["gitlab"]["ssh_host"] == "10.0.1.10"

    def test_borg_repo_derived(self, valid_seed: SeedConfig) -> None:
        content = _generate_bot_config(valid_seed)
        parsed = yaml.safe_load(content)
        assert parsed["backup"]["borg_repo"] == (
            "ssh://u12345@u12345.your-storagebox.de:23/./gitlab-borg"
        )

    def test_monitoring_thresholds(self, valid_seed: SeedConfig) -> None:
        content = _generate_bot_config(valid_seed)
        parsed = yaml.safe_load(content)
        assert parsed["monitoring"]["disk_warning_percent"] == 80
        assert parsed["monitoring"]["cpu_critical_percent"] == 90


class TestBorgConfGenerator:
    def test_contains_borg_repo(self, valid_seed: SeedConfig) -> None:
        content = _generate_borg_conf(valid_seed)
        assert "BORG_REPO=" in content
        assert "u12345@u12345.your-storagebox.de:23" in content

    def test_contains_retention(self, valid_seed: SeedConfig) -> None:
        content = _generate_borg_conf(valid_seed)
        assert "BACKUP_KEEP_HOURLY=24" in content
        assert "BACKUP_KEEP_DAILY=7" in content
        assert "BACKUP_KEEP_WEEKLY=4" in content
        assert "BACKUP_KEEP_MONTHLY=6" in content

    def test_contains_borg_rsh(self, valid_seed: SeedConfig) -> None:
        content = _generate_borg_conf(valid_seed)
        assert "BORG_RSH=" in content
        assert "storagebox_key" in content


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


class TestIdempotency:
    def test_terraform_idempotent(self, valid_seed: SeedConfig) -> None:
        a = _generate_terraform_tfvars(valid_seed)
        b = _generate_terraform_tfvars(valid_seed)
        assert a == b

    def test_bot_env_idempotent(self, valid_seed: SeedConfig) -> None:
        a = _generate_bot_env(valid_seed)
        b = _generate_bot_env(valid_seed)
        assert a == b

    def test_bot_config_idempotent(self, valid_seed: SeedConfig) -> None:
        a = _generate_bot_config(valid_seed)
        b = _generate_bot_config(valid_seed)
        assert a == b

    def test_borg_conf_idempotent(self, valid_seed: SeedConfig) -> None:
        a = _generate_borg_conf(valid_seed)
        b = _generate_borg_conf(valid_seed)
        assert a == b


# ---------------------------------------------------------------------------
# seed.example.yaml
# ---------------------------------------------------------------------------


class TestExampleSeed:
    def test_example_is_valid_yaml(self) -> None:
        example = _PROJECT_ROOT / "seed.example.yaml"
        assert example.exists(), "seed.example.yaml must exist"
        with open(example) as f:
            data = yaml.safe_load(f)
        assert isinstance(data, dict)
        assert data["version"] == 1

    def test_example_fails_validation_due_to_placeholders(self) -> None:
        example = _PROJECT_ROOT / "seed.example.yaml"
        with open(example) as f:
            data = yaml.safe_load(f)
        with pytest.raises(ValueError, match="Placeholder secrets"):
            SeedConfig(**data)


# ---------------------------------------------------------------------------
# CLI (seed_bootstrap.main)
# ---------------------------------------------------------------------------


class TestCLI:
    def test_validate_valid_seed(self, valid_seed_dict: dict[str, Any], tmp_path: Path) -> None:
        seed_path = tmp_path / "seed.yaml"
        with open(seed_path, "w") as f:
            yaml.dump(valid_seed_dict, f)
        # Should not raise
        bootstrap_main(["str(seed_path)" if False else str(seed_path), "--validate"])

    def test_validate_invalid_seed_exits(self, tmp_path: Path) -> None:
        seed_path = tmp_path / "seed.yaml"
        with open(seed_path, "w") as f:
            yaml.dump({"version": 1}, f)
        with pytest.raises(SystemExit):
            bootstrap_main([str(seed_path), "--validate"])

    def test_target_requires_when_not_validate(
        self, valid_seed_dict: dict[str, Any], tmp_path: Path
    ) -> None:
        seed_path = tmp_path / "seed.yaml"
        with open(seed_path, "w") as f:
            yaml.dump(valid_seed_dict, f)
        with pytest.raises(SystemExit):
            bootstrap_main([str(seed_path)])

    def test_generate_all_creates_files(
        self, valid_seed_dict: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seed_path = tmp_path / "seed.yaml"
        with open(seed_path, "w") as f:
            yaml.dump(valid_seed_dict, f)

        # Monkeypatch _PROJECT_ROOT so files land in tmp_path
        import seed_bootstrap

        monkeypatch.setattr(seed_bootstrap, "_PROJECT_ROOT", tmp_path)

        # Create directories that generators write into
        (tmp_path / "terraform").mkdir()
        (tmp_path / "gitlab-admin-bot").mkdir()
        (tmp_path / "gitlab-admin-bot" / "config").mkdir()

        bootstrap_main([str(seed_path), "--target", "all", "--force"])

        assert (tmp_path / "terraform" / "terraform.tfvars").exists()
        assert (tmp_path / "gitlab-admin-bot" / ".env").exists()
        assert (tmp_path / "gitlab-admin-bot" / "config" / "config.yaml").exists()
