"""Claude Code CLI wrapper for AI-powered analysis."""

from __future__ import annotations

import asyncio
import json
import shutil
from dataclasses import dataclass
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


@dataclass
class CLISettings:
    """Settings for Claude CLI invocation."""

    cli_path: str = "claude"
    timeout: int = 120
    output_format: str = "json"


class ClaudeCLIError(Exception):
    """Error from Claude CLI invocation."""

    def __init__(self, message: str, returncode: int | None = None, stderr: str = ""):
        super().__init__(message)
        self.returncode = returncode
        self.stderr = stderr


class ClaudeCLI:
    """Wrapper for Claude Code CLI invocation."""

    def __init__(self, settings: CLISettings | None = None) -> None:
        self.settings = settings or CLISettings()
        self._verify_cli_available()

    def _verify_cli_available(self) -> None:
        """Verify that the Claude CLI is available."""
        if not shutil.which(self.settings.cli_path):
            logger.warning(
                "Claude CLI not found in PATH",
                cli_path=self.settings.cli_path,
            )

    async def run_prompt(
        self,
        prompt: str,
        system_prompt: str | None = None,
        output_format: str | None = None,
        timeout: int | None = None,
    ) -> dict[str, Any]:
        """Run a prompt through Claude CLI and return parsed JSON response.

        Args:
            prompt: The user prompt to send
            system_prompt: Optional system prompt
            output_format: Output format (json, text, stream-json)
            timeout: Timeout in seconds

        Returns:
            Parsed JSON response from Claude

        Raises:
            ClaudeCLIError: If CLI invocation fails
        """
        cmd = [self.settings.cli_path]

        # Add prompt
        cmd.extend(["-p", prompt])

        # Add output format
        fmt = output_format or self.settings.output_format
        cmd.extend(["--output-format", fmt])

        # Add system prompt if provided
        if system_prompt:
            cmd.extend(["--system-prompt", system_prompt])

        logger.debug("Invoking Claude CLI", command=cmd[:3])

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            effective_timeout = timeout or self.settings.timeout
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=effective_timeout,
            )

            stdout_text = stdout.decode("utf-8")
            stderr_text = stderr.decode("utf-8")

            if process.returncode != 0:
                logger.error(
                    "Claude CLI failed",
                    returncode=process.returncode,
                    stderr=stderr_text,
                )
                raise ClaudeCLIError(
                    f"Claude CLI exited with code {process.returncode}",
                    returncode=process.returncode,
                    stderr=stderr_text,
                )

            # Parse JSON output
            return self._parse_cli_output(stdout_text, fmt)

        except TimeoutError:
            logger.error("Claude CLI timed out", timeout=effective_timeout)
            if process:
                process.kill()
            raise ClaudeCLIError(
                f"Claude CLI timed out after {effective_timeout}s"
            ) from None

        except FileNotFoundError as e:
            logger.error("Claude CLI not found", cli_path=self.settings.cli_path)
            raise ClaudeCLIError(
                f"Claude CLI not found at {self.settings.cli_path}"
            ) from e

    def _parse_cli_output(self, output: str, output_format: str) -> dict[str, Any]:
        """Parse CLI output based on format.

        Args:
            output: Raw CLI output
            output_format: The output format used

        Returns:
            Parsed output as dict
        """
        if output_format == "json":
            # JSON format returns structured output
            try:
                data = json.loads(output)
                # The CLI json format wraps result in a structure
                if isinstance(data, dict) and "result" in data:
                    result_text = data.get("result", "")
                    # Try to parse the result as JSON if it looks like JSON
                    if isinstance(result_text, str) and result_text.strip().startswith("{"):
                        try:
                            return json.loads(result_text)
                        except json.JSONDecodeError:
                            return {"text": result_text}
                    return {"text": result_text}
                return data
            except json.JSONDecodeError:
                logger.warning("Failed to parse CLI JSON output")
                return {"text": output}

        elif output_format == "stream-json":
            # Stream JSON returns line-delimited JSON
            lines = output.strip().split("\n")
            result_text = ""
            for line in lines:
                try:
                    event = json.loads(line)
                    if event.get("type") == "text":
                        result_text += event.get("content", "")
                except json.JSONDecodeError:
                    continue
            # Try to parse accumulated text as JSON
            if result_text.strip().startswith("{"):
                try:
                    return json.loads(result_text)
                except json.JSONDecodeError:
                    pass
            return {"text": result_text}

        else:
            # Plain text output
            return {"text": output}

    async def analyze_system_state(
        self,
        context: dict[str, Any],
        system_prompt: str,
    ) -> dict[str, Any]:
        """Analyze system state using Claude CLI.

        Args:
            context: System state context dict
            system_prompt: System prompt for Claude

        Returns:
            Analysis result dict with summary, actions, etc.
        """
        prompt = f"""Analyze this system state and provide recommendations.

Current timestamp: {context.get('timestamp', 'unknown')}

System State:
{json.dumps(context, indent=2, default=str)}

Respond with JSON:
{{
    "summary": "Brief summary of system state",
    "actions_needed": true/false,
    "urgency": "critical|high|medium|low|info",
    "recommendations": ["List of human-readable recommendations"],
    "actions": [
        {{
            "name": "action_identifier",
            "description": "What this action does",
            "reason": "Why this action is recommended",
            "urgency": "critical|high|medium|low|info",
            "auto_execute": false,
            "command": "optional shell command",
            "parameters": {{}}
        }}
    ]
}}"""

        result = await self.run_prompt(
            prompt=prompt,
            system_prompt=system_prompt,
            output_format="json",
        )

        # Ensure required fields exist
        return {
            "summary": result.get("summary", "Analysis completed"),
            "actions_needed": result.get("actions_needed", False),
            "urgency": result.get("urgency", "info"),
            "recommendations": result.get("recommendations", []),
            "actions": result.get("actions", []),
            "raw_response": result,
        }

    async def ask(
        self,
        question: str,
        context: dict[str, Any] | None = None,
        system_prompt: str | None = None,
    ) -> str:
        """Ask Claude a question.

        Args:
            question: The question to ask
            context: Optional context dict
            system_prompt: Optional system prompt

        Returns:
            Claude's response as text
        """
        prompt = question
        if context:
            prompt += f"\n\nContext:\n{json.dumps(context, indent=2, default=str)}"

        result = await self.run_prompt(
            prompt=prompt,
            system_prompt=system_prompt,
            output_format="text",
        )

        return result.get("text", str(result))
