"""Tests for AI analyst module."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.ai.analyst import AIAnalyst, AnalysisResult, RecommendedAction, Urgency
from src.ai.claude_cli import CLISettings, ClaudeCLI, ClaudeCLIError


class TestUrgency:
    """Tests for Urgency enum."""

    def test_urgency_values(self):
        """Test Urgency enum values."""
        assert Urgency.CRITICAL.value == "critical"
        assert Urgency.HIGH.value == "high"
        assert Urgency.MEDIUM.value == "medium"
        assert Urgency.LOW.value == "low"
        assert Urgency.INFO.value == "info"


class TestRecommendedAction:
    """Tests for RecommendedAction dataclass."""

    def test_action_creation(self):
        """Test creating a recommended action."""
        action = RecommendedAction(
            name="cleanup_artifacts",
            description="Clean up old CI artifacts",
            reason="Disk space is running low",
            urgency=Urgency.MEDIUM,
            auto_execute=True,
            command="gitlab-rake gitlab:cleanup:orphan_job_artifact_files",
        )

        assert action.name == "cleanup_artifacts"
        assert action.auto_execute is True
        assert action.urgency == Urgency.MEDIUM

    def test_action_defaults(self):
        """Test recommended action default values."""
        action = RecommendedAction(
            name="test",
            description="Test action",
            reason="Testing",
            urgency=Urgency.INFO,
        )

        assert action.auto_execute is False
        assert action.command is None
        assert action.parameters == {}


class TestAnalysisResult:
    """Tests for AnalysisResult dataclass."""

    def test_result_creation(self):
        """Test creating an analysis result."""
        result = AnalysisResult(
            timestamp=datetime.now(),
            summary="System is healthy",
            actions_needed=False,
            urgency=Urgency.INFO,
            recommendations=["Continue monitoring"],
            recommended_actions=[],
            raw_analysis='{"summary": "System is healthy"}',
        )

        assert result.summary == "System is healthy"
        assert result.actions_needed is False
        assert len(result.recommendations) == 1


class TestAIAnalyst:
    """Tests for AIAnalyst."""

    @pytest.fixture
    def mock_anthropic_client(self, mock_anthropic_response):
        """Create a mocked Anthropic client."""
        client = MagicMock()
        client.messages.create.return_value = mock_anthropic_response()
        return client

    @pytest.fixture
    def ai_analyst(self, claude_settings, mock_anthropic_client):
        """Create an AIAnalyst with mocked client."""
        with patch("anthropic.Anthropic", return_value=mock_anthropic_client):
            analyst = AIAnalyst(claude_settings)
            analyst.client = mock_anthropic_client
            return analyst

    @pytest.mark.asyncio
    async def test_analyze_healthy_system(
        self,
        ai_analyst,
        sample_health_status,
        sample_resource_status,
        sample_backup_status,
    ):
        """Test analysis of a healthy system."""
        result = await ai_analyst.analyze_system_state(
            health=sample_health_status,
            resources=sample_resource_status,
            backup=sample_backup_status,
        )

        assert isinstance(result, AnalysisResult)
        assert result.urgency == Urgency.INFO
        assert result.actions_needed is False

    @pytest.mark.asyncio
    async def test_analyze_with_actions(
        self,
        ai_analyst,
        mock_anthropic_response,
        sample_health_status,
        sample_resource_status,
        sample_backup_status,
    ):
        """Test analysis that recommends actions."""
        response_with_actions = mock_anthropic_response("""{
            "summary": "Disk space is running low",
            "actions_needed": true,
            "urgency": "high",
            "recommendations": ["Clean up old artifacts", "Expand storage"],
            "actions": [
                {
                    "name": "cleanup_artifacts",
                    "description": "Remove old CI artifacts",
                    "reason": "Disk at 85%",
                    "urgency": "high",
                    "auto_execute": true
                }
            ]
        }""")

        ai_analyst.client.messages.create.return_value = response_with_actions

        result = await ai_analyst.analyze_system_state(
            health=sample_health_status,
            resources=sample_resource_status,
            backup=sample_backup_status,
        )

        assert result.actions_needed is True
        assert result.urgency == Urgency.HIGH
        assert len(result.recommended_actions) == 1
        assert result.recommended_actions[0].name == "cleanup_artifacts"

    @pytest.mark.asyncio
    async def test_analyze_with_additional_context(
        self,
        ai_analyst,
        sample_health_status,
        sample_resource_status,
        sample_backup_status,
    ):
        """Test analysis with additional context."""
        await ai_analyst.analyze_system_state(
            health=sample_health_status,
            resources=sample_resource_status,
            backup=sample_backup_status,
            additional_context="Recent deployment caused some issues",
        )

        # Verify the call was made with additional context
        call_args = ai_analyst.client.messages.create.call_args
        assert "Recent deployment" in call_args.kwargs["messages"][0]["content"]

    @pytest.mark.asyncio
    async def test_parse_json_in_markdown(self, ai_analyst, mock_anthropic_response):
        """Test parsing JSON wrapped in markdown code blocks."""
        response_with_markdown = mock_anthropic_response("""Here's my analysis:

```json
{
    "summary": "All systems operational",
    "actions_needed": false,
    "urgency": "info",
    "recommendations": [],
    "actions": []
}
```

Let me know if you need more details.""")

        ai_analyst.client.messages.create.return_value = response_with_markdown

        result = await ai_analyst.analyze_system_state(
            health={}, resources={}, backup={}
        )

        assert result.summary == "All systems operational"

    @pytest.mark.asyncio
    async def test_parse_invalid_json(self, ai_analyst, mock_anthropic_response):
        """Test handling of invalid JSON response."""
        invalid_response = mock_anthropic_response(
            "This is not JSON, just plain text analysis."
        )

        ai_analyst.client.messages.create.return_value = invalid_response

        result = await ai_analyst.analyze_system_state(
            health={}, resources={}, backup={}
        )

        # Should return a result with the raw text
        assert "non-JSON response" in result.summary
        assert "plain text" in result.raw_analysis

    @pytest.mark.asyncio
    async def test_ask_question(self, ai_analyst):
        """Test asking a specific question."""
        ai_analyst.client.messages.create.return_value = MagicMock(
            content=[MagicMock(text="The disk usage is at 45%, which is healthy.")]
        )

        answer = await ai_analyst.ask("What is the current disk usage?")

        assert "disk usage" in answer.lower()
        ai_analyst.client.messages.create.assert_called()

    @pytest.mark.asyncio
    async def test_ask_with_context(self, ai_analyst):
        """Test asking a question with context."""
        context = {"disk_usage": 45, "memory_usage": 60}

        ai_analyst.client.messages.create.return_value = MagicMock(
            content=[MagicMock(text="Based on the metrics, the system is healthy.")]
        )

        await ai_analyst.ask("Is the system healthy?", context=context)

        # Verify context was included
        call_args = ai_analyst.client.messages.create.call_args
        assert "disk_usage" in call_args.kwargs["messages"][0]["content"]

    def test_get_history(self, ai_analyst):
        """Test getting analysis history."""
        # Initially empty
        assert len(ai_analyst.get_history()) == 0

    @pytest.mark.asyncio
    async def test_history_tracking(
        self,
        ai_analyst,
        sample_health_status,
        sample_resource_status,
        sample_backup_status,
    ):
        """Test that analyses are tracked in history."""
        await ai_analyst.analyze_system_state(
            health=sample_health_status,
            resources=sample_resource_status,
            backup=sample_backup_status,
        )

        history = ai_analyst.get_history()
        assert len(history) == 1
        assert isinstance(history[0], AnalysisResult)

    def test_prepare_context(self, ai_analyst):
        """Test context preparation for Claude."""
        health = {"status": "ok"}
        resources = {"disk": {"percent": 45}}
        backup = {"age_hours": 1}

        context = ai_analyst._prepare_context(health, resources, backup, None)

        assert "Health Status" in context
        assert "Resource Usage" in context
        assert "Backup Status" in context
        assert "ok" in context
        assert "45" in context

    def test_prepare_context_with_additional(self, ai_analyst):
        """Test context preparation with additional context."""
        context = ai_analyst._prepare_context(
            {}, {}, {}, "This is important additional context"
        )

        assert "Additional Context" in context
        assert "important additional context" in context


class TestAIAnalystErrorHandling:
    """Tests for AI analyst error handling."""

    @pytest.fixture
    def analyst_with_error(self, claude_settings):
        """Create an analyst that will raise errors."""
        import anthropic

        mock_client = MagicMock()
        mock_client.messages.create.side_effect = anthropic.APIError(
            message="API Error",
            request=MagicMock(),
            body=None,
        )

        with patch("anthropic.Anthropic", return_value=mock_client):
            analyst = AIAnalyst(claude_settings)
            analyst.client = mock_client
            return analyst

    @pytest.mark.asyncio
    async def test_api_error_handling(self, analyst_with_error):
        """Test handling of API errors."""
        import anthropic

        with pytest.raises(anthropic.APIError):
            await analyst_with_error.analyze_system_state(
                health={}, resources={}, backup={}
            )


class TestClaudeCLI:
    """Tests for Claude CLI wrapper."""

    @pytest.fixture
    def cli_settings(self):
        """Create CLI settings for testing."""
        return CLISettings(
            cli_path="claude",
            timeout=60,
            output_format="json",
        )

    @pytest.fixture
    def mock_subprocess_success(self):
        """Mock successful subprocess execution."""
        async def mock_communicate():
            return (
                b'{"result": "{\\"summary\\": \\"System healthy\\", \\"actions_needed\\": false, \\"urgency\\": \\"info\\", \\"recommendations\\": [], \\"actions\\": []}"}',
                b"",
            )

        mock_process = MagicMock()
        mock_process.communicate = mock_communicate
        mock_process.returncode = 0
        mock_process.kill = MagicMock()
        return mock_process

    @pytest.fixture
    def mock_subprocess_json_output(self):
        """Mock subprocess with direct JSON output."""
        async def mock_communicate():
            return (
                json.dumps({
                    "summary": "System is healthy",
                    "actions_needed": False,
                    "urgency": "info",
                    "recommendations": ["Continue monitoring"],
                    "actions": [],
                }).encode(),
                b"",
            )

        mock_process = MagicMock()
        mock_process.communicate = mock_communicate
        mock_process.returncode = 0
        return mock_process

    def test_cli_settings_defaults(self):
        """Test CLI settings have correct defaults."""
        settings = CLISettings()
        assert settings.cli_path == "claude"
        assert settings.timeout == 120
        assert settings.output_format == "json"

    def test_cli_initialization(self, cli_settings):
        """Test CLI wrapper initialization."""
        with patch("shutil.which", return_value="/usr/local/bin/claude"):
            cli = ClaudeCLI(cli_settings)
            assert cli.settings.cli_path == "claude"

    def test_cli_not_found_warning(self, cli_settings, caplog):
        """Test warning when CLI not found."""
        with patch("shutil.which", return_value=None):
            ClaudeCLI(cli_settings)
            # Should log a warning but not raise

    @pytest.mark.asyncio
    async def test_run_prompt_success(self, cli_settings, mock_subprocess_json_output):
        """Test successful prompt execution."""
        with patch("shutil.which", return_value="/usr/local/bin/claude"):
            cli = ClaudeCLI(cli_settings)

        with patch(
            "asyncio.create_subprocess_exec",
            return_value=mock_subprocess_json_output,
        ):
            result = await cli.run_prompt("Test prompt")

            assert "summary" in result or "text" in result

    @pytest.mark.asyncio
    async def test_run_prompt_failure(self, cli_settings):
        """Test handling of CLI failure."""
        async def mock_communicate():
            return (b"", b"Error: Something went wrong")

        mock_process = MagicMock()
        mock_process.communicate = mock_communicate
        mock_process.returncode = 1

        with patch("shutil.which", return_value="/usr/local/bin/claude"):
            cli = ClaudeCLI(cli_settings)

        with patch("asyncio.create_subprocess_exec", return_value=mock_process):
            with pytest.raises(ClaudeCLIError) as exc_info:
                await cli.run_prompt("Test prompt")

            assert exc_info.value.returncode == 1
            assert "Something went wrong" in exc_info.value.stderr

    @pytest.mark.asyncio
    async def test_run_prompt_timeout(self, cli_settings):
        """Test handling of CLI timeout."""
        async def mock_communicate():
            await asyncio.sleep(10)  # Longer than timeout
            return (b"", b"")

        mock_process = MagicMock()
        mock_process.communicate = mock_communicate
        mock_process.kill = MagicMock()

        # Use very short timeout
        cli_settings.timeout = 0.01

        with patch("shutil.which", return_value="/usr/local/bin/claude"):
            cli = ClaudeCLI(cli_settings)

        with patch("asyncio.create_subprocess_exec", return_value=mock_process):
            with pytest.raises(ClaudeCLIError) as exc_info:
                await cli.run_prompt("Test prompt")

            assert "timed out" in str(exc_info.value)

    def test_parse_cli_output_json(self, cli_settings):
        """Test parsing JSON output."""
        with patch("shutil.which", return_value="/usr/local/bin/claude"):
            cli = ClaudeCLI(cli_settings)

        output = '{"summary": "Test", "urgency": "info"}'
        result = cli._parse_cli_output(output, "json")

        assert result["summary"] == "Test"
        assert result["urgency"] == "info"

    def test_parse_cli_output_wrapped_json(self, cli_settings):
        """Test parsing wrapped JSON output from CLI."""
        with patch("shutil.which", return_value="/usr/local/bin/claude"):
            cli = ClaudeCLI(cli_settings)

        output = json.dumps({
            "result": '{"summary": "Wrapped test", "actions_needed": false}'
        })
        result = cli._parse_cli_output(output, "json")

        assert result["summary"] == "Wrapped test"

    def test_parse_cli_output_text(self, cli_settings):
        """Test parsing plain text output."""
        with patch("shutil.which", return_value="/usr/local/bin/claude"):
            cli = ClaudeCLI(cli_settings)

        output = "This is plain text response"
        result = cli._parse_cli_output(output, "text")

        assert result["text"] == output

    @pytest.mark.asyncio
    async def test_analyze_system_state(self, cli_settings, mock_subprocess_json_output):
        """Test system state analysis via CLI."""
        with patch("shutil.which", return_value="/usr/local/bin/claude"):
            cli = ClaudeCLI(cli_settings)

        with patch(
            "asyncio.create_subprocess_exec",
            return_value=mock_subprocess_json_output,
        ):
            result = await cli.analyze_system_state(
                context={"health": {"status": "ok"}},
                system_prompt="You are a system admin.",
            )

            assert "summary" in result
            assert "actions_needed" in result
            assert "urgency" in result

    @pytest.mark.asyncio
    async def test_ask_question(self, cli_settings):
        """Test asking a question via CLI."""
        async def mock_communicate():
            return (b"The answer is 42", b"")

        mock_process = MagicMock()
        mock_process.communicate = mock_communicate
        mock_process.returncode = 0

        with patch("shutil.which", return_value="/usr/local/bin/claude"):
            cli = ClaudeCLI(cli_settings)

        with patch("asyncio.create_subprocess_exec", return_value=mock_process):
            answer = await cli.ask("What is the meaning of life?")

            assert "42" in answer


class TestAIAnalystCLIMode:
    """Tests for AIAnalyst in CLI mode."""

    @pytest.fixture
    def mock_cli(self):
        """Create a mocked ClaudeCLI."""
        cli = MagicMock()
        cli.analyze_system_state = AsyncMock(return_value={
            "summary": "System healthy via CLI",
            "actions_needed": False,
            "urgency": "info",
            "recommendations": ["All good"],
            "actions": [],
            "raw_response": {},
        })
        cli.ask = AsyncMock(return_value="CLI response")
        return cli

    @pytest.fixture
    def ai_analyst_cli(self, claude_settings_cli, mock_cli):
        """Create an AIAnalyst in CLI mode with mocked CLI."""
        with patch("shutil.which", return_value="/usr/local/bin/claude"):
            with patch(
                "src.ai.claude_cli.ClaudeCLI",
                return_value=mock_cli,
            ):
                analyst = AIAnalyst(claude_settings_cli)
                analyst._cli = mock_cli
                return analyst

    @pytest.mark.asyncio
    async def test_analyze_via_cli(
        self,
        ai_analyst_cli,
        sample_health_status,
        sample_resource_status,
        sample_backup_status,
    ):
        """Test analysis using CLI backend."""
        result = await ai_analyst_cli.analyze_system_state(
            health=sample_health_status,
            resources=sample_resource_status,
            backup=sample_backup_status,
        )

        assert isinstance(result, AnalysisResult)
        assert result.summary == "System healthy via CLI"
        assert result.urgency == Urgency.INFO

    @pytest.mark.asyncio
    async def test_ask_via_cli(self, ai_analyst_cli):
        """Test asking a question via CLI backend."""
        answer = await ai_analyst_cli.ask("Test question")

        assert answer == "CLI response"
        ai_analyst_cli._cli.ask.assert_called_once()

    @pytest.mark.asyncio
    async def test_cli_error_handling(self, ai_analyst_cli):
        """Test handling of CLI errors."""
        ai_analyst_cli._cli.analyze_system_state = AsyncMock(
            side_effect=ClaudeCLIError("CLI failed", returncode=1)
        )

        with pytest.raises(ClaudeCLIError):
            await ai_analyst_cli.analyze_system_state(
                health={}, resources={}, backup={}
            )

    def test_client_property_raises_in_cli_mode(self, ai_analyst_cli):
        """Test that accessing client property raises in CLI mode."""
        ai_analyst_cli._client = None  # Ensure client is None
        with pytest.raises(RuntimeError, match="not available in CLI mode"):
            _ = ai_analyst_cli.client

    @pytest.mark.asyncio
    async def test_history_tracking_in_cli_mode(
        self,
        ai_analyst_cli,
        sample_health_status,
        sample_resource_status,
        sample_backup_status,
    ):
        """Test that history is tracked in CLI mode."""
        await ai_analyst_cli.analyze_system_state(
            health=sample_health_status,
            resources=sample_resource_status,
            backup=sample_backup_status,
        )

        history = ai_analyst_cli.get_history()
        assert len(history) == 1
        assert history[0].summary == "System healthy via CLI"
