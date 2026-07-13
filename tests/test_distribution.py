from __future__ import annotations

import asyncio
import json
import os
import stat
from pathlib import Path

from fastmcp import Client

from nepa_mcp import cli
from nepa_mcp.aggregate import build_aggregate_server, child_server_config
from nepa_mcp.clients import render_client_config
from nepa_mcp.config import create_credential_template, load_credentials
from nepa_mcp.registry import CREDENTIAL_VARIABLES, SERVER_SPECS, server_entrypoint


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_SERVERS = {
    "blm",
    "census",
    "cfr",
    "efh",
    "epa_aqs",
    "esa_ranges",
    "fema_nfhl",
    "gbif",
    "gis",
    "ipac",
    "nepa_assist",
    "noaa",
    "nrhp",
    "padus",
    "pcsrf",
    "tigerweb_counties",
    "tribal",
    "usace",
}


def test_registry_matches_the_public_server_inventory() -> None:
    assert {spec.name for spec in SERVER_SPECS} == EXPECTED_SERVERS
    assert all(server_entrypoint(spec.name).is_file() for spec in SERVER_SPECS)
    assert CREDENTIAL_VARIABLES == (
        "CENSUS_API_KEY",
        "EPA_AQS_EMAIL",
        "EPA_AQS_API_KEY",
    )


def test_child_servers_use_the_current_interpreter_and_stdio_cli() -> None:
    config = child_server_config("gis")["mcpServers"]["gis"]
    assert config["command"] == os.sys.executable
    assert config["args"] == ["-m", "nepa_mcp", "server", "gis"]
    assert config["env"] == {"PYTHONUNBUFFERED": "1"}


def test_credential_template_is_private_and_environment_wins(tmp_path, monkeypatch) -> None:
    config_path = tmp_path / "config" / "credentials.env"
    monkeypatch.setenv("NEPA_MCP_CONFIG_FILE", str(config_path))
    for variable in CREDENTIAL_VARIABLES:
        monkeypatch.delenv(variable, raising=False)

    path, created = create_credential_template()
    assert created is True
    assert path == config_path
    assert stat.S_IMODE(path.stat().st_mode) == 0o600

    path.write_text(
        "CENSUS_API_KEY=file-census\nEPA_AQS_EMAIL=file@example.test\nEPA_AQS_API_KEY=file-aqs\n",
        encoding="utf-8",
    )
    path.chmod(0o600)
    monkeypatch.setenv("CENSUS_API_KEY", "environment-census")
    sources = load_credentials()

    assert os.environ["CENSUS_API_KEY"] == "environment-census"
    assert sources["CENSUS_API_KEY"] == "environment"
    assert sources["EPA_AQS_EMAIL"] == "user config"
    assert sources["EPA_AQS_API_KEY"] == "user config"

    _, created_again = create_credential_template()
    assert created_again is False
    assert "file-census" in path.read_text(encoding="utf-8")


def test_doctor_never_prints_credential_values(tmp_path, monkeypatch, capsys) -> None:
    secret = "do-not-print-this-value"
    monkeypatch.setenv("NEPA_MCP_CONFIG_FILE", str(tmp_path / "missing.env"))
    monkeypatch.setenv("CENSUS_API_KEY", secret)
    monkeypatch.setenv("EPA_AQS_EMAIL", "person@example.test")
    monkeypatch.setenv("EPA_AQS_API_KEY", secret)

    assert cli.doctor() == 0
    output = capsys.readouterr().out
    assert secret not in output
    assert "person@example.test" not in output
    assert "configured via environment" in output


def test_client_config_generation_preserves_unrelated_entries() -> None:
    claude = render_client_config(
        "claude",
        json.dumps({"mcpServers": {"other": {"command": "node", "args": ["server.js"]}}}),
    )
    claude_data = json.loads(claude)
    assert "other" in claude_data["mcpServers"]
    assert "nepa" not in claude_data["mcpServers"]
    assert EXPECTED_SERVERS <= set(claude_data["mcpServers"])
    for server_name in EXPECTED_SERVERS:
        assert claude_data["mcpServers"][server_name]["args"] == ["server", server_name]

    codex = render_client_config(
        "codex",
        'model = "gpt-5"\n\n[mcp_servers.other]\ncommand = "node"\n',
    )
    assert 'model = "gpt-5"' in codex
    assert "[mcp_servers.other]" in codex
    assert "[mcp_servers.nepa]" not in codex
    for server_name in EXPECTED_SERVERS:
        assert f"[mcp_servers.{server_name}]" in codex
        assert f'args = ["server", "{server_name}"]' in codex


def test_plugin_and_marketplace_register_independent_servers() -> None:
    plugin_root = ROOT / "plugins" / "nepa-mcp"
    manifest = json.loads((plugin_root / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
    mcp_config = json.loads((plugin_root / ".mcp.json").read_text(encoding="utf-8"))
    marketplace = json.loads((ROOT / ".agents" / "plugins" / "marketplace.json").read_text(encoding="utf-8"))

    assert manifest["name"] == "nepa-mcp"
    assert manifest["mcpServers"] == "./.mcp.json"
    assert manifest["skills"] == "./skills/"
    assert set(mcp_config["mcpServers"]) == EXPECTED_SERVERS
    for server_name, server_config in mcp_config["mcpServers"].items():
        assert server_config == {
            "command": "nepa-mcp",
            "args": ["server", server_name],
            "env": {"PYTHONUNBUFFERED": "1"},
        }
    assert marketplace["plugins"][0]["source"] == {
        "source": "local",
        "path": "./plugins/nepa-mcp",
    }

    plugin_text = "\n".join(path.read_text(encoding="utf-8") for path in plugin_root.rglob("*") if path.is_file())
    assert "/Users/" not in plugin_text
    assert "AWS" not in plugin_text


def test_repository_client_examples_register_the_same_independent_servers() -> None:
    claude = json.loads((ROOT / ".mcp.json").read_text(encoding="utf-8"))
    vscode = json.loads((ROOT / ".vscode" / "mcp.json").read_text(encoding="utf-8"))
    codex = (ROOT / "config.template.toml").read_text(encoding="utf-8")

    assert set(claude["mcpServers"]) == EXPECTED_SERVERS
    assert set(vscode["servers"]) == EXPECTED_SERVERS
    for server_name in EXPECTED_SERVERS:
        assert claude["mcpServers"][server_name]["args"] == ["server", server_name]
        assert vscode["servers"][server_name]["args"] == ["server", server_name]
        assert f"[mcp_servers.{server_name}]" in codex
        assert f'args = ["server", "{server_name}"]' in codex


def test_open_source_runtime_has_no_aws_secret_manager_dependency() -> None:
    project = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    credential_servers = (ROOT / "census" / "server.py").read_text(encoding="utf-8") + (
        ROOT / "epa_aqs" / "server.py"
    ).read_text(encoding="utf-8")
    credential_requirements = (ROOT / "census" / "requirements.txt").read_text(encoding="utf-8") + (
        ROOT / "epa_aqs" / "requirements.txt"
    ).read_text(encoding="utf-8")
    assert "boto3" not in project
    assert "boto3" not in credential_requirements
    assert "secretsmanager" not in credential_servers.lower()
    assert "get_secret_value" not in credential_servers


async def _aggregate_tool_names() -> set[str]:
    async with Client(build_aggregate_server()) as client:
        return {tool.name for tool in await client.list_tools()}


def test_aggregate_server_discovers_all_tools() -> None:
    tool_names = asyncio.run(_aggregate_tool_names())
    assert len(tool_names) == 43
    assert {
        "summarize_roi_buffer",
        "get_ipac_resources_in_roi",
        "cfr_resolve_citation",
        "get_nrhp_properties_in_roi",
    } <= tool_names
