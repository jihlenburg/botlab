"""BorgBackup MCP Server implementation.

This MCP server exposes BorgBackup operations as tools that can be used
by Claude Code CLI for backup management tasks.
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

# Borg connection settings from environment
BORG_REPO = os.environ.get("BORG_REPO", "")
BORG_PASSPHRASE = os.environ.get("BORG_PASSPHRASE", "")
BORG_RSH = os.environ.get("BORG_RSH", "ssh -o StrictHostKeyChecking=accept-new")

# Create MCP server
server = Server("borg-mcp")


async def run_borg_command(
    args: list[str],
    timeout: int = 300,
    env_override: dict[str, str] | None = None,
) -> tuple[str, str, int]:
    """Run a borg command and return stdout, stderr, returncode."""
    env = os.environ.copy()
    env["BORG_REPO"] = BORG_REPO
    env["BORG_PASSPHRASE"] = BORG_PASSPHRASE
    env["BORG_RSH"] = BORG_RSH

    if env_override:
        env.update(env_override)

    process = await asyncio.create_subprocess_exec(
        "borg",
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )

    try:
        stdout, stderr = await asyncio.wait_for(
            process.communicate(),
            timeout=timeout,
        )
        return (
            stdout.decode("utf-8"),
            stderr.decode("utf-8"),
            process.returncode or 0,
        )
    except TimeoutError:
        process.kill()
        return "", f"Command timed out after {timeout}s", -1


@server.list_tools()
async def list_tools() -> list[Tool]:
    """List available Borg backup tools."""
    return [
        Tool(
            name="list_archives",
            description="List all backup archives in the repository",
            inputSchema={
                "type": "object",
                "properties": {
                    "prefix": {
                        "type": "string",
                        "description": "Filter archives by prefix",
                    },
                    "last": {
                        "type": "integer",
                        "description": "Only show last N archives",
                    },
                    "json_output": {
                        "type": "boolean",
                        "description": "Return detailed JSON output",
                        "default": True,
                    },
                },
            },
        ),
        Tool(
            name="check_repo",
            description="Check the repository and archives for consistency",
            inputSchema={
                "type": "object",
                "properties": {
                    "verify_data": {
                        "type": "boolean",
                        "description": "Verify data integrity (slower but more thorough)",
                        "default": False,
                    },
                    "archive": {
                        "type": "string",
                        "description": "Check only this specific archive",
                    },
                },
            },
        ),
        Tool(
            name="get_backup_info",
            description="Get detailed information about a specific archive",
            inputSchema={
                "type": "object",
                "properties": {
                    "archive": {
                        "type": "string",
                        "description": "Archive name (use 'last' for most recent)",
                        "default": "last",
                    },
                },
            },
        ),
        Tool(
            name="repo_info",
            description="Get repository information (size, encryption, etc.)",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
        Tool(
            name="compact_repo",
            description="Compact the repository to free space (safe operation)",
            inputSchema={
                "type": "object",
                "properties": {
                    "threshold": {
                        "type": "integer",
                        "description": "Minimum percentage of unused space to trigger compaction",
                        "default": 10,
                    },
                },
            },
        ),
        Tool(
            name="list_archive_contents",
            description="List contents of a specific archive (files and directories)",
            inputSchema={
                "type": "object",
                "properties": {
                    "archive": {
                        "type": "string",
                        "description": "Archive name",
                    },
                    "path": {
                        "type": "string",
                        "description": "Filter by path prefix",
                    },
                    "pattern": {
                        "type": "string",
                        "description": "Filter by pattern (e.g., '*.sql')",
                    },
                },
                "required": ["archive"],
            },
        ),
        Tool(
            name="diff_archives",
            description="Show differences between two archives",
            inputSchema={
                "type": "object",
                "properties": {
                    "archive1": {
                        "type": "string",
                        "description": "First archive name",
                    },
                    "archive2": {
                        "type": "string",
                        "description": "Second archive name",
                    },
                },
                "required": ["archive1", "archive2"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    """Execute a Borg backup tool."""
    try:
        if name == "list_archives":
            return await _list_archives(arguments)
        elif name == "check_repo":
            return await _check_repo(arguments)
        elif name == "get_backup_info":
            return await _get_backup_info(arguments)
        elif name == "repo_info":
            return await _repo_info(arguments)
        elif name == "compact_repo":
            return await _compact_repo(arguments)
        elif name == "list_archive_contents":
            return await _list_archive_contents(arguments)
        elif name == "diff_archives":
            return await _diff_archives(arguments)
        else:
            return [TextContent(type="text", text=f"Unknown tool: {name}")]

    except Exception as e:
        return [TextContent(type="text", text=f"Error: {e!s}")]


async def _list_archives(args: dict[str, Any]) -> list[TextContent]:
    """List backup archives."""
    cmd = ["list"]

    if args.get("json_output", True):
        cmd.append("--json")

    if args.get("prefix"):
        cmd.extend(["--prefix", args["prefix"]])

    if args.get("last"):
        cmd.extend(["--last", str(args["last"])])

    stdout, stderr, returncode = await run_borg_command(cmd)

    if returncode != 0:
        return [TextContent(type="text", text=f"Error: {stderr}")]

    # Parse JSON output if available
    if args.get("json_output", True):
        try:
            data = json.loads(stdout)
            archives = []
            for archive in data.get("archives", []):
                archives.append({
                    "name": archive.get("name"),
                    "start": archive.get("start"),
                    "end": archive.get("end"),
                    "id": archive.get("id", "")[:12],
                })
            return [TextContent(type="text", text=json.dumps(archives, indent=2))]
        except json.JSONDecodeError:
            pass

    return [TextContent(type="text", text=stdout)]


async def _check_repo(args: dict[str, Any]) -> list[TextContent]:
    """Check repository integrity."""
    cmd = ["check"]

    if args.get("verify_data"):
        cmd.append("--verify-data")

    if args.get("archive"):
        cmd.append(f"::{args['archive']}")

    # Repository checks can take a while
    stdout, stderr, returncode = await run_borg_command(cmd, timeout=1800)

    result = {
        "success": returncode == 0,
        "returncode": returncode,
        "output": stdout if stdout else stderr,
    }

    return [TextContent(type="text", text=json.dumps(result, indent=2))]


async def _get_backup_info(args: dict[str, Any]) -> list[TextContent]:
    """Get archive information."""
    archive = args.get("archive", "last")

    # Use --last 1 for "last" archive
    if archive == "last":
        cmd = ["info", "--json", "--last", "1"]
    else:
        cmd = ["info", "--json", f"::{archive}"]

    stdout, stderr, returncode = await run_borg_command(cmd)

    if returncode != 0:
        return [TextContent(type="text", text=f"Error: {stderr}")]

    try:
        data = json.loads(stdout)
        archives = data.get("archives", [])
        if archives:
            archive_info = archives[0]
            stats = archive_info.get("stats", {})
            result = {
                "name": archive_info.get("name"),
                "start": archive_info.get("start"),
                "end": archive_info.get("end"),
                "duration_seconds": archive_info.get("duration"),
                "stats": {
                    "original_size": _format_size(stats.get("original_size", 0)),
                    "compressed_size": _format_size(stats.get("compressed_size", 0)),
                    "deduplicated_size": _format_size(stats.get("deduplicated_size", 0)),
                    "nfiles": stats.get("nfiles"),
                },
                "hostname": archive_info.get("hostname"),
                "username": archive_info.get("username"),
            }
            return [TextContent(type="text", text=json.dumps(result, indent=2))]
    except json.JSONDecodeError:
        pass

    return [TextContent(type="text", text=stdout)]


async def _repo_info(args: dict[str, Any]) -> list[TextContent]:
    """Get repository information."""
    cmd = ["info", "--json"]

    stdout, stderr, returncode = await run_borg_command(cmd)

    if returncode != 0:
        return [TextContent(type="text", text=f"Error: {stderr}")]

    try:
        data = json.loads(stdout)
        repo = data.get("repository", {})
        cache = data.get("cache", {})
        stats = cache.get("stats", {})

        result = {
            "repository": {
                "id": repo.get("id", "")[:12],
                "location": repo.get("location"),
                "last_modified": repo.get("last_modified"),
            },
            "stats": {
                "total_chunks": stats.get("total_chunks"),
                "total_size": _format_size(stats.get("total_size", 0)),
                "total_csize": _format_size(stats.get("total_csize", 0)),
                "unique_chunks": stats.get("unique_chunks"),
                "unique_size": _format_size(stats.get("unique_size", 0)),
            },
            "encryption": data.get("encryption", {}).get("mode"),
        }
        return [TextContent(type="text", text=json.dumps(result, indent=2))]
    except json.JSONDecodeError:
        pass

    return [TextContent(type="text", text=stdout)]


async def _compact_repo(args: dict[str, Any]) -> list[TextContent]:
    """Compact the repository."""
    threshold = args.get("threshold", 10)
    cmd = ["compact", f"--threshold={threshold}"]

    stdout, stderr, returncode = await run_borg_command(cmd, timeout=3600)

    result = {
        "success": returncode == 0,
        "returncode": returncode,
        "output": stdout if stdout else stderr,
    }

    return [TextContent(type="text", text=json.dumps(result, indent=2))]


async def _list_archive_contents(args: dict[str, Any]) -> list[TextContent]:
    """List archive contents."""
    archive = args["archive"]
    cmd = ["list", "--json-lines", f"::{archive}"]

    if args.get("path"):
        cmd.append(args["path"])

    if args.get("pattern"):
        cmd.extend(["--pattern", args["pattern"]])

    stdout, stderr, returncode = await run_borg_command(cmd, timeout=600)

    if returncode != 0:
        return [TextContent(type="text", text=f"Error: {stderr}")]

    # Parse JSON lines output
    files = []
    for line in stdout.strip().split("\n"):
        if not line:
            continue
        try:
            item = json.loads(line)
            files.append({
                "path": item.get("path"),
                "type": item.get("type"),
                "size": item.get("size"),
                "mtime": item.get("mtime"),
            })
        except json.JSONDecodeError:
            continue

    # Limit output to prevent overwhelming responses
    if len(files) > 100:
        return [TextContent(
            type="text",
            text=json.dumps({
                "total_files": len(files),
                "showing": 100,
                "files": files[:100],
            }, indent=2)
        )]

    return [TextContent(type="text", text=json.dumps(files, indent=2))]


async def _diff_archives(args: dict[str, Any]) -> list[TextContent]:
    """Show differences between archives."""
    archive1 = args["archive1"]
    archive2 = args["archive2"]

    cmd = ["diff", f"::{archive1}", f"::{archive2}"]

    stdout, stderr, returncode = await run_borg_command(cmd, timeout=600)

    if returncode != 0:
        return [TextContent(type="text", text=f"Error: {stderr}")]

    # Parse diff output
    changes = {"added": [], "removed": [], "modified": []}
    for line in stdout.strip().split("\n"):
        if not line:
            continue
        if line.startswith("added "):
            changes["added"].append(line[6:])
        elif line.startswith("removed "):
            changes["removed"].append(line[8:])
        elif line.startswith("modified ") or line.startswith("changed "):
            changes["modified"].append(line.split(" ", 1)[1] if " " in line else line)

    result = {
        "archive1": archive1,
        "archive2": archive2,
        "summary": {
            "added": len(changes["added"]),
            "removed": len(changes["removed"]),
            "modified": len(changes["modified"]),
        },
        "changes": changes,
    }

    return [TextContent(type="text", text=json.dumps(result, indent=2))]


def _format_size(size_bytes: int) -> str:
    """Format bytes to human readable size."""
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if abs(size_bytes) < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} PB"


async def main():
    """Run the MCP server."""
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


if __name__ == "__main__":
    asyncio.run(main())
