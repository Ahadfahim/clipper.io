"""Tool catalog and per-agent access (PLAN §16.3), least privilege, at most 25 tools per agent.

Names are fully qualified the way Claude Code sees them: ``mcp__<server>__<tool>``. Built-in tools
(``Agent`` for subagents, ``WebSearch``/``WebFetch`` for research) are listed by their plain names.

The column meanings of PLAN §16.3 are realized per agent context. Where a role's column cannot fit in
25 tools, the work moves to one of its subagents (see HANDOFF §6): the Campaign agent's media reads go
to *editor*/*qa-checker*, EDL edits to *cutter*, and browser fallback to *browser-fixer*.
"""

from __future__ import annotations

from typing import Final

MAX_TOOLS_PER_AGENT: Final = 25

# server -> {tool: read_only}
CATALOG: Final[dict[str, dict[str, bool]]] = {
    "state": {
        "get_campaign": True,
        "list_campaigns": True,
        "update_campaign": False,
        "save_spec": False,
        "save_moments": False,
        "get_clip": True,
        "log_note": False,
        "get_learning_examples": True,
        "set_tuning": False,
    },
    "marketplace": {
        "list_campaigns": False,  # reads the site, upserts campaign rows
        "get_campaign_page": True,
        "join_campaign": False,
        "submit_post_url": False,
        "get_submission_status": True,
        "get_earnings": True,
        "snapshot_page": True,
    },
    "media": {
        "download": False,
        "analyze": False,
        "get_transcript": True,
        "get_signals": True,
        "get_comments": True,
        "frames": True,
        "contact_sheet": True,
        "ocr_frames": True,
        "render": False,
        "job_status": True,
    },
    "review": {
        "post_batch": False,
        "post_campaign_card": False,
        "get_batch_status": True,
        "get_decisions": True,
        "replace_preview": False,
    },
    "publish": {
        "list_accounts": True,
        "schedule_post": False,
        "cancel_post": False,
        "get_post_metrics": True,
        "account_health": True,
    },
    "browser": {
        "snapshot": True,
        "click": False,
        "type": False,
        "attach_file": False,
        "navigate": False,
    },
    "supervisor": {
        "wake_me": False,
        "list_wakeups": True,
        "cancel_wakeup": False,
        "get_usage": True,
        "report_status": False,
    },
    "notify": {"alert": False, "ask_user": False, "send_report": False},
    "memory": {"recall": True, "remember": False, "forget": False, "list_lessons": True},
    "trends": {"niche_trends": True, "hashtags": True, "saturation": True, "best_post_times": True},
    "insights": {
        "query": True,
        "performance_by": True,
        "approval_rate_by": True,
        "top_clips": True,
        "campaign_report": True,
    },
    "edit": {
        "get_edl": True,
        "trim": False,
        "split": False,
        "delete_range": False,
        "remove_silences": False,
        "remove_fillers": False,
        "set_layout": False,
        "set_camera_keyframes": False,
        "set_caption_style": False,
        "edit_caption_words": False,
        "emphasize": False,
        "set_hook": False,
        "add_overlay": False,
        "set_audio": False,
        "make_variant": False,
        "preview": False,
        "render_final": False,
        "undo": False,
    },
    "agenda": {"set_plan": False, "check": False, "get_notes": True, "ack_note": False},
    "clipper": {
        "status": True,
        "review_queue": True,
        "list_campaigns": True,
        "campaign_report": True,
        "recent_activity": True,
        "get_usage": True,
        "set_switch": False,
        "set_paused": False,
        "set_dry_run": False,
    },
}

BUILTIN_TOOLS: Final[dict[str, bool]] = {"Agent": False, "WebSearch": True, "WebFetch": True}


def fq(server: str, tool: str) -> str:
    return f"mcp__{server}__{tool}"


def split_fq(name: str) -> tuple[str, str] | None:
    if not name.startswith("mcp__"):
        return None
    rest = name[len("mcp__") :]
    server, sep, tool = rest.partition("__")
    return (server, tool) if sep else None


def all_tools() -> dict[str, bool]:
    """Every fully-qualified tool name -> read_only."""
    out = {fq(s, t): ro for s, tools in CATALOG.items() for t, ro in tools.items()}
    out.update(BUILTIN_TOOLS)
    return out


def is_read_only(name: str) -> bool:
    return all_tools().get(name, False)


def _t(server: str, *tools: str) -> list[str]:
    for t in tools:
        if t not in CATALOG[server]:
            raise KeyError(f"{server}.{t} is not in the catalog")
    return [fq(server, t) for t in tools]


_ALL_EDIT_BUT_FINAL = [t for t in CATALOG["edit"] if t != "render_final"]

ACCESS: Final[dict[str, list[str]]] = {
    # ------------------------------------------------------------- main agents
    "scout": [
        *_t("state", "get_campaign", "list_campaigns", "update_campaign", "log_note"),
        *_t("marketplace", "list_campaigns", "get_campaign_page"),
        *_t("media", "download"),  # pre-fetch sources (PLAN §14)
        *_t("review", "post_campaign_card"),
        *_t("supervisor", "wake_me", "list_wakeups", "cancel_wakeup", "get_usage", "report_status"),
        *_t("notify", "alert"),
        *_t("memory", "recall", "remember", "forget", "list_lessons"),
        *_t("trends", "niche_trends", "hashtags", "saturation", "best_post_times"),
    ],
    "campaign": [
        *_t("state", "get_campaign", "update_campaign", "save_spec", "save_moments", "get_clip", "log_note"),
        *_t("marketplace", "get_campaign_page", "join_campaign", "submit_post_url"),  # its campaign only
        *_t("media", "download", "render"),
        *_t("review", "post_batch", "get_decisions"),
        *_t("publish", "list_accounts", "schedule_post"),  # approved clips only (hook)
        *_t("edit", "render_final"),  # approved clips only (hook)
        *_t("agenda", "set_plan", "check", "ack_note"),
        *_t("supervisor", "wake_me"),
        *_t("notify", "alert", "ask_user"),
        *_t("memory", "recall", "remember"),
        "Agent",
    ],
    "analyst": [
        *_t("state", "get_campaign", "list_campaigns", "update_campaign", "set_tuning", "log_note"),
        *_t("marketplace", "get_earnings", "get_submission_status"),
        *_t("publish", "get_post_metrics", "account_health"),
        *_t("supervisor", "get_usage", "report_status"),
        *_t("notify", "send_report", "alert"),
        *_t("memory", "recall", "remember", "forget", "list_lessons"),
        *_t("trends", "niche_trends", "best_post_times"),
        *_t("insights", "query", "performance_by", "approval_rate_by", "top_clips", "campaign_report"),
        "Agent",  # web research goes through the *research* subagent
    ],
    "director": [
        *_t("state", "get_campaign", "list_campaigns", "get_clip", "update_campaign"),
        *_t("marketplace", "get_submission_status", "get_earnings"),
        *_t("media", "job_status"),
        *_t("review", "get_batch_status", "get_decisions"),
        *_t("publish", "list_accounts", "cancel_post"),
        *_t("supervisor", "get_usage", "list_wakeups"),
        *_t("notify", "alert"),
        *_t("memory", "recall", "remember", "forget"),
        *_t("trends", "niche_trends"),
        *_t("insights", "query", "campaign_report", "performance_by"),
        *_t("agenda", "get_notes"),
        *_t("edit", "get_edl"),
        *_t("clipper", "set_switch", "set_paused"),
    ],
    # ------------------------------------------------------------- subagents
    "brief-reader": [*_t("memory", "recall", "list_lessons")],  # nothing that changes anything
    "research": ["WebSearch", "WebFetch", *_t("memory", "remember")],
    "editor": [
        *_t("state", "get_campaign", "get_clip", "get_learning_examples"),
        *_t("media", "get_transcript", "get_signals", "get_comments", "frames"),
        *_t("memory", "recall"),
        *_t("trends", "saturation"),
    ],
    "cutter": [
        *_t("edit", *_ALL_EDIT_BUT_FINAL),
        *_t("agenda", "set_plan", "check", "get_notes", "ack_note"),
        *_t("media", "get_transcript", "frames"),
        *_t("memory", "recall"),
    ],
    "qa-checker": [
        *_t("state", "get_clip", "get_campaign"),
        *_t("media", "frames", "contact_sheet", "ocr_frames"),
        *_t("edit", "get_edl"),
        *_t("memory", "recall"),
    ],
    "copywriter": [
        *_t("state", "get_clip", "get_campaign"),
        *_t("memory", "recall", "list_lessons"),
        *_t("trends", "hashtags", "best_post_times"),
    ],
    "browser-fixer": [
        *_t("browser", "snapshot", "click", "type", "attach_file", "navigate"),
        *_t("memory", "recall", "remember"),
        *_t("notify", "alert"),
    ],
}

# Which subagents each main agent may launch through the Agent tool.
SUBAGENTS: Final[dict[str, list[str]]] = {
    "campaign": ["brief-reader", "editor", "cutter", "qa-checker", "copywriter", "browser-fixer"],
    "analyst": ["research"],
    "scout": [],
    "director": [],
}

MAIN_ROLES: Final = ("scout", "campaign", "analyst", "director")


def tools_for(role: str) -> list[str]:
    return list(ACCESS[role])


def servers_for(role: str) -> set[str]:
    """MCP servers a role's session needs (its own tools plus its subagents')."""
    names = set(ACCESS[role])
    for sub in SUBAGENTS.get(role, []):
        names.update(ACCESS[sub])
    return {parts[0] for n in names if (parts := split_fq(n)) is not None}


def allowed(role: str, tool: str) -> bool:
    return tool in ACCESS.get(role, [])
