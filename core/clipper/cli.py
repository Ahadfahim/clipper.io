"""`clipper` command line.

clipper doctor [--json] [--fast]     environment and health checks
clipper migrate                       create/upgrade the SQLite database (Alembic)
clipper seed [--fixtures]             seed switches/platforms; --fixtures adds demo data
clipper api [--fixtures]              run the FastAPI server (+ supervisor unless --fixtures)
clipper mcp <server>                  serve one MCP tool server over stdio (Claude Desktop/Code)
clipper eval                          re-run the editor on the golden set (PLAN §14)
clipper openapi <path>                write the OpenAPI schema (for the TS client)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _cmd_doctor(args: argparse.Namespace) -> int:
    from clipper.doctor import format_results, run_checks
    from clipper.settings import get_settings

    results = run_checks(get_settings(), include_slow=not args.fast)
    if args.json:
        print(json.dumps([r.as_dict() for r in results], indent=2))
    else:
        print(format_results(results))
    return 1 if any(r.status == "fail" for r in results) else 0


def _cmd_migrate(_: argparse.Namespace) -> int:
    from clipper.db.migrate import upgrade_to_head
    from clipper.settings import get_settings

    db = get_settings().paths.database
    db.parent.mkdir(parents=True, exist_ok=True)
    upgrade_to_head(db)
    print(f"migrated {db}")
    return 0


def _cmd_seed(args: argparse.Namespace) -> int:
    from clipper.db.engine import Database
    from clipper.db.seed import seed_base, seed_fixtures
    from clipper.settings import get_settings

    settings = get_settings()
    db = Database(settings.paths.database)
    try:
        seed_base(db, settings)
        if args.fixtures:
            seed_fixtures(db, settings)
    finally:
        db.close()
    print("seeded" + (" (with fixtures)" if args.fixtures else ""))
    return 0


def _cmd_api(args: argparse.Namespace) -> int:
    from clipper.api.server import serve

    serve(fixture_mode=args.fixtures)
    return 0


def _cmd_mcp(args: argparse.Namespace) -> int:
    from clipper.tools.stdio import serve_stdio

    serve_stdio(args.server)
    return 0


def _cmd_eval(_: argparse.Namespace) -> int:
    from clipper.evaluation import run_eval

    return run_eval()


def _cmd_openapi(args: argparse.Namespace) -> int:
    from clipper.api.app import create_app

    app = create_app(fixture_mode=True, start_background=False)
    Path(args.path).write_text(json.dumps(app.openapi(), indent=2) + "\n", encoding="utf-8")
    print(f"wrote {args.path}")
    return 0


def main(argv: list[str] | None = None) -> None:
    from clipper.agents.env import scrub_process_env

    scrub_process_env()
    parser = argparse.ArgumentParser(prog="clipper")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("doctor")
    p.add_argument("--json", action="store_true")
    p.add_argument("--fast", action="store_true", help="skip the Claude login and GPU checks")
    p.set_defaults(fn=_cmd_doctor)
    sub.add_parser("migrate").set_defaults(fn=_cmd_migrate)
    p = sub.add_parser("seed")
    p.add_argument("--fixtures", action="store_true")
    p.set_defaults(fn=_cmd_seed)
    p = sub.add_parser("api")
    p.add_argument("--fixtures", action="store_true")
    p.set_defaults(fn=_cmd_api)
    p = sub.add_parser("mcp")
    p.add_argument("server")
    p.set_defaults(fn=_cmd_mcp)
    sub.add_parser("eval").set_defaults(fn=_cmd_eval)
    p = sub.add_parser("openapi")
    p.add_argument("path")
    p.set_defaults(fn=_cmd_openapi)
    args = parser.parse_args(argv)
    sys.exit(args.fn(args))


if __name__ == "__main__":
    main()
