"""AI-powered system analyst using Claude API."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

import anthropic
import structlog

from src.config import ClaudeSettings

logger = structlog.get_logger(__name__)


class Urgency(str, Enum):
    """Urgency levels for recommended actions."""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


@dataclass
class RecommendedAction:
    """A recommended administrative action."""

    name: str
    description: str
    reason: str
    urgency: Urgency
    auto_execute: bool = False
    command: str | None = None
    parameters: dict[str, Any] = field(default_factory=dict)


@dataclass
class AnalysisResult:
    """Result of AI system analysis."""

    timestamp: datetime
    summary: str
    actions_needed: bool
    urgency: Urgency
    recommendations: list[str]
    recommended_actions: list[RecommendedAction]
    raw_analysis: str


SYSTEM_PROMPT = """You are an expert GitLab system administrator AI assistant for ACME Corp.
Your role is to analyze system health, resource usage, and backup status to identify issues and recommend actions.

You have access to monitoring data from a GitLab CE instance running on Hetzner Cloud.
The infrastructure consists of:
- GitLab Primary server (CPX31: 4 vCPU, 16GB RAM)
- Admin Bot server (CX32: 4 vCPU, 8GB RAM)
- BorgBackup to Hetzner Storage Box (hourly backups)
- Object storage for LFS, artifacts, uploads

Your responsibilities:
1. Identify potential issues before they become critical
2. Recommend preventive maintenance actions
3. Detect anomalies in resource usage patterns
4. Verify backup health and recommend restore tests
5. Suggest security improvements
6. Optimize performance when possible

When analyzing, consider:
- Disk usage trends (alert before running out)
- Memory pressure and swap usage
- CPU load patterns
- Backup age and success rate
- GitLab service health
- SSL certificate expiry
- Security best practices

Output your analysis as JSON with this structure:
{
    "summary": "Brief summary of system state",
    "actions_needed": true/false,
    "urgency": "critical|high|medium|low|info",
    "recommendations": ["List of human-readable recommendations"],
    "actions": [
        {
            "name": "action_identifier",
            "description": "What this action does",
            "reason": "Why this action is recommended",
            "urgency": "critical|high|medium|low|info",
            "auto_execute": false,
            "command": "optional shell command",
            "parameters": {}
        }
    ]
}

Safe actions that can be auto-executed (auto_execute: true):
- cleanup_old_artifacts: Remove artifacts older than retention period
- cleanup_docker_images: Run container registry garbage collection
- rotate_logs: Rotate and compress old log files
- send_daily_report: Generate and send status report

Actions requiring human approval (auto_execute: false):
- restart_service: Restart a GitLab service
- run_backup: Trigger an immediate backup
- expand_storage: Increase volume size
- update_gitlab: Update GitLab to newer version
- restore_test: Spin up test VM for backup verification

Always err on the side of caution. If unsure, recommend manual review."""


class AIAnalyst:
    """AI-powered system analyst using Claude API."""

    def __init__(self, settings: ClaudeSettings) -> None:
        self.settings = settings
        self.client = anthropic.Anthropic(
            api_key=settings.api_key.get_secret_value()
        )
        self._history: list[AnalysisResult] = []

    async def analyze_system_state(
        self,
        health: dict[str, Any],
        resources: dict[str, Any],
        backup: dict[str, Any],
        additional_context: str | None = None,
    ) -> AnalysisResult:
        """Analyze system state and recommend actions."""
        logger.info("Starting AI analysis")

        # Prepare the context for Claude
        context = self._prepare_context(health, resources, backup, additional_context)

        try:
            # Call Claude API
            message = self.client.messages.create(
                model=self.settings.model,
                max_tokens=self.settings.max_tokens,
                system=SYSTEM_PROMPT,
                messages=[
                    {
                        "role": "user",
                        "content": f"""Please analyze the current system state and provide recommendations.

Current timestamp: {datetime.now().isoformat()}

{context}

Provide your analysis as JSON.""",
                    }
                ],
            )

            # Parse response
            response_text = message.content[0].text
            result = self._parse_response(response_text)

            # Store in history
            self._history.append(result)
            if len(self._history) > 100:
                self._history = self._history[-100:]

            logger.info(
                "AI analysis complete",
                actions_needed=result.actions_needed,
                urgency=result.urgency.value,
                action_count=len(result.recommended_actions),
            )

            return result

        except anthropic.APIError as e:
            logger.error("Claude API error", error=str(e))
            raise
        except Exception as e:
            logger.error("AI analysis failed", error=str(e))
            raise

    def _prepare_context(
        self,
        health: dict[str, Any],
        resources: dict[str, Any],
        backup: dict[str, Any],
        additional_context: str | None,
    ) -> str:
        """Prepare context string for Claude."""
        sections = []

        sections.append("## GitLab Health Status")
        sections.append(json.dumps(health, indent=2, default=str))

        sections.append("\n## Resource Usage")
        sections.append(json.dumps(resources, indent=2, default=str))

        sections.append("\n## Backup Status")
        sections.append(json.dumps(backup, indent=2, default=str))

        if additional_context:
            sections.append("\n## Additional Context")
            sections.append(additional_context)

        # Add recent history summary if available
        if self._history:
            recent = self._history[-5:]
            sections.append("\n## Recent Analysis History")
            for h in recent:
                sections.append(
                    f"- {h.timestamp.isoformat()}: {h.summary} (urgency: {h.urgency.value})"
                )

        return "\n".join(sections)

    def _parse_response(self, response_text: str) -> AnalysisResult:
        """Parse Claude's response into an AnalysisResult."""
        # Try to extract JSON from response
        try:
            # Handle markdown code blocks
            if "```json" in response_text:
                json_str = response_text.split("```json")[1].split("```")[0]
            elif "```" in response_text:
                json_str = response_text.split("```")[1].split("```")[0]
            else:
                json_str = response_text

            data = json.loads(json_str.strip())
        except json.JSONDecodeError:
            logger.warning("Failed to parse JSON response, using raw text")
            return AnalysisResult(
                timestamp=datetime.now(),
                summary="Analysis completed (non-JSON response)",
                actions_needed=False,
                urgency=Urgency.INFO,
                recommendations=[response_text],
                recommended_actions=[],
                raw_analysis=response_text,
            )

        # Parse actions
        actions = []
        for action_data in data.get("actions", []):
            actions.append(
                RecommendedAction(
                    name=action_data.get("name", "unknown"),
                    description=action_data.get("description", ""),
                    reason=action_data.get("reason", ""),
                    urgency=Urgency(action_data.get("urgency", "info")),
                    auto_execute=action_data.get("auto_execute", False),
                    command=action_data.get("command"),
                    parameters=action_data.get("parameters", {}),
                )
            )

        return AnalysisResult(
            timestamp=datetime.now(),
            summary=data.get("summary", "No summary provided"),
            actions_needed=data.get("actions_needed", False),
            urgency=Urgency(data.get("urgency", "info")),
            recommendations=data.get("recommendations", []),
            recommended_actions=actions,
            raw_analysis=response_text,
        )

    async def ask(self, question: str, context: dict[str, Any] | None = None) -> str:
        """Ask Claude a specific question about the system."""
        context_str = ""
        if context:
            context_str = f"\n\nContext:\n{json.dumps(context, indent=2, default=str)}"

        message = self.client.messages.create(
            model=self.settings.model,
            max_tokens=self.settings.max_tokens,
            system=SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": f"{question}{context_str}",
                }
            ],
        )

        return message.content[0].text

    def get_history(self, limit: int = 10) -> list[AnalysisResult]:
        """Get recent analysis history."""
        return self._history[-limit:]
