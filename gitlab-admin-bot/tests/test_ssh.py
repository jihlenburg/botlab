"""Tests for SSH client module."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import SecretStr

from src.config import GitLabSettings
from src.utils.ssh import SSHClient


class TestSSHClient:
    """Tests for SSHClient."""

    @pytest.fixture
    def ssh_settings(self, tmp_path):
        """Create SSH settings with a temporary key file."""
        # Create a fake key file
        key_file = tmp_path / "test_key"
        key_file.write_text("fake-key-content")

        return GitLabSettings(
            url="https://gitlab.test.local",
            private_token=SecretStr("test-token"),
            ssh_host="10.0.1.10",
            ssh_user="gitlab-admin",
            ssh_key_path=key_file,
        )

    @pytest.fixture
    def ssh_client(self, ssh_settings):
        """Create an SSHClient instance."""
        return SSHClient(ssh_settings)

    def test_initialization(self, ssh_client):
        """Test SSHClient initializes without connection."""
        assert ssh_client._client is None

    def test_is_connected_no_client(self, ssh_client):
        """Test _is_connected returns False when no client exists."""
        assert ssh_client._is_connected() is False

    def test_is_connected_with_active_transport(self, ssh_client):
        """Test _is_connected returns True with active transport."""
        mock_client = MagicMock()
        mock_transport = MagicMock()
        mock_transport.is_active.return_value = True
        mock_client.get_transport.return_value = mock_transport

        ssh_client._client = mock_client
        assert ssh_client._is_connected() is True

    def test_is_connected_with_inactive_transport(self, ssh_client):
        """Test _is_connected returns False with inactive transport."""
        mock_client = MagicMock()
        mock_transport = MagicMock()
        mock_transport.is_active.return_value = False
        mock_client.get_transport.return_value = mock_transport

        ssh_client._client = mock_client
        assert ssh_client._is_connected() is False

    def test_is_connected_no_transport(self, ssh_client):
        """Test _is_connected returns False when transport is None."""
        mock_client = MagicMock()
        mock_client.get_transport.return_value = None

        ssh_client._client = mock_client
        assert ssh_client._is_connected() is False

    def test_get_client_missing_key(self, ssh_settings):
        """Test _get_client raises when key file doesn't exist."""
        ssh_settings.ssh_key_path = Path("/nonexistent/key")
        client = SSHClient(ssh_settings)

        with pytest.raises(FileNotFoundError, match="SSH key not found"):
            client._get_client()

    def test_get_client_creates_connection(self, ssh_client, ssh_settings):
        """Test _get_client creates a new paramiko connection."""
        mock_paramiko_client = MagicMock()
        mock_key = MagicMock()

        with (
            patch("src.utils.ssh.paramiko.SSHClient", return_value=mock_paramiko_client),
            patch("src.utils.ssh.paramiko.Ed25519Key.from_private_key_file", return_value=mock_key),
        ):
            result = ssh_client._get_client()

        assert result is mock_paramiko_client
        mock_paramiko_client.connect.assert_called_once_with(
            hostname=ssh_settings.ssh_host,
            username=ssh_settings.ssh_user,
            pkey=mock_key,
            timeout=30,
        )

    def test_get_client_reuses_connection(self, ssh_client):
        """Test _get_client reuses existing active connection."""
        mock_client = MagicMock()
        mock_transport = MagicMock()
        mock_transport.is_active.return_value = True
        mock_client.get_transport.return_value = mock_transport

        ssh_client._client = mock_client

        result = ssh_client._get_client()
        assert result is mock_client

    def test_run_command_sync_success(self, ssh_client):
        """Test _run_command_sync with successful command."""
        mock_client = MagicMock()
        mock_stdin = MagicMock()
        mock_stdout = MagicMock()
        mock_stderr = MagicMock()

        mock_stdout.read.return_value = b"command output"
        mock_stdout.channel.recv_exit_status.return_value = 0
        mock_stderr.read.return_value = b""

        mock_client.exec_command.return_value = (mock_stdin, mock_stdout, mock_stderr)

        ssh_client._client = mock_client
        mock_transport = MagicMock()
        mock_transport.is_active.return_value = True
        mock_client.get_transport.return_value = mock_transport

        result = ssh_client._run_command_sync("echo hello", 60)

        assert result == "command output"
        mock_client.exec_command.assert_called_once_with("echo hello", timeout=60)

    def test_run_command_sync_nonzero_exit(self, ssh_client):
        """Test _run_command_sync with non-zero exit code still returns output."""
        mock_client = MagicMock()
        mock_stdin = MagicMock()
        mock_stdout = MagicMock()
        mock_stderr = MagicMock()

        mock_stdout.read.return_value = b"partial output"
        mock_stdout.channel.recv_exit_status.return_value = 1
        mock_stderr.read.return_value = b"some error"

        mock_client.exec_command.return_value = (mock_stdin, mock_stdout, mock_stderr)

        ssh_client._client = mock_client
        mock_transport = MagicMock()
        mock_transport.is_active.return_value = True
        mock_client.get_transport.return_value = mock_transport

        result = ssh_client._run_command_sync("failing_cmd", 60)

        assert result == "partial output"

    @pytest.mark.asyncio
    async def test_run_script(self, ssh_client):
        """Test run_script constructs correct command."""
        ssh_client.run_command = AsyncMock(return_value="script output")

        await ssh_client.run_script("/usr/local/bin/backup.sh", args=["--verbose"])

        ssh_client.run_command.assert_called_once_with(
            "bash /usr/local/bin/backup.sh --verbose", timeout=300
        )

    @pytest.mark.asyncio
    async def test_run_script_no_args(self, ssh_client):
        """Test run_script without arguments."""
        ssh_client.run_command = AsyncMock(return_value="ok")

        await ssh_client.run_script("/usr/local/bin/backup.sh")

        ssh_client.run_command.assert_called_once_with(
            "bash /usr/local/bin/backup.sh ", timeout=300
        )

    @pytest.mark.asyncio
    async def test_check_file_exists_true(self, ssh_client):
        """Test check_file_exists when file exists."""
        ssh_client.run_command = AsyncMock(return_value="exists")

        result = await ssh_client.check_file_exists("/etc/gitlab/gitlab.rb")
        assert result is True

    @pytest.mark.asyncio
    async def test_check_file_exists_false(self, ssh_client):
        """Test check_file_exists when file does not exist."""
        ssh_client.run_command = AsyncMock(return_value="")

        result = await ssh_client.check_file_exists("/nonexistent/file")
        assert result is False

    def test_close(self, ssh_client):
        """Test closing the SSH connection."""
        mock_client = MagicMock()
        ssh_client._client = mock_client

        ssh_client.close()

        mock_client.close.assert_called_once()
        assert ssh_client._client is None

    def test_close_when_not_connected(self, ssh_client):
        """Test closing when no connection exists (no-op)."""
        ssh_client.close()
        assert ssh_client._client is None
