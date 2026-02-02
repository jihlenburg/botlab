"""GitLab MCP Server implementation.

This MCP server exposes GitLab API operations as tools that can be used
by Claude Code CLI for GitLab administration tasks.
"""

from __future__ import annotations

import os
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

# GitLab connection settings from environment
GITLAB_URL = os.environ.get("GITLAB_URL", "https://gitlab.example.com")
GITLAB_TOKEN = os.environ.get("GITLAB_TOKEN", "")

# Create MCP server
server = Server("gitlab-mcp")


def get_gitlab_client():
    """Get a python-gitlab client instance."""
    import gitlab

    return gitlab.Gitlab(GITLAB_URL, private_token=GITLAB_TOKEN)


@server.list_tools()
async def list_tools() -> list[Tool]:
    """List available GitLab tools."""
    return [
        Tool(
            name="list_projects",
            description="List GitLab projects with optional filters",
            inputSchema={
                "type": "object",
                "properties": {
                    "search": {
                        "type": "string",
                        "description": "Search query for project names",
                    },
                    "owned": {
                        "type": "boolean",
                        "description": "Only return projects owned by current user",
                        "default": False,
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of projects to return",
                        "default": 20,
                    },
                },
            },
        ),
        Tool(
            name="get_merge_requests",
            description="Get merge requests for a project or all accessible projects",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_id": {
                        "type": "integer",
                        "description": "Project ID (if not provided, gets MRs from all projects)",
                    },
                    "state": {
                        "type": "string",
                        "description": "MR state filter",
                        "enum": ["opened", "closed", "merged", "all"],
                        "default": "opened",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of MRs to return",
                        "default": 20,
                    },
                },
            },
        ),
        Tool(
            name="trigger_pipeline",
            description="Trigger a CI/CD pipeline for a project",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_id": {
                        "type": "integer",
                        "description": "Project ID",
                    },
                    "ref": {
                        "type": "string",
                        "description": "Branch or tag name to run pipeline on",
                        "default": "main",
                    },
                    "variables": {
                        "type": "object",
                        "description": "Pipeline variables as key-value pairs",
                        "additionalProperties": {"type": "string"},
                    },
                },
                "required": ["project_id"],
            },
        ),
        Tool(
            name="get_project_info",
            description="Get detailed information about a specific project",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_id": {
                        "type": "integer",
                        "description": "Project ID",
                    },
                },
                "required": ["project_id"],
            },
        ),
        Tool(
            name="get_pipeline_status",
            description="Get the status of pipelines for a project",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_id": {
                        "type": "integer",
                        "description": "Project ID",
                    },
                    "ref": {
                        "type": "string",
                        "description": "Filter by branch or tag name",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of pipelines to return",
                        "default": 10,
                    },
                },
                "required": ["project_id"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    """Execute a GitLab tool."""
    try:
        gl = get_gitlab_client()

        if name == "list_projects":
            return await _list_projects(gl, arguments)
        elif name == "get_merge_requests":
            return await _get_merge_requests(gl, arguments)
        elif name == "trigger_pipeline":
            return await _trigger_pipeline(gl, arguments)
        elif name == "get_project_info":
            return await _get_project_info(gl, arguments)
        elif name == "get_pipeline_status":
            return await _get_pipeline_status(gl, arguments)
        else:
            return [TextContent(type="text", text=f"Unknown tool: {name}")]

    except Exception as e:
        return [TextContent(type="text", text=f"Error: {e!s}")]


async def _list_projects(gl, args: dict[str, Any]) -> list[TextContent]:
    """List GitLab projects."""
    search = args.get("search")
    owned = args.get("owned", False)
    limit = args.get("limit", 20)

    projects = gl.projects.list(
        search=search,
        owned=owned,
        per_page=limit,
    )

    result = []
    for p in projects:
        result.append({
            "id": p.id,
            "name": p.name,
            "path_with_namespace": p.path_with_namespace,
            "web_url": p.web_url,
            "default_branch": getattr(p, "default_branch", "main"),
        })

    import json
    return [TextContent(type="text", text=json.dumps(result, indent=2))]


async def _get_merge_requests(gl, args: dict[str, Any]) -> list[TextContent]:
    """Get merge requests."""
    project_id = args.get("project_id")
    state = args.get("state", "opened")
    limit = args.get("limit", 20)

    if project_id:
        project = gl.projects.get(project_id)
        mrs = project.mergerequests.list(state=state, per_page=limit)
    else:
        mrs = gl.mergerequests.list(state=state, per_page=limit, scope="all")

    result = []
    for mr in mrs:
        result.append({
            "id": mr.id,
            "iid": mr.iid,
            "title": mr.title,
            "state": mr.state,
            "author": mr.author.get("username") if mr.author else None,
            "web_url": mr.web_url,
            "source_branch": mr.source_branch,
            "target_branch": mr.target_branch,
        })

    import json
    return [TextContent(type="text", text=json.dumps(result, indent=2))]


async def _trigger_pipeline(gl, args: dict[str, Any]) -> list[TextContent]:
    """Trigger a pipeline."""
    project_id = args["project_id"]
    ref = args.get("ref", "main")
    variables = args.get("variables", {})

    project = gl.projects.get(project_id)

    # Format variables for API
    var_list = [{"key": k, "value": v} for k, v in variables.items()]

    pipeline = project.pipelines.create({
        "ref": ref,
        "variables": var_list,
    })

    result = {
        "id": pipeline.id,
        "status": pipeline.status,
        "ref": pipeline.ref,
        "web_url": pipeline.web_url,
    }

    import json
    return [TextContent(type="text", text=json.dumps(result, indent=2))]


async def _get_project_info(gl, args: dict[str, Any]) -> list[TextContent]:
    """Get project information."""
    project_id = args["project_id"]
    project = gl.projects.get(project_id)

    result = {
        "id": project.id,
        "name": project.name,
        "path_with_namespace": project.path_with_namespace,
        "description": project.description,
        "web_url": project.web_url,
        "default_branch": project.default_branch,
        "visibility": project.visibility,
        "created_at": project.created_at,
        "last_activity_at": project.last_activity_at,
        "star_count": project.star_count,
        "forks_count": project.forks_count,
    }

    import json
    return [TextContent(type="text", text=json.dumps(result, indent=2))]


async def _get_pipeline_status(gl, args: dict[str, Any]) -> list[TextContent]:
    """Get pipeline status."""
    project_id = args["project_id"]
    ref = args.get("ref")
    limit = args.get("limit", 10)

    project = gl.projects.get(project_id)

    kwargs = {"per_page": limit}
    if ref:
        kwargs["ref"] = ref

    pipelines = project.pipelines.list(**kwargs)

    result = []
    for p in pipelines:
        result.append({
            "id": p.id,
            "status": p.status,
            "ref": p.ref,
            "sha": p.sha[:8] if p.sha else None,
            "created_at": p.created_at,
            "web_url": p.web_url,
        })

    import json
    return [TextContent(type="text", text=json.dumps(result, indent=2))]


async def main():
    """Run the MCP server."""
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
