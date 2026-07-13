"""Generate or merge MCP client configuration for the installed command."""

from __future__ import annotations

import json
import os
from pathlib import Path

import tomlkit

from nepa_mcp.registry import server_names


def server_entry(name: str, *, vscode: bool = False) -> dict:
    entry = {
        "command": "nepa-mcp",
        "args": ["server", name],
        "env": {"PYTHONUNBUFFERED": "1"},
    }
    if vscode:
        return {"type": "stdio", **entry}
    return entry


def default_client_path(client: str) -> Path:
    if client == "codex":
        return Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")) / "config.toml"
    if client == "claude":
        return Path.cwd() / ".mcp.json"
    if client == "vscode":
        return Path.cwd() / ".vscode" / "mcp.json"
    raise ValueError(f"unsupported client: {client}")


def _merge_json(existing_text: str, client: str) -> str:
    data = json.loads(existing_text) if existing_text.strip() else {}
    top_level = "servers" if client == "vscode" else "mcpServers"
    servers = dict(data.get(top_level) or {})
    servers.pop("nepa", None)  # Remove the former aggregate registration.
    for name in server_names():
        servers[name] = server_entry(name, vscode=client == "vscode")
    data[top_level] = servers
    return json.dumps(data, indent=2) + "\n"


def _merge_codex(existing_text: str) -> str:
    document = tomlkit.parse(existing_text) if existing_text.strip() else tomlkit.document()
    servers = document.get("mcp_servers")
    if servers is None:
        servers = tomlkit.table()
        document["mcp_servers"] = servers

    servers.pop("nepa", None)  # Remove the former aggregate registration.
    for name in server_names():
        entry = tomlkit.table()
        entry["command"] = "nepa-mcp"
        entry["args"] = ["server", name]
        entry["env"] = {"PYTHONUNBUFFERED": "1"}
        servers[name] = entry
    return tomlkit.dumps(document)


def render_client_config(client: str, existing_text: str = "") -> str:
    if client == "codex":
        return _merge_codex(existing_text)
    if client in {"claude", "vscode"}:
        return _merge_json(existing_text, client)
    raise ValueError(f"unsupported client: {client}")


def _write_atomically(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        backup = path.with_suffix(path.suffix + ".nepa-mcp.bak")
        if not backup.exists():
            backup.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def configure_client(
    client: str,
    *,
    path: Path | None = None,
    dry_run: bool = False,
) -> tuple[Path, str]:
    target = path or default_client_path(client)
    existing_text = target.read_text(encoding="utf-8") if target.exists() else ""
    rendered = render_client_config(client, existing_text)
    if not dry_run:
        _write_atomically(target, rendered)
    return target, rendered
