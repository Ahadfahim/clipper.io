"""Tool catalog and the per-agent access matrix (PLAN §16.3), max 25 tools per agent."""

from __future__ import annotations

import pytest

from clipper.agents.access import (
    ACCESS,
    BUILTIN_TOOLS,
    CATALOG,
    MAX_TOOLS_PER_AGENT,
    SUBAGENTS,
    all_tools,
    fq,
    servers_for,
    split_fq,
)
from clipper.tools.base import REGISTRY, ensure_loaded, json_schema

PUBLISH_OR_SUBMIT = {
    fq("publish", "schedule_post"),
    fq("marketplace", "submit_post_url"),
    fq("edit", "render_final"),
    fq("marketplace", "join_campaign"),
}
WEB = {"WebSearch", "WebFetch"}


def test_registry_matches_catalog() -> None:
    ensure_loaded()
    assert set(REGISTRY) == set(CATALOG)
    for server, tools in CATALOG.items():
        assert set(REGISTRY[server]) == set(tools), server
        for name, spec in REGISTRY[server].items():
            assert spec.read_only == tools[name]
            assert spec.description and len(spec.description) < 400
            schema = json_schema(spec.args)
            assert schema["type"] == "object"


@pytest.mark.parametrize("role", sorted(ACCESS))
def test_at_most_25_tools_and_all_exist(role: str) -> None:
    tools = ACCESS[role]
    assert len(tools) <= MAX_TOOLS_PER_AGENT, f"{role} sees {len(tools)} tools"
    assert len(tools) == len(set(tools)), f"{role} has duplicates"
    known = all_tools()
    assert all(t in known for t in tools)


def _servers(role: str) -> set[str]:
    return {p[0] for t in ACCESS[role] if (p := split_fq(t))}


def _has(role: str, server: str, *names: str) -> bool:
    return all(fq(server, n) in ACCESS[role] for n in names)


# One row per cell of the PLAN §16.3 matrix that our encoding must honor.
MATRIX = [
    # Scout: state rw, market read, media download only, review cards, supervisor, alert, memory rw, trends; no publish/browser/insights/web
    ("scout", lambda: _has("scout", "state", "update_campaign", "get_campaign")),
    ("scout", lambda: _has("scout", "marketplace", "list_campaigns", "get_campaign_page") and not _has("scout", "marketplace", "submit_post_url")),
    ("scout", lambda: [t for t in ACCESS["scout"] if t.startswith("mcp__media__")] == [fq("media", "download")]),
    ("scout", lambda: _has("scout", "review", "post_campaign_card") and not _has("scout", "review", "post_batch")),
    ("scout", lambda: not ({"publish", "browser", "insights", "edit"} & _servers("scout"))),
    ("scout", lambda: _has("scout", "memory", "recall", "remember") and _has("scout", "notify", "alert") and not _has("scout", "notify", "ask_user")),
    # brief-reader: memory read only; nothing that changes anything
    ("brief-reader", lambda: set(ACCESS["brief-reader"]) <= {fq("memory", "recall"), fq("memory", "list_lessons")}),
    ("brief-reader", lambda: all(all_tools()[t] for t in ACCESS["brief-reader"])),
    # research: web + memory write; no publish/submit
    ("research", lambda: set(ACCESS["research"]) >= WEB and _has("research", "memory", "remember")),
    ("research", lambda: not (PUBLISH_OR_SUBMIT & set(ACCESS["research"]))),
    # Campaign: schedule approved clips, its campaign's market tools, media, review, agenda, render_final, subagents
    ("campaign", lambda: _has("campaign", "publish", "schedule_post") and _has("campaign", "marketplace", "submit_post_url", "join_campaign")),
    ("campaign", lambda: _has("campaign", "edit", "render_final") and _has("campaign", "agenda", "set_plan", "check", "ack_note")),
    ("campaign", lambda: _has("campaign", "review", "post_batch", "get_decisions") and "Agent" in ACCESS["campaign"]),
    ("campaign", lambda: not (WEB & set(ACCESS["campaign"])) and "insights" not in _servers("campaign")),
    # editor: state read, media read + frames, memory read, saturation
    ("editor", lambda: _has("editor", "media", "get_transcript", "get_signals", "get_comments", "frames") and _has("editor", "trends", "saturation")),
    ("editor", lambda: all(all_tools()[t] for t in ACCESS["editor"])),
    # cutter: every edit op except render_final, plus agenda
    ("cutter", lambda: {t for t in CATALOG["edit"] if t != "render_final"} == {split_fq(t)[1] for t in ACCESS["cutter"] if t.startswith("mcp__edit__")}),  # type: ignore[index]
    ("cutter", lambda: not _has("cutter", "edit", "render_final") and _has("cutter", "agenda", "set_plan", "check", "get_notes", "ack_note")),
    # qa-checker: frames, contact sheet, OCR; read-only
    ("qa-checker", lambda: _has("qa-checker", "media", "frames", "contact_sheet", "ocr_frames") and all(all_tools()[t] for t in ACCESS["qa-checker"])),
    # copywriter: hashtags, times; read-only
    ("copywriter", lambda: _has("copywriter", "trends", "hashtags", "best_post_times") and all(all_tools()[t] for t in ACCESS["copywriter"])),
    # Analyst: weights, earnings/status, metrics/health, reports, insights, web via research
    ("analyst", lambda: _has("analyst", "insights", *CATALOG["insights"]) and _has("analyst", "marketplace", "get_earnings", "get_submission_status")),
    ("analyst", lambda: _has("analyst", "publish", "get_post_metrics", "account_health") and not _has("analyst", "publish", "schedule_post")),
    ("analyst", lambda: _has("analyst", "state", "set_tuning") and _has("analyst", "notify", "send_report") and "research" in SUBAGENTS["analyst"]),
    # Director: read + controls, cancel, insights, agenda + read-only edit; nothing that publishes or submits
    ("director", lambda: _has("director", "publish", "cancel_post") and not _has("director", "publish", "schedule_post")),
    ("director", lambda: _has("director", "clipper", "set_switch", "set_paused") and _has("director", "edit", "get_edl") and _has("director", "agenda", "get_notes")),
    ("director", lambda: not (PUBLISH_OR_SUBMIT & set(ACCESS["director"])) and "insights" in _servers("director")),
    # browser-fixer: browser + memory + alert only
    ("browser-fixer", lambda: _servers("browser-fixer") == {"browser", "memory", "notify"}),
]  # fmt: skip


@pytest.mark.parametrize(("role", "check"), MATRIX, ids=[f"{r}-{i}" for i, (r, _) in enumerate(MATRIX)])
def test_matrix(role: str, check: object) -> None:
    assert callable(check) and check()


def test_web_only_without_publish_or_submit() -> None:
    for role, tools in ACCESS.items():
        if WEB & set(tools):
            assert not (PUBLISH_OR_SUBMIT & set(tools)), role


def test_subagents_and_servers() -> None:
    assert set(SUBAGENTS["campaign"]) == {
        "brief-reader",
        "editor",
        "cutter",
        "qa-checker",
        "copywriter",
        "browser-fixer",
    }
    assert "edit" in servers_for("campaign") and "browser" in servers_for("campaign")
    assert BUILTIN_TOOLS["Agent"] is False


def test_sdk_servers_build_for_every_server(core: object) -> None:
    from clipper.tools.base import ToolContext, sdk_server

    for server in CATALOG:
        cfg = sdk_server(server, ToolContext(core, role="developer"))  # type: ignore[arg-type]
        assert cfg["type"] == "sdk" and cfg["name"] == server
