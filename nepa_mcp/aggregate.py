"""Aggregate all domain servers behind one MCP stdio connection."""

from __future__ import annotations

import sys

from fastmcp import FastMCP
from fastmcp.server import create_proxy

from nepa_mcp.config import load_credentials
from nepa_mcp.registry import server_names


def child_server_config(name: str) -> dict:
    return {
        "mcpServers": {
            name: {
                "command": sys.executable,
                "args": ["-m", "nepa_mcp", "server", name],
                "env": {"PYTHONUNBUFFERED": "1"},
            }
        }
    }


def build_aggregate_server() -> FastMCP:
    """Build a proxy that keeps every flat server in its own subprocess."""
    load_credentials()
    aggregate = FastMCP("nepa-mcp")
    for name in server_names():
        proxy = create_proxy(child_server_config(name), name=f"{name}-proxy")
        aggregate.mount(proxy)
    return aggregate


def run_aggregate_server() -> None:
    build_aggregate_server().run(transport="stdio", show_banner=False)
