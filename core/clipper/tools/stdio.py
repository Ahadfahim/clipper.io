"""stdio entry points: ``clipper mcp <server>``.

- ``clipper mcp clipper``: the umbrella server for Claude Desktop / Claude Code (read-only + controls).
- ``clipper mcp <state|media|...>``: one server for calling tools by hand while developing (PLAN §16.4).

Each runs its own Core against the same SQLite file; writes use BEGIN IMMEDIATE, so they stay atomic
next to the main clipper-core process. All guard rules still apply (the developer role only skips the
per-agent access matrix).
"""

from __future__ import annotations

import os
import sys

import anyio

from clipper.agents.access import CATALOG
from clipper.tools.base import ToolContext, sdk_server


def serve_stdio(server: str, *, fakes: bool | None = None) -> None:
    if server not in CATALOG:
        print(f"unknown server {server!r}; choose one of: {', '.join(CATALOG)}", file=sys.stderr)
        raise SystemExit(2)
    from clipper.core import Core
    from clipper.settings import get_settings

    use_fakes = fakes if fakes is not None else os.environ.get("CLIPPER_FAKES") == "1"
    core = Core.create(get_settings(), fakes=use_fakes)
    role = "umbrella" if server == "clipper" else "developer"
    ctx = ToolContext(core, role=role, skip_rules=frozenset({"access", "max_turns"}))
    config = sdk_server(server, ctx)
    instance = config["instance"]

    async def main() -> None:
        from mcp.server.stdio import stdio_server

        async with stdio_server() as (read, write):
            await instance.run(read, write, instance.create_initialization_options())

    try:
        anyio.run(main)
    finally:
        core.close()
