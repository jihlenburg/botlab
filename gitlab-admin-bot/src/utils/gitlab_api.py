"""GitLab API client wrapper."""

from __future__ import annotations

from typing import Any

import gitlab
import structlog

from src.config import GitLabSettings

logger = structlog.get_logger(__name__)


class GitLabClient:
    """Wrapper around python-gitlab for GitLab API access."""

    def __init__(self, settings: GitLabSettings) -> None:
        self.settings = settings
        self.url = settings.url
        self._gl: gitlab.Gitlab | None = None

    @property
    def gl(self) -> gitlab.Gitlab:
        """Get or create GitLab API client."""
        if self._gl is None:
            self._gl = gitlab.Gitlab(
                url=self.settings.url,
                private_token=self.settings.private_token.get_secret_value(),
            )
        return self._gl

    def auth(self) -> bool:
        """Authenticate with GitLab."""
        try:
            self.gl.auth()
            logger.info("GitLab authentication successful")
            return True
        except gitlab.exceptions.GitlabAuthenticationError as e:
            logger.error("GitLab authentication failed", error=str(e))
            return False

    def get_version(self) -> tuple[str, str]:
        """Get GitLab version information."""
        return self.gl.version()

    def get_health(self) -> dict[str, Any]:
        """Get GitLab health status via API."""
        try:
            # Use the application settings endpoint as a health indicator
            self.gl.settings.get()
            return {
                "healthy": True,
                "version": self.gl.version(),
            }
        except Exception as e:
            return {
                "healthy": False,
                "error": str(e),
            }

    def list_projects(self, limit: int = 100) -> list[dict[str, Any]]:
        """List GitLab projects."""
        projects = self.gl.projects.list(per_page=limit)
        return [
            {
                "id": p.id,
                "name": p.name,
                "path_with_namespace": p.path_with_namespace,
                "visibility": p.visibility,
            }
            for p in projects
        ]

    def list_users(self, limit: int = 100) -> list[dict[str, Any]]:
        """List GitLab users."""
        users = self.gl.users.list(per_page=limit)
        return [
            {
                "id": u.id,
                "username": u.username,
                "email": u.email,
                "state": u.state,
                "is_admin": getattr(u, "is_admin", False),
            }
            for u in users
        ]

    def get_system_info(self) -> dict[str, Any]:
        """Get system information."""
        try:
            # GitLab CE doesn't have full system info API
            # Use available endpoints
            return {
                "version": self.gl.version(),
                "projects_count": len(self.gl.projects.list(per_page=1, get_all=False)),
                "users_count": len(self.gl.users.list(per_page=1, get_all=False)),
            }
        except Exception as e:
            logger.error("Failed to get system info", error=str(e))
            return {"error": str(e)}

    def trigger_backup(self) -> bool:
        """
        Trigger a GitLab backup.

        Note: GitLab CE doesn't have a backup API endpoint.
        This must be done via SSH/command execution.
        """
        logger.warning("Backup cannot be triggered via API, use SSH instead")
        return False
