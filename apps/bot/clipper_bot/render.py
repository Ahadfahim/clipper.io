"""Embeds and component rows for every bot message. Pure functions of core data, so the relay
can re-render a message whenever the state changes (decisions from the dashboard included)."""

from __future__ import annotations

from typing import Any

import discord

from clipper_bot import ids
from clipper_bot.actions import PLATFORMS, REASONS

GRAY = discord.Colour(0x8A8A8A)
GREEN = discord.Colour(0x0F7B0F)
RED = discord.Colour(0xC42B1C)
BLUE = discord.Colour(0x005FB8)
VIOLET = discord.Colour(0x6B4FBB)
PLATFORM_LABEL = {"youtube": "YouTube", "tiktok": "TikTok", "instagram": "Instagram", "x": "X"}
MARKET_LABEL = {"vyro": "Vyro", "whop": "Whop"}


def _dur(s: float | None) -> str:
    if s is None:
        return "—"
    s = round(s)
    return f"{s // 60}:{s % 60:02d}" if s < 3600 else f"{s // 3600}:{(s % 3600) // 60:02d}:{s % 60:02d}"


def _money(v: float | None) -> str:
    return "—" if v is None else (f"${v / 1000:.1f}k" if v >= 1000 else f"${v:,.2f}")


def _cut(text: str, n: int = 1024) -> str:
    return text if len(text) <= n else text[: n - 1] + "…"


# ---------------------------------------------------------------- campaign cards (#campaigns)


def campaign_card(
    detail: dict[str, Any], reasoning: str | None = None
) -> tuple[discord.Embed, discord.ui.View]:
    c = detail["campaign"]
    status = str(c.get("status", "suggested"))
    e = discord.Embed(
        title=_cut(f"{MARKET_LABEL.get(c['marketplace'], c['marketplace'])} · {c['title']}", 256),
        url=detail.get("url") or None,
        colour=GREEN if status == "active" else GRAY if status in ("skipped", "ended") else BLUE,
        description=_cut(reasoning or detail.get("score_reason") or "", 4000) or None,
    )
    e.add_field(name="Score", value=str(round(c["score"])) if c.get("score") is not None else "—")
    e.add_field(name="CPM", value=f"${c['cpm']:.2f}")
    e.add_field(name="Budget left", value=_money(c.get("budget_left")))
    e.add_field(name="Deadline", value=(c.get("deadline") or "—")[:10])
    e.add_field(
        name="Accounts", value=", ".join(c.get("matching_accounts") or []) or "none match", inline=False
    )
    if status not in ("suggested", "needs_user"):
        e.set_footer(text=f"Status: {status.replace('_', ' ')}")
    v = discord.ui.View(timeout=None)
    open_ = status in ("suggested", "needs_user")
    v.add_item(
        discord.ui.Button(
            label="Take",
            emoji="✅",
            style=discord.ButtonStyle.success,
            custom_id=ids.make(*ids.CAMPAIGN_TAKE, c["id"]),
            disabled=not open_,
        )
    )
    v.add_item(
        discord.ui.Button(
            label="Skip",
            emoji="⏭",
            style=discord.ButtonStyle.secondary,
            custom_id=ids.make(*ids.CAMPAIGN_SKIP, c["id"]),
            disabled=not open_,
        )
    )
    if detail.get("url"):
        v.add_item(discord.ui.Button(label="Details", style=discord.ButtonStyle.link, url=detail["url"]))
    return e, v


# ---------------------------------------------------------------- clips (#clip-review forum)

DECISION_LINE = {"approved": "✅ Approved", "rejected": "❌ Rejected", "pending": "⏳ Pending"}


def clip_message(rc: dict[str, Any], shipped: bool = False) -> tuple[discord.Embed, discord.ui.View]:
    """``rc`` is a ReviewClip from GET /api/review/batches/{id}."""
    c = rc["clip"]
    decision = str(rc.get("decision", "pending"))
    colour = GREEN if decision == "approved" else RED if decision == "rejected" else GRAY
    e = discord.Embed(title=_cut(f"#{c['id']} · {c.get('hook') or 'Clip'}", 256), colour=colour)
    e.add_field(name="Score", value=str(round(c["score"])))
    e.add_field(name="Length", value=_dur(c.get("duration")))
    rng = rc.get("source_range") or [0, 0]
    e.add_field(name="Source", value=f"{_dur(rng[0])}–{_dur(rng[1])}")
    if rc.get("reason"):
        e.add_field(name="Why", value=_cut(str(rc["reason"])), inline=False)
    for p in PLATFORMS:
        if p in (rc.get("platforms_allowed") or []):
            cap = (rc.get("captions") or {}).get(p)
            on = p in (rc.get("platforms") or [])
            e.add_field(
                name=f"{'☑' if on else '☐'} {PLATFORM_LABEL[p]}", value=_cut(cap or "—"), inline=False
            )
    status = DECISION_LINE.get(decision, decision)
    if decision != "pending":
        who = rc.get("reviewer") or "someone"
        via = rc.get("via")
        status += f" by {who}" + (f" via {'the app' if via == 'dashboard' else via}" if via else "")
        if rc.get("decision_reason"):
            status += f" · {REASONS.get(rc['decision_reason'], rc['decision_reason'])}"
    if c.get("status") == "recut":
        status += " · 🔁 re-cutting"
    if rc.get("qa_ok") is False:
        status += " · QA failed"
    e.set_footer(text=f"{status} · v{c.get('version', 1)}")
    v = discord.ui.View(timeout=None)
    cid = c["id"]
    v.add_item(
        discord.ui.Button(
            label="Approve",
            emoji="✅",
            style=discord.ButtonStyle.success,
            custom_id=ids.make(*ids.CLIP_APPROVE, cid),
            disabled=shipped,
            row=0,
        )
    )
    v.add_item(
        discord.ui.Button(
            label="Reject",
            emoji="❌",
            style=discord.ButtonStyle.danger,
            custom_id=ids.make(*ids.CLIP_REJECT, cid),
            disabled=shipped,
            row=0,
        )
    )
    v.add_item(
        discord.ui.Button(
            label="Edit caption",
            emoji="✏️",
            style=discord.ButtonStyle.secondary,
            custom_id=ids.make(*ids.CLIP_CAPTION, cid),
            disabled=shipped,
            row=0,
        )
    )
    v.add_item(
        discord.ui.Button(
            label="Re-cut",
            emoji="🔁",
            style=discord.ButtonStyle.secondary,
            custom_id=ids.make(*ids.CLIP_RECUT, cid),
            disabled=shipped,
            row=0,
        )
    )
    allowed = [p for p in PLATFORMS if p in (rc.get("platforms_allowed") or [])]
    if allowed:
        chosen = set(rc.get("platforms") or [])
        v.add_item(
            discord.ui.Select(
                custom_id=ids.make(*ids.CLIP_PLATFORMS, cid),
                placeholder="Post to…",
                min_values=0,
                max_values=len(allowed),
                options=[
                    discord.SelectOption(label=PLATFORM_LABEL[p], value=p, default=p in chosen)
                    for p in allowed
                ],
                disabled=shipped,
                row=1,
            )
        )
    return e, v


def reason_picker(clip_id: int) -> discord.ui.View:
    v = discord.ui.View(timeout=300)
    v.add_item(
        discord.ui.Select(
            custom_id=ids.make(*ids.CLIP_REASON, clip_id),
            placeholder="Why reject it?",
            options=[discord.SelectOption(label=label, value=key) for key, label in REASONS.items()],
        )
    )
    return v


def batch_summary(detail: dict[str, Any], threshold: int) -> tuple[discord.Embed, discord.ui.View]:
    b = detail["batch"]
    shipped = b.get("status") == "shipped"
    reviewed = b["approved"] + b["rejected"]
    e = discord.Embed(
        title=_cut(f"{b['campaign_title']} · {b.get('source_title') or 'batch ' + str(b['id'])}", 256),
        description=f"Reviewed {reviewed}/{b['total']} · ✅{b['approved']} ❌{b['rejected']}"
        + (" · 🚀 shipped" if shipped else ""),
        colour=GREEN if shipped else BLUE,
    )
    if b.get("timeout_at") and not shipped:
        e.set_footer(text=f"Times out {b['timeout_at'][:16].replace('T', ' ')} UTC")
    v = discord.ui.View(timeout=None)
    v.add_item(
        discord.ui.Button(
            label=f"Ship approved ({b['approved']})",
            emoji="🚀",
            style=discord.ButtonStyle.primary,
            custom_id=ids.make(*ids.BATCH_SHIP, b["id"]),
            disabled=shipped or b["approved"] == 0,
        )
    )
    v.add_item(
        discord.ui.Button(
            label=f"Approve all ≥{threshold}",
            emoji="✅",
            style=discord.ButtonStyle.success,
            custom_id=ids.make(*ids.BATCH_APPROVE_ALL, b["id"]),
            disabled=shipped,
        )
    )
    v.add_item(
        discord.ui.Button(
            label="Reject rest",
            emoji="⏭",
            style=discord.ButtonStyle.secondary,
            custom_id=ids.make(*ids.BATCH_REJECT_REST, b["id"]),
            disabled=shipped or b["pending"] == 0,
        )
    )
    return e, v


def batch_tag(detail: dict[str, Any]) -> str:
    b = detail["batch"]
    if b.get("status") == "shipped":
        return "shipped"
    return "in review" if b["approved"] + b["rejected"] > 0 else "pending"


# ---------------------------------------------------------------- questions, alerts, posts


def question_message(q: dict[str, Any]) -> tuple[discord.Embed, discord.ui.View]:
    answered = q.get("status") != "open"
    e = discord.Embed(
        title="The agent has a question",
        description=_cut(str(q["text"]), 4000),
        colour=GRAY if answered else VIOLET,
    )
    if answered:
        e.set_footer(text=f"Answered: {q.get('answer')}")
    v = discord.ui.View(timeout=None)
    for i, opt in enumerate(list(q.get("options") or [])[:5]):
        v.add_item(
            discord.ui.Button(
                label=_cut(str(opt), 80),
                style=discord.ButtonStyle.secondary,
                custom_id=ids.make(*ids.QUESTION_ANSWER, q["id"], i),
                disabled=answered,
            )
        )
    return e, v


def alert_message(level: str, text: str, source: str) -> discord.Embed:
    colour = RED if level == "error" else discord.Colour(0x9D5D00) if level == "warning" else GRAY
    return discord.Embed(
        title=f"{'⛔' if level == 'error' else '⚠️' if level == 'warning' else 'ℹ️'} {source}",
        description=_cut(text, 4000),
        colour=colour,
    )


def published_message(p: dict[str, Any]) -> discord.Embed:
    e = discord.Embed(
        title=f"Posted clip #{p['clip_id']} on {PLATFORM_LABEL.get(p['platform'], p['platform'])}",
        url=p.get("url") or None,
        colour=GREEN,
        description=p.get("url") or None,
    )
    if p.get("dry_run"):
        e.set_footer(text="Dry run: simulated, nothing was posted")
    return e
