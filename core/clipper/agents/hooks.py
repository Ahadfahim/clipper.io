"""PreToolUse / PostToolUse guardrails (PLAN §4, §15.2, §16.3).

The rules are pure functions of a ``ToolCall`` and a read-only ``GuardContext``. They never read
notes, briefs or free-text arguments, so nothing an agent or a note says can change the outcome
(``tests/agents/test_guards.py`` has the "a note can't override a rule" cases).

The same ``Guard`` runs in two places:
1. as the Agent SDK ``PreToolUse`` hook (``make_pre_tool_use_hook``) for every agent session, and
2. inside the tool wrapper (``clipper.tools.base``) so a call that reaches a tool any other way
   (stdio server, API) is still checked.

Every denial returns a clear ``[rule] reason`` and is logged to ``agent_event`` as ``blocked``.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

from clipper.agents.access import allowed, fq, is_read_only, split_fq
from clipper.clock import ensure_utc
from clipper.rules.caps import AccountCaps, check_daily_cap, check_min_gap
from clipper.rules.spec import ClipSpec
from clipper.rules.urls import domain_allowed, source_whitelisted
from clipper.services.control import ControlState
from clipper.settings import Settings

log = logging.getLogger(__name__)

# ---------------------------------------------------------------- inputs


@dataclass(frozen=True)
class ToolCall:
    tool: str  # fully qualified, e.g. mcp__publish__schedule_post
    args: Mapping[str, Any]
    role: str  # main role or subagent name
    session_id: int | None = None
    campaign_id: int | None = None  # the campaign this session is bound to (Campaign agent)
    turns: int = 0
    max_turns: int | None = None


@dataclass(frozen=True)
class Verdict:
    allowed: bool
    rule: str = ""
    reason: str = ""
    dry_run: bool = False

    @property
    def message(self) -> str:
        return f"[{self.rule}] {self.reason}" if self.rule else self.reason


ALLOW = Verdict(True)


def deny(rule: str, reason: str) -> Verdict:
    return Verdict(False, rule, reason)


@dataclass(frozen=True)
class AccountFacts:
    id: int
    platform: str
    enabled: bool
    status: str
    chrome_profile: str
    caps: AccountCaps


@dataclass(frozen=True)
class ReviewFacts:
    clip_id: int
    decision: str
    via: str | None
    reviewer: str | None
    platforms: tuple[str, ...] = ()
    score: float | None = None


@dataclass(frozen=True)
class CampaignFacts:
    id: int
    marketplace: str
    status: str
    platforms: tuple[str, ...] = ()
    spec: ClipSpec = field(default_factory=ClipSpec)
    listed_sources: tuple[str, ...] = ()


@dataclass(frozen=True)
class ClipFacts:
    id: int
    campaign_id: int | None
    locked_by: str | None = None
    score: float | None = None


@dataclass(frozen=True)
class PostFacts:
    id: int
    clip_id: int
    account_id: int
    platform: str
    status: str
    url: str | None
    campaign_id: int | None
    dry_run: bool = False


class GuardContext(Protocol):
    """Read-only facts the rules need. ``DbGuardContext`` reads them from SQLite."""

    @property
    def settings(self) -> Settings: ...
    def now(self) -> datetime: ...
    def control(self) -> ControlState: ...
    def marketplace_enabled(self, market: str) -> bool: ...
    def platform_enabled(self, platform: str) -> bool: ...
    def account(self, account_id: int) -> AccountFacts | None: ...
    def campaign(self, campaign_id: int) -> CampaignFacts | None: ...
    def clip(self, clip_id: int) -> ClipFacts | None: ...
    def review(self, clip_id: int) -> ReviewFacts | None: ...
    def post(self, post_id: int) -> PostFacts | None: ...
    def submitted_campaigns(self, post_id: int) -> list[int]: ...
    def counted_post_times(self, account_id: int, around: datetime) -> list[datetime]: ...
    def browser_url(self, profile: str | None) -> str | None: ...


# ---------------------------------------------------------------- tool groups

SCHEDULE_POST = fq("publish", "schedule_post")
RENDER_FINAL = fq("edit", "render_final")
SUBMIT_POST_URL = fq("marketplace", "submit_post_url")
JOIN_CAMPAIGN = fq("marketplace", "join_campaign")
DOWNLOAD = fq("media", "download")
NAVIGATE = fq("browser", "navigate")

# Tools that create new clips/posts for a campaign: denied when its marketplace is switched off.
NEW_WORK_TOOLS = frozenset(
    {
        DOWNLOAD,
        fq("media", "analyze"),
        fq("media", "render"),
        fq("review", "post_batch"),
        SCHEDULE_POST,
        RENDER_FINAL,
    }
)
# Tools that only pretend in dry-run mode (the tool code simulates them and logs what it would do).
DRY_RUN_TOOLS = frozenset(
    {
        SCHEDULE_POST,
        SUBMIT_POST_URL,
        JOIN_CAMPAIGN,
        fq("browser", "click"),
        fq("browser", "type"),
        fq("browser", "attach_file"),
    }
)
HUMAN_REVIEW_VIA = frozenset({"discord", "dashboard"})


def _int_arg(args: Mapping[str, Any], key: str) -> int | None:
    value = args.get(key)
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value)
    return None


def _str_arg(args: Mapping[str, Any], key: str) -> str | None:
    value = args.get(key)
    return value if isinstance(value, str) and value.strip() else None


def resolve_campaign_id(call: ToolCall, ctx: GuardContext) -> int | None:
    """The campaign a call targets: explicit ``campaign_id``, else via ``clip_id`` or ``post_id``."""
    cid = _int_arg(call.args, "campaign_id")
    if cid is not None:
        return cid
    clip_id = _int_arg(call.args, "clip_id")
    if clip_id is not None:
        clip = ctx.clip(clip_id)
        if clip is not None:
            return clip.campaign_id
    post_id = _int_arg(call.args, "post_id")
    if post_id is not None:
        post = ctx.post(post_id)
        if post is not None:
            return post.campaign_id
    return None


def parse_when(value: Any, now: datetime) -> datetime | None:
    if value is None or value == "now":
        return now
    if isinstance(value, str):
        try:
            return ensure_utc(datetime.fromisoformat(value.replace("Z", "+00:00")))
        except ValueError:
            return None
    return None


# ---------------------------------------------------------------- rules

Rule = Callable[[ToolCall, GuardContext], Verdict | None]


def rule_kill_switch(call: ToolCall, ctx: GuardContext) -> Verdict | None:
    if ctx.control().kill_switch:
        return deny("kill_switch", "the kill switch is on: every agent tool is stopped until it is reset")
    return None


def rule_paused(call: ToolCall, ctx: GuardContext) -> Verdict | None:
    if ctx.control().paused and not is_read_only(call.tool):
        return deny("paused", "Clipper is paused (Pause all): only read-only tools run until it is resumed")
    return None


def rule_max_turns(call: ToolCall, ctx: GuardContext) -> Verdict | None:
    if call.max_turns is not None and call.turns >= call.max_turns:
        return deny(
            "max_turns", f"this session used {call.turns}/{call.max_turns} turns; end the turn and summarize"
        )
    return None


def rule_access(call: ToolCall, ctx: GuardContext) -> Verdict | None:
    if not allowed(call.role, call.tool):
        return deny("access", f"{call.role} is not allowed to use {call.tool} (PLAN §16.3)")
    return None


def rule_campaign_scope(call: ToolCall, ctx: GuardContext) -> Verdict | None:
    if call.campaign_id is None:
        return None
    target = resolve_campaign_id(call, ctx)
    if target is not None and target != call.campaign_id:
        return deny(
            "campaign_scope",
            f"this session owns campaign {call.campaign_id}; it may not act on campaign {target}",
        )
    return None


def rule_marketplace_switch(call: ToolCall, ctx: GuardContext) -> Verdict | None:
    parts = split_fq(call.tool)
    is_market_tool = parts is not None and parts[0] == "marketplace"
    if not is_market_tool and call.tool not in NEW_WORK_TOOLS:
        return None
    market = _str_arg(call.args, "market")
    campaign: CampaignFacts | None = None
    cid = resolve_campaign_id(call, ctx)
    if cid is not None:
        campaign = ctx.campaign(cid)
        if campaign is not None:
            market = campaign.marketplace
    if market is None:
        return None
    if ctx.marketplace_enabled(market):
        return None
    if call.tool == SUBMIT_POST_URL and campaign is not None and campaign.status == "ending":
        return None  # "Finish them": posts that are already live still get submitted (PLAN §15.2)
    if is_market_tool:
        return deny("marketplace_switch", f"{market} is switched off; its tools are denied")
    return deny("marketplace_switch", f"{market} is switched off; its campaigns get no new clips or posts")


def rule_account_switch(call: ToolCall, ctx: GuardContext) -> Verdict | None:
    if call.tool != SCHEDULE_POST:
        return None
    account_id = _int_arg(call.args, "account_id")
    if account_id is None:
        return deny("account_switch", "schedule_post needs an account_id")
    account = ctx.account(account_id)
    if account is None:
        return deny("account_switch", f"account {account_id} does not exist")
    if not account.enabled:
        return deny("account_switch", f"account {account_id} is switched off")
    if account.status != "active":
        return deny(
            "account_switch", f"account {account_id} is paused ({account.status}); the user must resume it"
        )
    return None


def rule_social_switch(call: ToolCall, ctx: GuardContext) -> Verdict | None:
    if call.tool != SCHEDULE_POST:
        return None
    account_id = _int_arg(call.args, "account_id")
    account = ctx.account(account_id) if account_id is not None else None
    if account is None:
        return None  # rule_account_switch reports it
    if not ctx.platform_enabled(account.platform):
        return deny("social_switch", f"{account.platform} is switched off; nothing new is scheduled there")
    cid = resolve_campaign_id(call, ctx)
    campaign = ctx.campaign(cid) if cid is not None else None
    if campaign is not None:
        if campaign.platforms and account.platform not in campaign.platforms:
            return deny("social_switch", f"campaign {campaign.id} does not allow {account.platform}")
        if campaign.spec.platforms and account.platform not in campaign.spec.platforms:
            return deny(
                "social_switch",
                f"campaign {campaign.id}'s spec limits it to {', '.join(campaign.spec.platforms)}",
            )
    return None


def human_approved(review: ReviewFacts | None, clip: ClipFacts | None, ctx: GuardContext) -> tuple[bool, str]:
    if review is None or review.decision != "approved":
        return False, "has no approved review"
    if review.via in HUMAN_REVIEW_VIA and review.reviewer:
        return True, ""
    if review.via == "auto":
        tier = ctx.control().auto_approve_tier
        score = review.score if review.score is not None else (clip.score if clip else None)
        if tier is not None and score is not None and score >= tier:
            return True, ""
        return False, "was auto-approved but the auto-approve tier is off or the score is below it"
    return False, "was not approved by a human (Discord or dashboard)"


def rule_publish_approval(call: ToolCall, ctx: GuardContext) -> Verdict | None:
    if call.tool not in (SCHEDULE_POST, RENDER_FINAL):
        return None
    clip_id = _int_arg(call.args, "clip_id")
    if clip_id is None:
        return deny("approval", f"{call.tool} needs a clip_id")
    clip = ctx.clip(clip_id)
    if clip is None:
        return deny("approval", f"clip {clip_id} does not exist")
    review = ctx.review(clip_id)
    ok, why = human_approved(review, clip, ctx)
    if not ok:
        return deny("approval", f"clip {clip_id} {why}; publishing requires a human approved review")
    if call.tool == SCHEDULE_POST and review is not None and review.platforms:
        account_id = _int_arg(call.args, "account_id")
        account = ctx.account(account_id) if account_id is not None else None
        if account is not None and account.platform not in review.platforms:
            return deny(
                "approval",
                f"clip {clip_id} was approved for {', '.join(review.platforms)}, not {account.platform}",
            )
    return None


def _schedule_target(call: ToolCall, ctx: GuardContext) -> tuple[AccountFacts, datetime] | Verdict | None:
    if call.tool != SCHEDULE_POST:
        return None
    account_id = _int_arg(call.args, "account_id")
    account = ctx.account(account_id) if account_id is not None else None
    if account is None:
        return None
    when = parse_when(call.args.get("scheduled_at"), ctx.now())
    if when is None:
        return deny("posting_caps", "scheduled_at must be an ISO-8601 time or 'now'")
    return account, when


def rule_posting_caps(call: ToolCall, ctx: GuardContext) -> Verdict | None:
    target = _schedule_target(call, ctx)
    if target is None or isinstance(target, Verdict):
        return target
    account, when = target
    times = ctx.counted_post_times(account.id, when)
    decision = check_daily_cap(
        account.caps, times, when, ctx.settings.posting, ctx.settings.triggers.timezone
    )
    return None if decision.ok else deny("posting_caps", decision.reason)


def rule_min_gap(call: ToolCall, ctx: GuardContext) -> Verdict | None:
    target = _schedule_target(call, ctx)
    if target is None or isinstance(target, Verdict):
        return None
    account, when = target
    decision = check_min_gap(
        account.caps, ctx.counted_post_times(account.id, when), when, ctx.settings.posting
    )
    return None if decision.ok else deny("min_gap", decision.reason)


def rule_source_whitelist(call: ToolCall, ctx: GuardContext) -> Verdict | None:
    if call.tool != DOWNLOAD:
        return None
    url = _str_arg(call.args, "url")
    cid = _int_arg(call.args, "campaign_id")
    if url is None or cid is None:
        return deny("source_whitelist", "download needs a url and the campaign_id it is for")
    campaign = ctx.campaign(cid)
    if campaign is None:
        return deny("source_whitelist", f"campaign {cid} does not exist")
    whitelist = [*campaign.spec.source_whitelist, *campaign.listed_sources]
    if not source_whitelisted(url, whitelist):
        return deny("source_whitelist", f"{url} is not on campaign {cid}'s source whitelist")
    return None


def browser_domains(ctx: GuardContext) -> list[str]:
    domains: list[str] = []
    for switch, names in ctx.settings.browser.domain_allowlist.items():
        enabled = (
            ctx.marketplace_enabled(switch) if switch in ("vyro", "whop") else ctx.platform_enabled(switch)
        )
        if enabled:
            domains += names
    return domains


def rule_browser_allowlist(call: ToolCall, ctx: GuardContext) -> Verdict | None:
    parts = split_fq(call.tool)
    if parts is None or parts[0] != "browser":
        return None
    url = (
        _str_arg(call.args, "url")
        if call.tool == NAVIGATE
        else ctx.browser_url(_str_arg(call.args, "profile"))
    )
    if url is None:
        return deny(
            "domain_allowlist", "no page is open in that Chrome profile; navigate to an allowed site first"
        )
    if not domain_allowed(url, browser_domains(ctx)):
        return deny(
            "domain_allowlist", f"{url} is not on the domain allowlist for the sites that are switched on"
        )
    return None


def rule_submit_own_live_post(call: ToolCall, ctx: GuardContext) -> Verdict | None:
    if call.tool != SUBMIT_POST_URL:
        return None
    post_id = _int_arg(call.args, "post_id")
    if post_id is None:
        return deny("submit_own_post", "submit_post_url needs the post_id of our own post")
    post = ctx.post(post_id)
    if post is None:
        return deny("submit_own_post", f"post {post_id} is not one of ours")
    live = post.status == "live" or (post.status == "simulated" and ctx.control().dry_run)
    if not live:
        return deny("submit_own_post", f"post {post_id} is {post.status}, not live")
    cid = _int_arg(call.args, "campaign_id") or post.campaign_id
    if cid is None or (post.campaign_id is not None and cid != post.campaign_id):
        return deny("submit_own_post", f"post {post_id} was made for campaign {post.campaign_id}, not {cid}")
    url = _str_arg(call.args, "url")
    if url is not None and post.url is not None and url.strip() != post.url:
        return deny("submit_own_post", f"{url} is not the URL of post {post_id}")
    already = ctx.submitted_campaigns(post_id)
    if cid in already:
        return deny("submit_own_post", f"post {post_id} was already submitted to campaign {cid}")
    if already:
        this = ctx.campaign(cid)
        others = [ctx.campaign(c) for c in already]
        if (
            this is None
            or not this.spec.allow_cross_submit
            or not all(o and o.spec.allow_cross_submit for o in others)
        ):
            return deny(
                "submit_own_post",
                f"post {post_id} is already submitted to campaign {already[0]}; both rules must allow reuse",
            )
    return None


def rule_edit_lock(call: ToolCall, ctx: GuardContext) -> Verdict | None:
    parts = split_fq(call.tool)
    if parts is None or parts[0] != "edit" or is_read_only(call.tool):
        return None
    clip_id = _int_arg(call.args, "clip_id")
    if clip_id is None:
        return deny("edit_lock", f"{call.tool} needs a clip_id")
    clip = ctx.clip(clip_id)
    if clip is not None and clip.locked_by == "user":
        return deny("edit_lock", f"the user took over clip {clip_id}; wait until they hand it back")
    return None


RULES: Sequence[tuple[str, Rule]] = (
    ("kill_switch", rule_kill_switch),
    ("paused", rule_paused),
    ("max_turns", rule_max_turns),
    ("access", rule_access),
    ("campaign_scope", rule_campaign_scope),
    ("marketplace_switch", rule_marketplace_switch),
    ("account_switch", rule_account_switch),
    ("social_switch", rule_social_switch),
    ("approval", rule_publish_approval),
    ("posting_caps", rule_posting_caps),
    ("min_gap", rule_min_gap),
    ("source_whitelist", rule_source_whitelist),
    ("domain_allowlist", rule_browser_allowlist),
    ("submit_own_post", rule_submit_own_live_post),
    ("edit_lock", rule_edit_lock),
)


BlockListener = Callable[[ToolCall, Verdict], None]


class Guard:
    def __init__(self, ctx: GuardContext, on_block: BlockListener | None = None) -> None:
        self.ctx = ctx
        self.on_block = on_block

    def evaluate(self, call: ToolCall, skip: frozenset[str] = frozenset()) -> Verdict:
        """Pure decision (no logging). ``skip`` names rules already enforced elsewhere for this call path."""
        for name, rule in RULES:
            if name in skip:
                continue
            verdict = rule(call, self.ctx)
            if verdict is not None and not verdict.allowed:
                return verdict
        if call.tool in DRY_RUN_TOOLS and self.ctx.control().dry_run:
            return Verdict(
                True, "dry_run", "dry-run mode: this call is simulated and only logged", dry_run=True
            )
        return ALLOW

    def check(self, call: ToolCall, skip: frozenset[str] = frozenset()) -> Verdict:
        verdict = self.evaluate(call, skip)
        if not verdict.allowed and self.on_block is not None:
            try:
                self.on_block(call, verdict)
            except Exception:
                log.exception("failed to log a blocked call")
        return verdict


# ---------------------------------------------------------------- Agent SDK adapters


@dataclass
class SessionBinding:
    """What the hook knows about the session it guards."""

    role: str
    session_id: int | None
    campaign_id: int | None
    max_turns: int | None
    turns: Callable[[], int] = lambda: 0


HookFn = Callable[[Any, str | None, Any], Awaitable[dict[str, Any]]]


def make_pre_tool_use_hook(guard: Guard, binding: SessionBinding) -> HookFn:
    """``HookMatcher(hooks=[make_pre_tool_use_hook(...)])`` for ``ClaudeAgentOptions.hooks['PreToolUse']``."""

    async def pre_tool_use(input_data: Any, tool_use_id: str | None, context: Any) -> dict[str, Any]:
        if input_data.get("hook_event_name") != "PreToolUse":
            return {}
        role = input_data.get("agent_type") or binding.role
        call = ToolCall(
            tool=str(input_data.get("tool_name", "")),
            args=dict(input_data.get("tool_input") or {}),
            role=str(role),
            session_id=binding.session_id,
            campaign_id=binding.campaign_id,
            turns=binding.turns(),
            max_turns=binding.max_turns if role == binding.role else None,
        )
        verdict = guard.check(call)
        if not verdict.allowed:
            return {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": verdict.message,
                }
            }
        if verdict.dry_run:
            return {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "additionalContext": "DRY RUN: this call is simulated; nothing is posted or submitted.",
                }
            }
        return {}

    return pre_tool_use


ToolResultRecorder = Callable[[str, dict[str, Any], Any, str | None], None]


def make_post_tool_use_hook(record: ToolResultRecorder) -> HookFn:
    """Logs every tool result for the audit trail and the live console."""

    async def post_tool_use(input_data: Any, tool_use_id: str | None, context: Any) -> dict[str, Any]:
        if input_data.get("hook_event_name") != "PostToolUse":
            return {}
        try:
            record(
                str(input_data.get("tool_name", "")),
                dict(input_data.get("tool_input") or {}),
                input_data.get("tool_response"),
                input_data.get("agent_type"),
            )
        except Exception:
            log.exception("failed to record a tool result")
        return {}

    return post_tool_use
