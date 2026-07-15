"""Generate the human-facing MCP tool catalog from live server contracts."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_PATH = ROOT / "docs" / "mcp-tool-catalog.md"
MAX_PURPOSE_LENGTH = 140

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastmcp import Client  # noqa: E402

from nepa_mcp.loader import load_server_module  # noqa: E402
from nepa_mcp.registry import SERVER_SPECS  # noqa: E402


@dataclass(frozen=True)
class CatalogRow:
    server: str
    tool: str
    purpose: str


def _tool_purpose(server_name: str, tool_name: str, description: str | None) -> str:
    """Return the concise first paragraph of a tool's MCP description."""
    if not description or not description.strip():
        raise ValueError(f"{server_name}.{tool_name} has no MCP description")

    first_paragraph = description.strip().split("\n\n", maxsplit=1)[0]
    purpose = " ".join(first_paragraph.split())
    if len(purpose) > MAX_PURPOSE_LENGTH:
        raise ValueError(
            f"{server_name}.{tool_name} catalog purpose is {len(purpose)} characters; "
            f"keep the first description paragraph at or below {MAX_PURPOSE_LENGTH}"
        )
    return purpose


async def discover_catalog_rows() -> list[CatalogRow]:
    """Discover every registered server's tools through the MCP contract."""
    rows: list[CatalogRow] = []
    for server in SERVER_SPECS:
        module = load_server_module(server.name)
        async with Client(module.mcp) as client:
            tools = sorted(await client.list_tools(), key=lambda tool: tool.name)
        rows.extend(
            CatalogRow(
                server=server.name,
                tool=tool.name,
                purpose=_tool_purpose(server.name, tool.name, tool.description),
            )
            for tool in tools
        )
    return rows


def _escape_markdown_cell(value: str) -> str:
    return value.replace("|", "\\|")


async def render_tool_catalog() -> str:
    """Render the complete catalog as deterministic Markdown."""
    rows = await discover_catalog_rows()
    lines = [
        "# MCP Tool Catalog",
        "",
        (
            f"NEPA MCP provides {len(SERVER_SPECS)} independent servers "
            f"with {len(rows)} tools. Use this catalog to choose the smallest set "
            "of servers needed for a workflow."
        ),
        "",
        (
            "This file is generated from the server registry and each server's live "
            "MCP `tools/list` contract. Do not edit it manually. Regenerate it with "
            "`uv run python scripts/generate_tool_catalog.py`; add `--check` to verify "
            "it without writing."
        ),
        "",
        "| Server | Tool | Purpose |",
        "|---|---|---|",
    ]
    lines.extend(
        "| `{server}` | `{tool}` | {purpose} |".format(
            server=row.server,
            tool=row.tool,
            purpose=_escape_markdown_cell(row.purpose),
        )
        for row in rows
    )
    lines.append("")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit nonzero instead of writing when the committed catalog is stale",
    )
    args = parser.parse_args(argv)

    logging.getLogger("mcp.server.lowlevel.server").setLevel(logging.WARNING)
    rendered = asyncio.run(render_tool_catalog())
    if args.check:
        current = OUTPUT_PATH.read_text(encoding="utf-8") if OUTPUT_PATH.is_file() else None
        if current != rendered:
            print(
                f"{OUTPUT_PATH.relative_to(ROOT)} is stale; regenerate it with "
                "`uv run python scripts/generate_tool_catalog.py`",
                file=sys.stderr,
            )
            return 1
        print(f"{OUTPUT_PATH.relative_to(ROOT)} is current")
        return 0

    OUTPUT_PATH.write_text(rendered, encoding="utf-8")
    print(f"Wrote {OUTPUT_PATH.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
