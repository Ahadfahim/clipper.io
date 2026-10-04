"""What each button, modal, command and #control message does, independent of discord.py so it
can be tested against the real core API. Only members with the reviewer role may act."""

from __future__ import annotations

from dataclasses import dataclass, field

from clipper_bot.config import BotConfig
from clipper_bot.core_client import CoreClient, CoreError

REASONS: dict[str, str] = {
    "bad_hook": "Bad hook",
    "boring": "Boring",
    "broken": "Broken",
    "off_brief": "Off-brief",
    "other": "Other",
}
PLATFORMS = ("youtube", "tiktok", "instagram", "x")
SWITCHES: dict[str, str] = {
    "vyro": "marketplace",
    "whop": "marketplace",
    "youtube": "social",
    "tiktok": "social",
    "instagram": "social",
    "x": "social",
}
NO_ROLE = "Only members with the reviewer role can do this."


@dataclass(frozen=True)
class Actor:
    id: int
    name: str
    role_ids: frozenset[int] = field(default_factory=frozenset)
    role_names: frozenset[str] = field(default_factory=frozenset)


def is_reviewer(actor: Actor, cfg: BotConfig) -> bool:
    if cfg.reviewer_role_id is not None:
        return cfg.reviewer_role_id in actor.role_ids
    return cfg.reviewer_role_name.lower() in {n.lower() for n in actor.role_names}


class Actions:
    def __init__(self, core: CoreClient, cfg: BotConfig) -> None:
        self.core = core
        self.cfg = cfg

    def allowed(self, actor: Actor) -> bool:
        return is_reviewer(actor, self.cfg)

    # ------------------------------------------------------------ campaigns
    async def take(self, actor: Actor, campaign_id: int) -> str:
        if not self.allowed(actor):
            return NO_ROLE
        try:
            await self.core.take(campaign_id)
        except CoreError as e:
            return f"Couldn't take it: {e.detail}"
        return "Taken. The Campaign agent starts on it."

    async def skip(self, actor: Actor, campaign_id: int) -> str:
        if not self.allowed(actor):
            return NO_ROLE
        try:
            await self.core.skip(campaign_id)
        except CoreError as e:
            return f"Couldn't skip it: {e.detail}"
        return "Skipped."

    # ------------------------------------------------------------ clips
    async def _review_clip(self, clip_id: int) -> dict[str, object] | None:
        clip = await self.core.clip(clip_id)
        review = clip.get("review")
        return review if isinstance(review, dict) else None

    async def approve(self, actor: Actor, clip_id: int) -> str:
        if not self.allowed(actor):
            return NO_ROLE
        try:
            review = await self._review_clip(clip_id)
            platforms = list(review.get("platforms") or []) if review else None  # type: ignore[call-overload]
            await self.core.decide(clip_id, "approved", reviewer=actor.name, platforms=platforms)
        except CoreError as e:
            return f"Couldn't approve: {e.detail}"
        return f"Approved clip {clip_id}."

    async def reject(self, actor: Actor, clip_id: int, reason: str) -> str:
        if not self.allowed(actor):
            return NO_ROLE
        if reason not in REASONS:
            return "Pick one of the reasons."
        try:
            await self.core.decide(clip_id, "rejected", reviewer=actor.name, reason=reason)
        except CoreError as e:
            return f"Couldn't reject: {e.detail}"
        return f"Rejected clip {clip_id}: {REASONS[reason].lower()}."

    async def set_platforms(self, actor: Actor, clip_id: int, platforms: list[str]) -> str:
        if not self.allowed(actor):
            return NO_ROLE
        chosen = [p for p in platforms if p in PLATFORMS]
        try:
            review = await self._review_clip(clip_id)
            decision = str(review.get("decision", "pending")) if review else "pending"
            reason = review.get("reason") if review else None
            await self.core.decide(
                clip_id,
                decision,
                reviewer=actor.name,
                platforms=chosen,
                reason=reason if isinstance(reason, str) else None,
            )
        except CoreError as e:
            return f"Couldn't change platforms: {e.detail}"
        return f"Clip {clip_id} will post to: {', '.join(chosen) or 'nowhere'}."

    async def captions(self, actor: Actor, clip_id: int, changes: dict[str, str]) -> str:
        if not self.allowed(actor):
            return NO_ROLE
        try:
            for platform, text in changes.items():
                if platform in PLATFORMS:
                    await self.core.caption(clip_id, platform, text)
        except CoreError as e:
            return f"Couldn't save the caption: {e.detail}"
        return "Caption saved." if changes else "Nothing changed."

    async def recut(self, actor: Actor, clip_id: int, start: str, end: str, layout: str, note: str) -> str:
        if not self.allowed(actor):
            return NO_ROLE
        try:
            start_delta = float(start or 0)
            end_delta = float(end or 0)
        except ValueError:
            return "Start and end must be numbers of seconds, like -1.5 or 2."
        if abs(start_delta) > 5 or abs(end_delta) > 5:
            return "Re-cuts can move each end by up to 5 seconds."
        lay = layout.strip().lower() or None
        if lay in ("keep", "same", "-"):
            lay = None
        if lay is not None and lay not in ("crop", "split", "fit"):
            return "Layout must be crop, split, fit or empty."
        try:
            await self.core.recut(clip_id, start_delta, end_delta, lay, note.strip() or None)
        except CoreError as e:
            return f"Couldn't send the re-cut: {e.detail}"
        return "Re-cut sent to the agent. The new preview replaces this one when it's rendered."

    # ------------------------------------------------------------ batches
    async def ship(self, actor: Actor, batch_id: int) -> str:
        if not self.allowed(actor):
            return NO_ROLE
        try:
            out = await self.core.ship(batch_id, reviewer=actor.name)
        except CoreError as e:
            return f"Couldn't ship: {e.detail}"
        return f"Shipped: {len(out.get('approved', []))} approved clips go to the Campaign agent."

    async def approve_all(self, actor: Actor, batch_id: int) -> str:
        if not self.allowed(actor):
            return NO_ROLE
        try:
            ids = await self.core.approve_all(batch_id, self.cfg.approve_all_threshold, reviewer=actor.name)
        except CoreError as e:
            return f"Couldn't approve: {e.detail}"
        return f"Approved {len(ids)} clips scored {self.cfg.approve_all_threshold}+."

    async def reject_rest(self, actor: Actor, batch_id: int) -> str:
        if not self.allowed(actor):
            return NO_ROLE
        try:
            ids = await self.core.reject_rest(batch_id, reason="other", reviewer=actor.name)
        except CoreError as e:
            return f"Couldn't reject: {e.detail}"
        return f"Rejected the {len(ids)} clips still pending."

    # ------------------------------------------------------------ questions, switches, chat
    async def answer(self, actor: Actor, question_id: int, option_index: int) -> str:
        if not self.allowed(actor):
            return NO_ROLE
        try:
            q = await self.core.question(question_id)
            if q is None or q.get("status") != "open":
                return "That question was already answered."
            options = list(q.get("options") or [])
            if not 0 <= option_index < len(options):
                return "Unknown option."
            await self.core.answer(question_id, str(options[option_index]), by=actor.name)
        except CoreError as e:
            return f"Couldn't answer: {e.detail}"
        return f"Answered: {options[option_index]}. The agent picks it up from here."

    async def toggle(self, actor: Actor, name: str, on: bool) -> str:
        if not self.allowed(actor):
            return NO_ROLE
        level = SWITCHES.get(name.lower())
        if level is None:
            return f"Unknown switch {name!r}. Use one of: {', '.join(SWITCHES)}."
        try:
            res = await self.core.switch(level, name.lower(), on)
        except CoreError as e:
            return f"Couldn't switch {name}: {e.detail}"
        if not res.get("ok", True):
            return f"{name} needs setup first: {res.get('needs_setup') or 'open Settings in the app'}."
        effects = res.get("effects") or {}
        extra = ""
        if not on and effects:
            parts = [f"{k.replace('_', ' ')}: {v}" for k, v in effects.items() if v]
            extra = f" ({'; '.join(parts)})" if parts else ""
        return f"{name} is {'on' if on else 'off'}{extra}."

    async def chat(self, actor: Actor, text: str, thread_id: int | None) -> str | None:
        """#control → Director. Returns an error to show, or None when sent."""
        if not self.allowed(actor):
            return NO_ROLE
        if not text.strip():
            return None
        try:
            await self.core.chat(text.strip(), reply_to=str(thread_id) if thread_id else None)
        except CoreError as e:
            return f"Couldn't reach the Director: {e.detail}"
        return None
