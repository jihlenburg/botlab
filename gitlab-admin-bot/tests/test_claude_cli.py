"""Tests for Claude Code CLI wrapper."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.ai.claude_cli import ClaudeCLI, ClaudeCLIError, CLISettings


class TestCLISettings:
    """Tests for CLISettings."""

    def test_default_settings(self):
        """Test default CLI settings."""
        settings = CLISettings()
        assert settings.cli_path == "claude"
        assert settings.timeout == 120
        assert settings.output_format == "json"

    def test_custom_settings(self):
        """Test custom CLI settings."""
        settings = CLISettings(
            cli_path="/usr/local/bin/claude",
            timeout=60,
            output_format="text",
        )
        assert settings.cli_path == "/usr/local/bin/claude"
        assert settings.timeout == 60
        assert settings.output_format == "text"


class TestClaudeCLIError:
    """Tests for ClaudeCLIError."""

    def test_error_basic(self):
        """Test basic error creation."""
        error = ClaudeCLIError("Something failed")
        assert str(error) == "Something failed"
        assert error.returncode is None
        assert error.stderr == ""

    def test_error_with_details(self):
        """Test error with returncode and stderr."""
        error = ClaudeCLIError(
            "Command failed",
            returncode=1,
            stderr="Permission denied",
        )
        assert str(error) == "Command failed"
        assert error.returncode == 1
        assert error.stderr == "Permission denied"


class TestClaudeCLI:
    """Tests for ClaudeCLI."""

    @pytest.fixture
    def cli(self):
        """Create ClaudeCLI with mocked verification."""
        with patch("shutil.which", return_value="/usr/bin/claude"):
            return ClaudeCLI()

    @pytest.fixture
    def cli_custom(self):
        """Create ClaudeCLI with custom settings."""
        settings = CLISettings(
            cli_path="/custom/claude",
            timeout=60,
            output_format="text",
        )
        with patch("shutil.which", return_value="/custom/claude"):
            return ClaudeCLI(settings)

    def test_initialization(self, cli):
        """Test CLI initialization."""
        assert cli.settings.cli_path == "claude"
        assert cli.settings.timeout == 120

    def test_initialization_cli_not_found(self):
        """Test initialization when CLI not in PATH."""
        with patch("shutil.which", return_value=None):
            # Should not raise, just log warning
            cli = ClaudeCLI()
            assert cli.settings.cli_path == "claude"

    @pytest.mark.asyncio
    async def test_run_prompt_success(self, cli):
        """Test successful prompt execution."""
        mock_process = AsyncMock()
        mock_process.returncode = 0
        mock_process.communicate = AsyncMock(
            return_value=(
                b'{"result": "Hello, world!"}',
                b"",
            )
        )

        with patch("asyncio.create_subprocess_exec", return_value=mock_process):
            result = await cli.run_prompt("Say hello")

        assert "text" in result
        assert result["text"] == "Hello, world!"

    @pytest.mark.asyncio
    async def test_run_prompt_with_system_prompt(self, cli):
        """Test prompt with system prompt."""
        mock_process = AsyncMock()
        mock_process.returncode = 0
        mock_process.communicate = AsyncMock(
            return_value=(
                b'{"result": "Response"}',
                b"",
            )
        )

        with patch("asyncio.create_subprocess_exec", return_value=mock_process) as mock_exec:
            await cli.run_prompt(
                "Test prompt",
                system_prompt="You are a helpful assistant",
            )

            # Verify system prompt was passed
            call_args = mock_exec.call_args[0]
            assert "--system-prompt" in call_args

    @pytest.mark.asyncio
    async def test_run_prompt_nonzero_exit(self, cli):
        """Test prompt with non-zero exit code."""
        mock_process = AsyncMock()
        mock_process.returncode = 1
        mock_process.communicate = AsyncMock(
            return_value=(b"", b"Error: API rate limit exceeded")
        )

        with patch("asyncio.create_subprocess_exec", return_value=mock_process):
            with pytest.raises(ClaudeCLIError) as exc_info:
                await cli.run_prompt("Test prompt")

            assert exc_info.value.returncode == 1
            assert "rate limit" in exc_info.value.stderr

    @pytest.mark.asyncio
    async def test_run_prompt_timeout(self, cli):
        """Test prompt timeout."""
        mock_process = AsyncMock()
        mock_process.kill = MagicMock()

        async def slow_communicate():
            await asyncio.sleep(10)
            return (b"", b"")

        mock_process.communicate = slow_communicate

        with patch("asyncio.create_subprocess_exec", return_value=mock_process):
            with pytest.raises(ClaudeCLIError) as exc_info:
                await cli.run_prompt("Test", timeout=0.01)

            assert "timed out" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_run_prompt_file_not_found(self, cli):
        """Test prompt when CLI binary not found."""
        with patch(
            "asyncio.create_subprocess_exec",
            side_effect=FileNotFoundError("claude not found"),
        ):
            with pytest.raises(ClaudeCLIError) as exc_info:
                await cli.run_prompt("Test")

            assert "not found" in str(exc_info.value)

    def test_parse_cli_output_json(self, cli):
        """Test parsing JSON output."""
        output = '{"result": "test response"}'
        result = cli._parse_cli_output(output, "json")
        assert result["text"] == "test response"

    def test_parse_cli_output_json_nested(self, cli):
        """Test parsing JSON output with nested JSON result."""
        inner_json = '{"summary": "All good", "actions_needed": false}'
        output = json.dumps({"result": inner_json})
        result = cli._parse_cli_output(output, "json")
        assert result["summary"] == "All good"
        assert result["actions_needed"] is False

    def test_parse_cli_output_json_invalid(self, cli):
        """Test parsing invalid JSON output."""
        output = "This is not JSON"
        result = cli._parse_cli_output(output, "json")
        assert result["text"] == "This is not JSON"

    def test_parse_cli_output_json_non_dict_result(self, cli):
        """Test parsing JSON with non-dict result."""
        output = '{"result": ["item1", "item2"]}'
        result = cli._parse_cli_output(output, "json")
        assert "text" in result

    def test_parse_cli_output_json_direct_dict(self, cli):
        """Test parsing JSON that is already a dict without result key."""
        output = '{"summary": "test", "status": "ok"}'
        result = cli._parse_cli_output(output, "json")
        assert result["summary"] == "test"
        assert result["status"] == "ok"

    def test_parse_cli_output_json_non_json_result(self, cli):
        """Test parsing JSON with non-JSON string result."""
        output = '{"result": "Just plain text response"}'
        result = cli._parse_cli_output(output, "json")
        assert result["text"] == "Just plain text response"

    def test_parse_cli_output_stream_json(self, cli):
        """Test parsing stream-json output."""
        output = (
            '{"type": "text", "content": "Hello "}\n'
            '{"type": "text", "content": "world!"}\n'
        )
        result = cli._parse_cli_output(output, "stream-json")
        assert result["text"] == "Hello world!"

    def test_parse_cli_output_stream_json_with_json_content(self, cli):
        """Test parsing stream-json that accumulates to valid JSON."""
        output = (
            '{"type": "text", "content": "{\\"summary\\": "}\n'
            '{"type": "text", "content": "\\"ok\\"}"}\n'
        )
        result = cli._parse_cli_output(output, "stream-json")
        assert "summary" in result or "text" in result

    def test_parse_cli_output_stream_json_invalid_line(self, cli):
        """Test parsing stream-json with invalid lines."""
        output = (
            'not json\n'
            '{"type": "text", "content": "valid"}\n'
        )
        result = cli._parse_cli_output(output, "stream-json")
        assert result["text"] == "valid"

    def test_parse_cli_output_text(self, cli):
        """Test parsing text output."""
        output = "Plain text response"
        result = cli._parse_cli_output(output, "text")
        assert result["text"] == "Plain text response"

    @pytest.mark.asyncio
    async def test_analyze_system_state(self, cli):
        """Test system state analysis."""
        mock_response = {
            "summary": "System is healthy",
            "actions_needed": False,
            "urgency": "info",
            "recommendations": ["Continue monitoring"],
            "actions": [],
        }

        with patch.object(cli, "run_prompt", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = mock_response

            result = await cli.analyze_system_state(
                context={"health": "ok", "timestamp": "2024-01-01"},
                system_prompt="You are a system admin assistant",
            )

        assert result["summary"] == "System is healthy"
        assert result["actions_needed"] is False
        assert "raw_response" in result

    @pytest.mark.asyncio
    async def test_analyze_system_state_missing_fields(self, cli):
        """Test analysis with missing fields in response."""
        mock_response = {"partial": "response"}

        with patch.object(cli, "run_prompt", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = mock_response

            result = await cli.analyze_system_state(
                context={},
                system_prompt="Test",
            )

        # Should have default values
        assert result["summary"] == "Analysis completed"
        assert result["actions_needed"] is False
        assert result["urgency"] == "info"
        assert result["recommendations"] == []
        assert result["actions"] == []

    @pytest.mark.asyncio
    async def test_ask(self, cli):
        """Test asking a question."""
        with patch.object(cli, "run_prompt", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = {"text": "The answer is 42"}

            result = await cli.ask("What is the meaning of life?")

        assert result == "The answer is 42"
        mock_run.assert_called_once()

    @pytest.mark.asyncio
    async def test_ask_with_context(self, cli):
        """Test asking with context."""
        with patch.object(cli, "run_prompt", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = {"text": "Response with context"}

            result = await cli.ask(
                "What should we do?",
                context={"status": "critical"},
                system_prompt="Be helpful",
            )

        assert result == "Response with context"
        call_kwargs = mock_run.call_args.kwargs
        assert "Context:" in mock_run.call_args.kwargs["prompt"]
        assert call_kwargs["system_prompt"] == "Be helpful"

    @pytest.mark.asyncio
    async def test_ask_non_text_response(self, cli):
        """Test ask when response is not text."""
        with patch.object(cli, "run_prompt", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = {"data": "something"}

            result = await cli.ask("Question")

        # Should stringify the dict
        assert "data" in result
