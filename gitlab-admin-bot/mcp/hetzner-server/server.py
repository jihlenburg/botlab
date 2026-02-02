"""Hetzner Cloud MCP Server implementation.

This MCP server exposes Hetzner Cloud API operations as tools that can be used
by Claude Code CLI for infrastructure management tasks.
"""

from __future__ import annotations

import os
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

# Hetzner connection settings from environment
HETZNER_TOKEN = os.environ.get("HETZNER_TOKEN", "")
HETZNER_LOCATION = os.environ.get("HETZNER_LOCATION", "fsn1")

# Create MCP server
server = Server("hetzner-mcp")


def get_hcloud_client():
    """Get a hcloud client instance."""
    from hcloud import Client

    return Client(token=HETZNER_TOKEN)


@server.list_tools()
async def list_tools() -> list[Tool]:
    """List available Hetzner tools."""
    return [
        Tool(
            name="list_servers",
            description="List all servers in the Hetzner Cloud project",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Filter by server name (partial match)",
                    },
                    "status": {
                        "type": "string",
                        "description": "Filter by server status",
                        "enum": ["running", "off", "starting", "stopping", "migrating"],
                    },
                },
            },
        ),
        Tool(
            name="get_server_status",
            description="Get detailed status of a specific server",
            inputSchema={
                "type": "object",
                "properties": {
                    "server_id": {
                        "type": "integer",
                        "description": "Server ID",
                    },
                    "server_name": {
                        "type": "string",
                        "description": "Server name (alternative to server_id)",
                    },
                },
            },
        ),
        Tool(
            name="create_server",
            description="Create a new server in Hetzner Cloud (requires approval)",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Server name",
                    },
                    "server_type": {
                        "type": "string",
                        "description": "Server type (e.g., cpx31, cx32)",
                        "default": "cx22",
                    },
                    "image": {
                        "type": "string",
                        "description": "Image name or ID",
                        "default": "ubuntu-24.04",
                    },
                    "location": {
                        "type": "string",
                        "description": "Datacenter location",
                        "default": "fsn1",
                    },
                    "ssh_keys": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "SSH key names to add",
                    },
                    "user_data": {
                        "type": "string",
                        "description": "Cloud-init user data",
                    },
                },
                "required": ["name"],
            },
        ),
        Tool(
            name="power_action",
            description="Perform power action on a server (start, stop, reboot)",
            inputSchema={
                "type": "object",
                "properties": {
                    "server_id": {
                        "type": "integer",
                        "description": "Server ID",
                    },
                    "action": {
                        "type": "string",
                        "description": "Power action to perform",
                        "enum": ["start", "stop", "reboot", "shutdown"],
                    },
                },
                "required": ["server_id", "action"],
            },
        ),
        Tool(
            name="list_volumes",
            description="List all volumes in the project",
            inputSchema={
                "type": "object",
                "properties": {
                    "server_id": {
                        "type": "integer",
                        "description": "Filter by attached server ID",
                    },
                },
            },
        ),
        Tool(
            name="get_server_metrics",
            description="Get server metrics (CPU, disk, network)",
            inputSchema={
                "type": "object",
                "properties": {
                    "server_id": {
                        "type": "integer",
                        "description": "Server ID",
                    },
                    "metric_type": {
                        "type": "string",
                        "description": "Type of metrics to retrieve",
                        "enum": ["cpu", "disk", "network"],
                        "default": "cpu",
                    },
                    "start": {
                        "type": "string",
                        "description": "Start time (ISO 8601 format)",
                    },
                    "end": {
                        "type": "string",
                        "description": "End time (ISO 8601 format)",
                    },
                },
                "required": ["server_id"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    """Execute a Hetzner tool."""
    try:
        client = get_hcloud_client()

        if name == "list_servers":
            return await _list_servers(client, arguments)
        elif name == "get_server_status":
            return await _get_server_status(client, arguments)
        elif name == "create_server":
            return await _create_server(client, arguments)
        elif name == "power_action":
            return await _power_action(client, arguments)
        elif name == "list_volumes":
            return await _list_volumes(client, arguments)
        elif name == "get_server_metrics":
            return await _get_server_metrics(client, arguments)
        else:
            return [TextContent(type="text", text=f"Unknown tool: {name}")]

    except Exception as e:
        return [TextContent(type="text", text=f"Error: {e!s}")]


async def _list_servers(client, args: dict[str, Any]) -> list[TextContent]:
    """List all servers."""
    name_filter = args.get("name")
    status_filter = args.get("status")

    servers = client.servers.get_all(name=name_filter)

    result = []
    for s in servers:
        if status_filter and s.status != status_filter:
            continue

        result.append({
            "id": s.id,
            "name": s.name,
            "status": s.status,
            "server_type": s.server_type.name,
            "datacenter": s.datacenter.name,
            "public_ip": s.public_net.ipv4.ip if s.public_net.ipv4 else None,
            "private_ip": (
                s.private_net[0].ip if s.private_net else None
            ),
            "created": s.created.isoformat() if s.created else None,
        })

    import json
    return [TextContent(type="text", text=json.dumps(result, indent=2))]


async def _get_server_status(client, args: dict[str, Any]) -> list[TextContent]:
    """Get detailed server status."""
    server_id = args.get("server_id")
    server_name = args.get("server_name")

    if server_id:
        server = client.servers.get_by_id(server_id)
    elif server_name:
        server = client.servers.get_by_name(server_name)
    else:
        return [TextContent(type="text", text="Error: Must provide server_id or server_name")]

    if not server:
        return [TextContent(type="text", text="Server not found")]

    result = {
        "id": server.id,
        "name": server.name,
        "status": server.status,
        "server_type": {
            "name": server.server_type.name,
            "cores": server.server_type.cores,
            "memory": server.server_type.memory,
            "disk": server.server_type.disk,
        },
        "datacenter": {
            "name": server.datacenter.name,
            "location": server.datacenter.location.name,
        },
        "public_net": {
            "ipv4": server.public_net.ipv4.ip if server.public_net.ipv4 else None,
            "ipv6": server.public_net.ipv6.ip if server.public_net.ipv6 else None,
        },
        "private_net": [
            {"ip": pn.ip, "network_id": pn.network.id}
            for pn in server.private_net
        ] if server.private_net else [],
        "volumes": [v.id for v in server.volumes] if server.volumes else [],
        "created": server.created.isoformat() if server.created else None,
        "labels": server.labels,
    }

    import json
    return [TextContent(type="text", text=json.dumps(result, indent=2))]


async def _create_server(client, args: dict[str, Any]) -> list[TextContent]:
    """Create a new server."""
    from hcloud.images import Image
    from hcloud.locations import Location
    from hcloud.server_types import ServerType

    name = args["name"]
    server_type = args.get("server_type", "cx22")
    image = args.get("image", "ubuntu-24.04")
    location = args.get("location", HETZNER_LOCATION)
    ssh_key_names = args.get("ssh_keys", [])
    user_data = args.get("user_data")

    # Get SSH keys by name
    ssh_keys = []
    for key_name in ssh_key_names:
        key = client.ssh_keys.get_by_name(key_name)
        if key:
            ssh_keys.append(key)

    response = client.servers.create(
        name=name,
        server_type=ServerType(name=server_type),
        image=Image(name=image),
        location=Location(name=location),
        ssh_keys=ssh_keys if ssh_keys else None,
        user_data=user_data,
    )

    result = {
        "server": {
            "id": response.server.id,
            "name": response.server.name,
            "status": response.server.status,
            "public_ip": (
                response.server.public_net.ipv4.ip
                if response.server.public_net.ipv4 else None
            ),
        },
        "action": {
            "id": response.action.id,
            "status": response.action.status,
        },
        "root_password": response.root_password,
    }

    import json
    return [TextContent(type="text", text=json.dumps(result, indent=2))]


async def _power_action(client, args: dict[str, Any]) -> list[TextContent]:
    """Perform power action on server."""
    server_id = args["server_id"]
    action = args["action"]

    server = client.servers.get_by_id(server_id)
    if not server:
        return [TextContent(type="text", text="Server not found")]

    if action == "start":
        response = client.servers.power_on(server)
    elif action == "stop":
        response = client.servers.power_off(server)
    elif action == "reboot":
        response = client.servers.reboot(server)
    elif action == "shutdown":
        response = client.servers.shutdown(server)
    else:
        return [TextContent(type="text", text=f"Unknown action: {action}")]

    result = {
        "action_id": response.id,
        "status": response.status,
        "command": response.command,
    }

    import json
    return [TextContent(type="text", text=json.dumps(result, indent=2))]


async def _list_volumes(client, args: dict[str, Any]) -> list[TextContent]:
    """List all volumes."""
    server_id = args.get("server_id")

    volumes = client.volumes.get_all()

    result = []
    for v in volumes:
        # Filter by server if specified
        if server_id and (not v.server or v.server.id != server_id):
            continue

        result.append({
            "id": v.id,
            "name": v.name,
            "size": v.size,
            "server_id": v.server.id if v.server else None,
            "location": v.location.name,
            "linux_device": v.linux_device,
            "status": v.status,
        })

    import json
    return [TextContent(type="text", text=json.dumps(result, indent=2))]


async def _get_server_metrics(client, args: dict[str, Any]) -> list[TextContent]:
    """Get server metrics."""
    from datetime import datetime, timedelta

    server_id = args["server_id"]
    metric_type = args.get("metric_type", "cpu")

    server = client.servers.get_by_id(server_id)
    if not server:
        return [TextContent(type="text", text="Server not found")]

    # Default time range: last hour
    end = datetime.now()
    start = end - timedelta(hours=1)

    if args.get("start"):
        start = datetime.fromisoformat(args["start"].replace("Z", "+00:00"))
    if args.get("end"):
        end = datetime.fromisoformat(args["end"].replace("Z", "+00:00"))

    metrics = client.servers.get_metrics(
        server,
        type=metric_type,
        start=start,
        end=end,
    )

    result = {
        "server_id": server_id,
        "metric_type": metric_type,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "time_series": metrics.time_series,
    }

    import json
    return [TextContent(type="text", text=json.dumps(result, indent=2, default=str))]


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
