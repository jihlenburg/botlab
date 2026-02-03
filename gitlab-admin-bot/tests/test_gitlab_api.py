"""Tests for GitLab API client module."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.utils.gitlab_api import GitLabClient


class TestGitLabClient:
    """Tests for GitLabClient."""

    @pytest.fixture
    def client(self, gitlab_settings):
        """Create a GitLabClient with test settings."""
        return GitLabClient(gitlab_settings)

    def test_initialization(self, client, gitlab_settings):
        """Test GitLabClient initializes correctly."""
        assert client.url == gitlab_settings.url
        assert client._gl is None

    def test_gl_property_creates_client(self, client):
        """Test that gl property creates a gitlab.Gitlab instance."""
        with patch("src.utils.gitlab_api.gitlab.Gitlab") as mock_gitlab:
            mock_instance = MagicMock()
            mock_gitlab.return_value = mock_instance

            result = client.gl

            assert result is mock_instance
            mock_gitlab.assert_called_once_with(
                url=client.settings.url,
                private_token=client.settings.private_token.get_secret_value(),
            )

    def test_gl_property_caches(self, client):
        """Test that gl property returns cached instance."""
        mock_instance = MagicMock()
        client._gl = mock_instance

        assert client.gl is mock_instance

    def test_auth_success(self, client):
        """Test successful authentication."""
        mock_gl = MagicMock()
        client._gl = mock_gl

        result = client.auth()

        assert result is True
        mock_gl.auth.assert_called_once()

    def test_auth_failure(self, client):
        """Test authentication failure."""
        import gitlab.exceptions

        mock_gl = MagicMock()
        mock_gl.auth.side_effect = gitlab.exceptions.GitlabAuthenticationError(
            response_code=401, error_message="Unauthorized"
        )
        client._gl = mock_gl

        result = client.auth()

        assert result is False

    def test_get_version(self, client):
        """Test getting GitLab version."""
        mock_gl = MagicMock()
        mock_gl.version.return_value = ("16.8.0", "16.8.0-ee")
        client._gl = mock_gl

        result = client.get_version()

        assert result == ("16.8.0", "16.8.0-ee")

    def test_get_health_success(self, client):
        """Test getting health status when GitLab is healthy."""
        mock_gl = MagicMock()
        mock_gl.version.return_value = ("16.8.0", "16.8.0-ee")
        mock_gl.settings.get.return_value = MagicMock()
        client._gl = mock_gl

        result = client.get_health()

        assert result["healthy"] is True
        assert "version" in result

    def test_get_health_failure(self, client):
        """Test getting health status when GitLab is down."""
        mock_gl = MagicMock()
        mock_gl.settings.get.side_effect = ConnectionError("Connection refused")
        client._gl = mock_gl

        result = client.get_health()

        assert result["healthy"] is False
        assert "Connection refused" in result["error"]

    def test_list_projects(self, client):
        """Test listing projects."""
        mock_project = MagicMock()
        mock_project.id = 1
        mock_project.name = "test-project"
        mock_project.path_with_namespace = "group/test-project"
        mock_project.visibility = "private"

        mock_gl = MagicMock()
        mock_gl.projects.list.return_value = [mock_project]
        client._gl = mock_gl

        result = client.list_projects(limit=50)

        assert len(result) == 1
        assert result[0]["id"] == 1
        assert result[0]["name"] == "test-project"
        assert result[0]["path_with_namespace"] == "group/test-project"
        mock_gl.projects.list.assert_called_once_with(per_page=50)

    def test_list_users(self, client):
        """Test listing users."""
        mock_user = MagicMock()
        mock_user.id = 1
        mock_user.username = "admin"
        mock_user.email = "admin@test.local"
        mock_user.state = "active"
        mock_user.is_admin = True

        mock_gl = MagicMock()
        mock_gl.users.list.return_value = [mock_user]
        client._gl = mock_gl

        result = client.list_users()

        assert len(result) == 1
        assert result[0]["username"] == "admin"
        assert result[0]["is_admin"] is True

    def test_get_system_info_success(self, client):
        """Test getting system information."""
        mock_gl = MagicMock()
        mock_gl.version.return_value = ("16.8.0", "16.8.0-ee")
        mock_gl.projects.list.return_value = [MagicMock()]
        mock_gl.users.list.return_value = [MagicMock(), MagicMock()]
        client._gl = mock_gl

        result = client.get_system_info()

        assert result["version"] == ("16.8.0", "16.8.0-ee")
        assert result["projects_count"] == 1
        assert result["users_count"] == 2

    def test_get_system_info_failure(self, client):
        """Test getting system info when API fails."""
        mock_gl = MagicMock()
        mock_gl.version.side_effect = ConnectionError("API unavailable")
        client._gl = mock_gl

        result = client.get_system_info()

        assert "error" in result

    def test_trigger_backup_returns_false(self, client):
        """Test that trigger_backup returns False (not available via API)."""
        result = client.trigger_backup()
        assert result is False
