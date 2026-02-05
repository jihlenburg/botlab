"""Extended tests for disaster recovery module to increase coverage."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.restore.recovery import RecoveryManager
from src.restore.tester import RestoreTester


# Patch asyncio.sleep globally for faster tests
@pytest.fixture(autouse=True)
def fast_sleep():
    """Speed up tests by making asyncio.sleep instant."""
    with patch("asyncio.sleep", new_callable=AsyncMock):
        yield


class TestRecoveryManagerExtended:
    """Extended tests for RecoveryManager to increase coverage."""

    @pytest.fixture
    def recovery_manager(
        self,
        hetzner_settings,
        backup_settings,
        gitlab_settings,
        mock_alert_manager,
        mock_hcloud_client,
    ):
        """Create a RecoveryManager with mocked dependencies."""
        with patch("hcloud.Client", return_value=mock_hcloud_client):
            manager = RecoveryManager(
                hetzner_settings=hetzner_settings,
                backup_settings=backup_settings,
                gitlab_settings=gitlab_settings,
                alert_manager=mock_alert_manager,
            )
            manager.hcloud = mock_hcloud_client
            return manager

    @pytest.mark.asyncio
    async def test_provision_recovery_server(self, recovery_manager, mock_hcloud_client):
        """Test provisioning a recovery server."""
        with (
            patch.object(recovery_manager, "_wait_for_action", new_callable=AsyncMock),
            patch.object(recovery_manager, "_wait_for_ssh", new_callable=AsyncMock),
        ):
            server = await recovery_manager._provision_recovery_server()

        assert server is not None
        mock_hcloud_client.servers.create.assert_called_once()
        call_kwargs = mock_hcloud_client.servers.create.call_args.kwargs
        assert "gitlab-recovery-" in call_kwargs["name"]
        assert call_kwargs["labels"]["purpose"] == "gitlab-recovery"

    @pytest.mark.asyncio
    async def test_wait_for_ssh_success(self, recovery_manager):
        """Test waiting for SSH to become available."""
        with patch("socket.socket") as mock_socket:
            mock_sock = MagicMock()
            mock_sock.connect_ex.return_value = 0
            mock_socket.return_value = mock_sock

            await recovery_manager._wait_for_ssh("10.0.0.1", timeout=10)

            mock_sock.close.assert_called()

    @pytest.mark.asyncio
    async def test_wait_for_ssh_timeout(self, recovery_manager):
        """Test SSH wait timeout."""
        with patch("socket.socket") as mock_socket:
            mock_sock = MagicMock()
            mock_sock.connect_ex.return_value = 1  # Connection refused
            mock_socket.return_value = mock_sock

            with pytest.raises(TimeoutError, match="SSH not available"):
                await recovery_manager._wait_for_ssh("10.0.0.1", timeout=1)

    @pytest.mark.asyncio
    async def test_wait_for_ssh_os_error(self, recovery_manager):
        """Test SSH wait handles OSError."""
        call_count = 0

        def mock_connect_ex(*args):
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise OSError("Network unreachable")
            return 0

        with patch("socket.socket") as mock_socket:
            mock_sock = MagicMock()
            mock_sock.connect_ex.side_effect = mock_connect_ex
            mock_socket.return_value = mock_sock

            await recovery_manager._wait_for_ssh("10.0.0.1", timeout=30)

    @pytest.mark.asyncio
    async def test_attach_volumes_no_volumes(self, recovery_manager, mock_hcloud_client):
        """Test attach_volumes when no volumes exist."""
        mock_hcloud_client.volumes.get_all.return_value = []
        mock_server = MagicMock()

        await recovery_manager._attach_volumes(mock_server)

        mock_hcloud_client.volumes.get_all.assert_called_once()

    @pytest.mark.asyncio
    async def test_attach_volumes_with_detach(self, recovery_manager, mock_hcloud_client):
        """Test attaching volumes that need to be detached first."""
        mock_volume = MagicMock()
        mock_volume.id = 123
        mock_volume.name = "gitlab-data"
        mock_volume.server = MagicMock(id=999)  # Attached to another server

        mock_hcloud_client.volumes.get_all.return_value = [mock_volume]

        mock_action = MagicMock()
        mock_action.id = 1
        mock_action.status = "success"
        mock_hcloud_client.volumes.detach.return_value = mock_action
        mock_hcloud_client.volumes.attach.return_value = mock_action
        mock_hcloud_client.actions.get_by_id.return_value = mock_action

        mock_server = MagicMock(id=12345)

        await recovery_manager._attach_volumes(mock_server)

        mock_hcloud_client.volumes.detach.assert_called_once()
        mock_hcloud_client.volumes.attach.assert_called_once()

    @pytest.mark.asyncio
    async def test_attach_volumes_without_detach(self, recovery_manager, mock_hcloud_client):
        """Test attaching volumes that are not attached to any server."""
        mock_volume = MagicMock()
        mock_volume.id = 123
        mock_volume.name = "gitlab-data"
        mock_volume.server = None  # Not attached

        mock_hcloud_client.volumes.get_all.return_value = [mock_volume]

        mock_action = MagicMock()
        mock_action.id = 1
        mock_action.status = "success"
        mock_hcloud_client.volumes.attach.return_value = mock_action
        mock_hcloud_client.actions.get_by_id.return_value = mock_action

        mock_server = MagicMock(id=12345)

        await recovery_manager._attach_volumes(mock_server)

        mock_hcloud_client.volumes.detach.assert_not_called()
        mock_hcloud_client.volumes.attach.assert_called_once()

    def test_get_ssh_client(self, recovery_manager):
        """Test SSH client creation for recovery server."""
        with patch("src.restore.recovery.SSHClient") as mock_ssh_class:
            recovery_manager._get_ssh_client("10.0.0.1")

            mock_ssh_class.assert_called_once()
            call_args = mock_ssh_class.call_args[0][0]
            assert call_args.ssh_host == "10.0.0.1"
            assert call_args.ssh_user == "root"

    @pytest.mark.asyncio
    async def test_install_gitlab(self, recovery_manager, mock_ssh_client):
        """Test GitLab installation on recovery server."""
        mock_ssh_client.run_command = AsyncMock(return_value="ok")

        with patch.object(
            recovery_manager, "_get_ssh_client", return_value=mock_ssh_client
        ):
            await recovery_manager._install_gitlab("10.0.0.1")

        # Should have run multiple commands
        assert mock_ssh_client.run_command.call_count >= 5
        mock_ssh_client.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_restore_config(self, recovery_manager, mock_ssh_client):
        """Test configuration restore."""
        mock_ssh_client.run_command = AsyncMock(
            side_effect=[
                "",  # mkdir
                "gitlab-backup-2024-01-01",  # borg list
                "",  # borg extract
                "",  # cp gitlab.rb
                "",  # cp gitlab-secrets.json
                "",  # chmod
            ]
        )

        with patch.object(
            recovery_manager, "_get_ssh_client", return_value=mock_ssh_client
        ):
            await recovery_manager._restore_config("10.0.0.1")

        mock_ssh_client.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_restore_config_no_archive(self, recovery_manager, mock_ssh_client):
        """Test restore config when no archive found."""
        mock_ssh_client.run_command = AsyncMock(
            side_effect=[
                "",  # mkdir
                "",  # borg list returns empty
            ]
        )

        with patch.object(
            recovery_manager, "_get_ssh_client", return_value=mock_ssh_client
        ), pytest.raises(RuntimeError, match="No backup archives"):
            await recovery_manager._restore_config("10.0.0.1")

    @pytest.mark.asyncio
    async def test_restore_backup(self, recovery_manager, mock_ssh_client):
        """Test backup restoration."""
        mock_ssh_client.run_command = AsyncMock(
            side_effect=[
                "gitlab-backup-2024-01-01",  # borg list
                "",  # borg extract
                "",  # find/copy
                "1704067200_2024_01_01_16.0.0",  # timestamp
                "",  # stop puma
                "",  # stop sidekiq
                "",  # gitlab-backup restore
            ]
        )

        with patch.object(
            recovery_manager, "_get_ssh_client", return_value=mock_ssh_client
        ):
            await recovery_manager._restore_backup("10.0.0.1")

        mock_ssh_client.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_restore_backup_no_timestamp(self, recovery_manager, mock_ssh_client):
        """Test restore backup when timestamp cannot be determined."""
        mock_ssh_client.run_command = AsyncMock(
            side_effect=[
                "gitlab-backup-2024-01-01",  # borg list
                "",  # borg extract
                "",  # find/copy
                "",  # empty timestamp
            ]
        )

        with patch.object(
            recovery_manager, "_get_ssh_client", return_value=mock_ssh_client
        ), pytest.raises(RuntimeError, match="Could not determine"):
            await recovery_manager._restore_backup("10.0.0.1")

    @pytest.mark.asyncio
    async def test_reconfigure_gitlab(self, recovery_manager, mock_ssh_client):
        """Test GitLab reconfiguration."""
        mock_ssh_client.run_command = AsyncMock(return_value="ok")

        with patch.object(
            recovery_manager, "_get_ssh_client", return_value=mock_ssh_client
        ):
            await recovery_manager._reconfigure_gitlab("10.0.0.1")

        assert mock_ssh_client.run_command.call_count >= 2
        mock_ssh_client.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_verify_recovery_all_pass(self, recovery_manager, mock_ssh_client):
        """Test recovery verification when all checks pass."""
        mock_ssh_client.run_command = AsyncMock(
            side_effect=[
                "run: puma: (pid 123) 100s\nrun: sidekiq: (pid 124) 100s",
                "Checking GitLab Shell ... Finished\n",
            ]
        )

        with (
            patch.object(
                recovery_manager, "_get_ssh_client", return_value=mock_ssh_client
            ),
            patch("httpx.AsyncClient") as mock_httpx,
        ):
            mock_client = AsyncMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_client.get.return_value = MagicMock(status_code=200)
            mock_httpx.return_value = mock_client

            await recovery_manager._verify_recovery("10.0.0.1")

        mock_ssh_client.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_verify_recovery_with_warnings(
        self, recovery_manager, mock_ssh_client, mock_alert_manager
    ):
        """Test verification when some checks have warnings."""
        mock_ssh_client.run_command = AsyncMock(
            side_effect=[
                "run: puma: (pid 123) 100s\ndown: sidekiq: 0s",  # service down
                "Checking GitLab Shell ... Failure\nError: something wrong",
            ]
        )

        with (
            patch.object(
                recovery_manager, "_get_ssh_client", return_value=mock_ssh_client
            ),
            patch("httpx.AsyncClient") as mock_httpx,
        ):
            mock_client = AsyncMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_client.get.return_value = MagicMock(status_code=503)
            mock_httpx.return_value = mock_client

            await recovery_manager._verify_recovery("10.0.0.1")

        # Should send warning alert
        mock_alert_manager.send_alert.assert_called()

    @pytest.mark.asyncio
    async def test_verify_recovery_http_errors(
        self, recovery_manager, mock_ssh_client, mock_alert_manager
    ):
        """Test verification when HTTP checks fail."""
        mock_ssh_client.run_command = AsyncMock(
            side_effect=[
                "run: puma: (pid 123) 100s",
                "Checking GitLab Shell ... Finished\n",
            ]
        )

        with (
            patch.object(
                recovery_manager, "_get_ssh_client", return_value=mock_ssh_client
            ),
            patch("httpx.AsyncClient") as mock_httpx,
        ):
            mock_client = AsyncMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_client.get.side_effect = Exception("Connection refused")
            mock_httpx.return_value = mock_client

            await recovery_manager._verify_recovery("10.0.0.1")


class TestRestoreTesterExtended:
    """Extended tests for RestoreTester."""

    @pytest.fixture
    def restore_tester(
        self,
        hetzner_settings,
        backup_settings,
        gitlab_settings,
        mock_alert_manager,
        mock_hcloud_client,
    ):
        """Create a RestoreTester with mocked dependencies."""
        with patch("hcloud.Client", return_value=mock_hcloud_client):
            tester = RestoreTester(
                hetzner_settings=hetzner_settings,
                backup_settings=backup_settings,
                gitlab_settings=gitlab_settings,
                alert_manager=mock_alert_manager,
            )
            tester.hcloud = mock_hcloud_client
            return tester

    @pytest.mark.asyncio
    async def test_wait_for_action_success(self, restore_tester, mock_hcloud_client):
        """Test waiting for action to complete successfully."""
        mock_action = MagicMock()
        mock_action.id = 1
        mock_action.status = "success"
        mock_hcloud_client.actions.get_by_id.return_value = mock_action

        await restore_tester._wait_for_action(mock_action, timeout=10)

    @pytest.mark.asyncio
    async def test_wait_for_action_error(self, restore_tester, mock_hcloud_client):
        """Test handling action error."""
        mock_action = MagicMock()
        mock_action.id = 1
        mock_action.status = "error"
        mock_action.error = {"message": "Failed"}
        mock_hcloud_client.actions.get_by_id.return_value = mock_action

        with pytest.raises(RuntimeError, match="action failed"):
            await restore_tester._wait_for_action(mock_action, timeout=10)

    @pytest.mark.asyncio
    async def test_wait_for_action_timeout(self, restore_tester, mock_hcloud_client):
        """Test action timeout."""
        mock_action = MagicMock()
        mock_action.id = 1
        mock_action.status = "running"
        mock_hcloud_client.actions.get_by_id.return_value = mock_action

        with pytest.raises(TimeoutError):
            await restore_tester._wait_for_action(mock_action, timeout=1)

    @pytest.mark.asyncio
    async def test_wait_for_ssh_success(self, restore_tester):
        """Test waiting for SSH."""
        with patch("socket.socket") as mock_socket:
            mock_sock = MagicMock()
            mock_sock.connect_ex.return_value = 0
            mock_socket.return_value = mock_sock

            await restore_tester._wait_for_ssh("10.0.0.1", timeout=10)

    @pytest.mark.asyncio
    async def test_wait_for_ssh_timeout(self, restore_tester):
        """Test SSH timeout."""
        with patch("socket.socket") as mock_socket:
            mock_sock = MagicMock()
            mock_sock.connect_ex.return_value = 1
            mock_socket.return_value = mock_sock

            with pytest.raises(TimeoutError):
                await restore_tester._wait_for_ssh("10.0.0.1", timeout=1)

    @pytest.mark.asyncio
    async def test_wait_for_ssh_os_error(self, restore_tester):
        """Test SSH wait handles OSError."""
        call_count = 0

        def mock_connect_ex(*args):
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise OSError("Network error")
            return 0

        with patch("socket.socket") as mock_socket:
            mock_sock = MagicMock()
            mock_sock.connect_ex.side_effect = mock_connect_ex
            mock_socket.return_value = mock_sock

            await restore_tester._wait_for_ssh("10.0.0.1", timeout=30)

    def test_get_ssh_client(self, restore_tester):
        """Test SSH client creation."""
        with patch("src.restore.tester.SSHClient") as mock_ssh_class:
            restore_tester._get_ssh_client("10.0.0.1")

            mock_ssh_class.assert_called_once()
            call_args = mock_ssh_class.call_args[0][0]
            assert call_args.ssh_host == "10.0.0.1"
            assert call_args.ssh_user == "root"

    @pytest.mark.asyncio
    async def test_install_gitlab(self, restore_tester, mock_ssh_client):
        """Test GitLab installation."""
        mock_ssh_client.run_command = AsyncMock(return_value="ok")

        with patch.object(
            restore_tester, "_get_ssh_client", return_value=mock_ssh_client
        ):
            await restore_tester._install_gitlab("10.0.0.1")

        assert mock_ssh_client.run_command.call_count >= 5
        mock_ssh_client.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_restore_backup(self, restore_tester, mock_ssh_client):
        """Test backup restoration."""
        mock_ssh_client.run_command = AsyncMock(
            side_effect=[
                "",  # mkdir
                "gitlab-backup-2024-01-01",  # borg list
                "",  # borg extract
                "",  # cp gitlab.rb
                "",  # cp gitlab-secrets.json
                "",  # find/copy
                "1704067200_2024_01_01",  # timestamp
                "",  # stop puma
                "",  # stop sidekiq
                "",  # restore
                "",  # reconfigure
                "",  # restart
            ]
        )

        with patch.object(
            restore_tester, "_get_ssh_client", return_value=mock_ssh_client
        ):
            await restore_tester._restore_backup("10.0.0.1")

        mock_ssh_client.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_restore_backup_no_archive(self, restore_tester, mock_ssh_client):
        """Test restore when no archive found."""
        mock_ssh_client.run_command = AsyncMock(
            side_effect=[
                "",  # mkdir
                "",  # borg list empty
            ]
        )

        with patch.object(
            restore_tester, "_get_ssh_client", return_value=mock_ssh_client
        ), pytest.raises(RuntimeError, match="No backup archives"):
            await restore_tester._restore_backup("10.0.0.1")

    @pytest.mark.asyncio
    async def test_restore_backup_no_timestamp(self, restore_tester, mock_ssh_client):
        """Test restore when timestamp cannot be found."""
        mock_ssh_client.run_command = AsyncMock(
            side_effect=[
                "",  # mkdir
                "gitlab-backup-2024-01-01",  # borg list
                "",  # borg extract
                "",  # cp gitlab.rb
                "",  # cp gitlab-secrets.json
                "",  # find/copy
                "",  # empty timestamp
            ]
        )

        with patch.object(
            restore_tester, "_get_ssh_client", return_value=mock_ssh_client
        ), pytest.raises(RuntimeError, match="Could not find backup"):
            await restore_tester._restore_backup("10.0.0.1")

    @pytest.mark.asyncio
    async def test_verify_restore_database_check(self, restore_tester, mock_ssh_client):
        """Test database connectivity check in verification."""
        mock_ssh_client.run_command = AsyncMock(
            side_effect=[
                "run: puma: (pid 123) 100s",  # status
                "Finished",  # check
                "1",  # db check
            ]
        )

        with (
            patch.object(
                restore_tester, "_get_ssh_client", return_value=mock_ssh_client
            ),
            patch("httpx.AsyncClient") as mock_httpx,
        ):
            mock_client = AsyncMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_client.get.return_value = MagicMock(status_code=200)
            mock_httpx.return_value = mock_client

            results = await restore_tester._verify_restore("10.0.0.1")

        assert results["database_accessible"] is True

    @pytest.mark.asyncio
    async def test_verify_restore_all_http_checks(self, restore_tester, mock_ssh_client):
        """Test all HTTP endpoint checks."""
        mock_ssh_client.run_command = AsyncMock(
            side_effect=[
                "run: puma: 100s",
                "Finished",
                "1",
            ]
        )

        with (
            patch.object(
                restore_tester, "_get_ssh_client", return_value=mock_ssh_client
            ),
            patch("httpx.AsyncClient") as mock_httpx,
        ):
            mock_client = AsyncMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_client.get.return_value = MagicMock(status_code=200)
            mock_httpx.return_value = mock_client

            results = await restore_tester._verify_restore("10.0.0.1")

        assert results["health_check"] is True
        assert results["readiness_check"] is True
        assert results["liveness_check"] is True
        assert results["web_accessible"] is True

    @pytest.mark.asyncio
    async def test_verify_restore_web_redirect(self, restore_tester, mock_ssh_client):
        """Test web accessible check handles redirect."""
        mock_ssh_client.run_command = AsyncMock(
            side_effect=[
                "run: puma: 100s",
                "Finished",
                "1",
            ]
        )

        with (
            patch.object(
                restore_tester, "_get_ssh_client", return_value=mock_ssh_client
            ),
            patch("httpx.AsyncClient") as mock_httpx,
        ):
            mock_client = AsyncMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            # Return 302 redirect for main page
            mock_client.get.return_value = MagicMock(status_code=302)
            mock_httpx.return_value = mock_client

            results = await restore_tester._verify_restore("10.0.0.1")

        assert results["web_accessible"] is True

    @pytest.mark.asyncio
    async def test_run_restore_test_success(
        self, restore_tester, mock_hcloud_client, mock_alert_manager
    ):
        """Test full restore test workflow success."""
        with (
            patch.object(
                restore_tester, "_provision_test_server", new_callable=AsyncMock
            ) as mock_provision,
            patch.object(
                restore_tester, "_install_gitlab", new_callable=AsyncMock
            ),
            patch.object(
                restore_tester, "_restore_backup", new_callable=AsyncMock
            ),
            patch.object(
                restore_tester, "_verify_restore", new_callable=AsyncMock
            ) as mock_verify,
        ):
            mock_server = MagicMock()
            mock_server.id = 12345
            mock_server.public_net.ipv4.ip = "10.0.0.1"
            mock_provision.return_value = mock_server
            mock_verify.return_value = {"health_check": True, "services": True}

            result = await restore_tester.run_restore_test()

        assert result.success is True
        assert "server_provisioned" in result.steps_completed
        assert "verification_completed" in result.steps_completed
        assert "server_destroyed" in result.steps_completed
        mock_alert_manager.send_alert.assert_called_once()

    @pytest.mark.asyncio
    async def test_run_restore_test_failure(
        self, restore_tester, mock_hcloud_client, mock_alert_manager
    ):
        """Test restore test workflow with failure."""
        with (
            patch.object(
                restore_tester, "_provision_test_server", new_callable=AsyncMock
            ) as mock_provision,
            patch.object(
                restore_tester, "_install_gitlab", new_callable=AsyncMock
            ) as mock_install,
        ):
            mock_server = MagicMock()
            mock_server.id = 12345
            mock_server.public_net.ipv4.ip = "10.0.0.1"
            mock_provision.return_value = mock_server
            mock_install.side_effect = RuntimeError("Installation failed")

            result = await restore_tester.run_restore_test()

        assert result.success is False
        assert "Installation failed" in result.errors
        mock_alert_manager.send_alert.assert_called_once()

    @pytest.mark.asyncio
    async def test_run_restore_test_cleanup_failure(
        self, restore_tester, mock_hcloud_client, mock_alert_manager
    ):
        """Test restore test when cleanup fails."""
        mock_hcloud_client.servers.delete.side_effect = Exception("Delete failed")

        with (
            patch.object(
                restore_tester, "_provision_test_server", new_callable=AsyncMock
            ) as mock_provision,
            patch.object(
                restore_tester, "_install_gitlab", new_callable=AsyncMock
            ),
            patch.object(
                restore_tester, "_restore_backup", new_callable=AsyncMock
            ),
            patch.object(
                restore_tester, "_verify_restore", new_callable=AsyncMock
            ) as mock_verify,
        ):
            mock_server = MagicMock()
            mock_server.id = 12345
            mock_server.public_net.ipv4.ip = "10.0.0.1"
            mock_provision.return_value = mock_server
            mock_verify.return_value = {"health_check": True}

            result = await restore_tester.run_restore_test()

        assert "Cleanup failed" in str(result.errors)
