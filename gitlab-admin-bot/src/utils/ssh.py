"""SSH client for remote command execution."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import paramiko
import structlog

from src.config import GitLabSettings

logger = structlog.get_logger(__name__)


class SSHClient:
    """SSH client for executing commands on GitLab server."""

    def __init__(self, settings: GitLabSettings) -> None:
        self.settings = settings
        self._client: paramiko.SSHClient | None = None

    def _get_client(self) -> paramiko.SSHClient:
        """Get or create SSH client connection."""
        if self._client is None or not self._is_connected():
            self._client = paramiko.SSHClient()
            self._client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

            key_path = self.settings.ssh_key_path
            if not key_path.exists():
                raise FileNotFoundError(f"SSH key not found: {key_path}")

            private_key = paramiko.Ed25519Key.from_private_key_file(str(key_path))

            self._client.connect(
                hostname=self.settings.ssh_host,
                username=self.settings.ssh_user,
                pkey=private_key,
                timeout=30,
            )
            logger.debug(
                "SSH connection established",
                host=self.settings.ssh_host,
                user=self.settings.ssh_user,
            )

        return self._client

    def _is_connected(self) -> bool:
        """Check if SSH client is connected."""
        if self._client is None:
            return False
        transport = self._client.get_transport()
        return transport is not None and transport.is_active()

    async def run_command(
        self,
        command: str,
        timeout: int = 60,
    ) -> str:
        """
        Execute a command on the remote server.

        Args:
            command: The command to execute
            timeout: Command timeout in seconds

        Returns:
            Command output (stdout)

        Raises:
            Exception: If command fails or times out
        """
        # Run in thread pool to avoid blocking
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            self._run_command_sync,
            command,
            timeout,
        )

    def _run_command_sync(self, command: str, timeout: int) -> str:
        """Synchronous command execution."""
        client = self._get_client()

        logger.debug("Executing SSH command", command=command[:100])

        stdin, stdout, stderr = client.exec_command(command, timeout=timeout)

        # Wait for command to complete
        exit_status = stdout.channel.recv_exit_status()

        output = stdout.read().decode("utf-8")
        error = stderr.read().decode("utf-8")

        if exit_status != 0:
            logger.warning(
                "SSH command returned non-zero",
                command=command[:100],
                exit_status=exit_status,
                stderr=error[:500],
            )

        return output

    async def run_script(
        self,
        script_path: Path | str,
        args: list[str] | None = None,
        timeout: int = 300,
    ) -> str:
        """
        Execute a script on the remote server.

        Args:
            script_path: Path to script on remote server
            args: Script arguments
            timeout: Script timeout in seconds

        Returns:
            Script output
        """
        args_str = " ".join(args) if args else ""
        command = f"bash {script_path} {args_str}"
        return await self.run_command(command, timeout=timeout)

    async def check_file_exists(self, path: str) -> bool:
        """Check if a file exists on the remote server."""
        output = await self.run_command(f"test -f {path} && echo 'exists'")
        return "exists" in output

    async def get_file_info(self, path: str) -> dict[str, Any]:
        """Get file information."""
        if not await self.check_file_exists(path):
            return {"exists": False}

        stat_output = await self.run_command(f"stat -c '%s %Y %U %G' {path}")
        parts = stat_output.strip().split()

        if len(parts) >= 4:
            return {
                "exists": True,
                "size": int(parts[0]),
                "mtime": int(parts[1]),
                "owner": parts[2],
                "group": parts[3],
            }

        return {"exists": True, "raw": stat_output}

    def close(self) -> None:
        """Close the SSH connection."""
        if self._client:
            self._client.close()
            self._client = None
            logger.debug("SSH connection closed")
