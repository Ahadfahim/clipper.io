"""Typed settings loaded from TOML.

Lookup order: the path in ``CLIPPER_SETTINGS``, then ``config/settings.toml`` next to the repo root,
then built-in defaults. ``config/settings.example.toml`` documents every key and is kept in sync with
this module by ``tests/test_settings.py``.

Secrets (Discord token, extension pairing token, Hugging Face token) never live here: they are stored
in Windows Credential Manager through ``clipper.secrets``.
"""

from __future__ import annotations

import os
import tomllib
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Effort = Literal["low", "medium", "high", "xhigh", "max"]
Role = Literal["scout", "campaign", "analyst", "director"]
SubagentName = Literal[
    "brief-reader", "research", "editor", "cutter", "qa-checker", "copywriter", "browser-fixer"
]

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SETTINGS_PATH = REPO_ROOT / "config" / "settings.toml"


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _default_data_dir() -> Path:
    # The target machine is Windows; elsewhere (CI, cloud sessions) use a home-relative folder so a
    # literal "D:\..." directory is never created in the working directory.
    return Path(r"D:\Clipper.io\data") if os.name == "nt" else Path.home() / ".clipper" / "data"


def _default_sources_dir() -> Path | None:
    # Source videos are big (1-3 GB per hour of 1080p) and D: is small on the target machine, so on
    # Windows they default to C:. Elsewhere they live under the data folder.
    return Path(r"C:\ClipperData\sources") if os.name == "nt" else None


class PathsSettings(_Model):
    data_dir: Path = Field(default_factory=_default_data_dir)
    sources_dir: Path | None = Field(default_factory=_default_sources_dir)
    work_dir: Path | None = None
    clips_dir: Path | None = None
    previews_dir: Path | None = None
    db_path: Path | None = None
    logs_dir: Path | None = None
    screenshots_dir: Path | None = None
    backups_dir: Path | None = None
    models_dir: Path = Path(r"C:\ClipperData\models")
    ffmpeg_bin: Path | None = Path(r"C:\ffmpeg\bin")
    yt_dlp: str = "yt-dlp"
    gpu_python: Path = Path(r"C:\ClipperData\envs\gpu\Scripts\python.exe")
    chrome_exe: Path = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
    chrome_profiles_dir: Path = Path(r"C:\ClipperData\chrome")

    def sub(self, name: str) -> Path:
        explicit: Path | None = getattr(self, f"{name}_dir", None)
        return explicit if explicit is not None else self.data_dir / name

    @property
    def database(self) -> Path:
        return self.db_path if self.db_path is not None else self.data_dir / "clipper.sqlite"

    def ffmpeg(self, tool: str = "ffmpeg") -> str:
        if self.ffmpeg_bin is not None:
            exe = self.ffmpeg_bin / (f"{tool}.exe" if os.name == "nt" else tool)
            if exe.exists():
                return str(exe)
        return tool


class ApiSettings(_Model):
    host: str = "127.0.0.1"
    port: int = 8765
    fixture_mode: bool = False

    @field_validator("host")
    @classmethod
    def _loopback_only(cls, v: str) -> str:
        if v not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("the API binds to loopback only (127.0.0.1)")
        return v


class RoleSettings(_Model):
    effort: Effort = "high"
    max_turns: int = 60


class SubagentSettings(_Model):
    effort: Effort = "medium"
    max_turns: int = 30


def _default_roles() -> dict[str, RoleSettings]:
    return {
        "scout": RoleSettings(effort="low", max_turns=40),
        "campaign": RoleSettings(effort="high", max_turns=80),
        "analyst": RoleSettings(effort="medium", max_turns=60),
        "director": RoleSettings(effort="high", max_turns=40),
    }


def _default_subagents() -> dict[str, SubagentSettings]:
    return {
        "brief-reader": SubagentSettings(effort="high", max_turns=10),
        "research": SubagentSettings(effort="medium", max_turns=20),
        "editor": SubagentSettings(effort="high", max_turns=40),
        "cutter": SubagentSettings(effort="high", max_turns=60),
        "qa-checker": SubagentSettings(effort="low", max_turns=20),
        "copywriter": SubagentSettings(effort="medium", max_turns=15),
        "browser-fixer": SubagentSettings(effort="medium", max_turns=30),
    }


class AgentSettings(_Model):
    model: str = "claude-opus-5-5"
    # How many agent sessions run at once. 0 = unlimited: the pool grows with the work (one session
    # per active campaign plus Scout/Analyst/Director), still paused by the plan's rate limit and the
    # free-memory floor below. Default 2 suits a Claude Pro plan.
    slots: int = Field(default=2, ge=0)
    reserve_p0_slot: bool = True
    # Don't start background agent sessions when free RAM drops below this (each session is a Claude
    # Code process). Your own requests (P0) still start. 0 disables the check.
    min_free_ram_gb: float = Field(default=2.0, ge=0)
    roles: dict[str, RoleSettings] = Field(default_factory=_default_roles)
    subagents: dict[str, SubagentSettings] = Field(default_factory=_default_subagents)
    prompts_dir: Path | None = None
    cli_path: Path | None = None


class TriggerSettings(_Model):
    scout_every_min: int = 15
    analyst_daily_at: str = "09:00"
    watchdog_stale_min: int = 180
    wakeup_poll_s: int = 30
    timezone: str = "America/New_York"


class UsageSettings(_Model):
    """Claude plan usage pacing. No money is tracked: only usage-window utilization."""

    daily_agent_run_cap: int = Field(default=300, ge=0)  # 0 = no daily cap
    # utilization (0..1) -> max slots for a fixed pool. The highest threshold reached wins. An
    # unlimited pool (agents.slots = 0) isn't shrunk; near the limit only P0/P1 work runs.
    shrink_steps: dict[str, int] = Field(default_factory=lambda: {"0.6": 3, "0.8": 2})
    # at or above this, only P0/P1 work runs
    p01_only_at: float = 0.9
    # roles slowed first under high usage (P3 work)
    slow_first: list[str] = Field(default_factory=lambda: ["scout", "analyst"])
    auto_resume_after_reset: bool = True


class WarmupSettings(_Model):
    week1_daily_cap: int = 1
    week2_daily_cap: int = 2


class PostingSettings(_Model):
    default_daily_cap: int = 3
    min_gap_min: int = 120
    warmup: WarmupSettings = WarmupSettings()
    step_delay_ms: tuple[int, int] = (600, 2200)


class SwitchSettings(_Model):
    """Initial switch values written to the DB on first run. The DB is the source of truth after that."""

    marketplaces: dict[str, bool] = Field(default_factory=lambda: {"vyro": True, "whop": True})
    socials: dict[str, bool] = Field(
        default_factory=lambda: {"youtube": True, "tiktok": True, "instagram": True, "x": False}
    )


class VyroSettings(_Model):
    min_cpm: float = 1.0


class WhopSettings(_Model):
    min_cpm: float = 0.5
    include_ugc: bool = False
    auto_join_free: bool = True
    use_bounty_api: bool = False


class MarketplaceSettings(_Model):
    vyro: VyroSettings = VyroSettings()
    whop: WhopSettings = WhopSettings()


class ScoutSettings(_Model):
    mode: Literal["suggest", "auto"] = "suggest"
    auto_take_min_score: int = 85
    min_score_to_post_card: int = 55
    prefetch_sources: bool = True


class ReviewSettings(_Model):
    timeout_hours: float = 0.0  # 0 = no timeout
    timeout_action: Literal["ship_approved", "reject_rest"] = "ship_approved"
    approve_all_threshold: int = 80
    auto_approve_offer_min_decisions: int = 100
    auto_approve_offer_min_rate: float = 0.95
    auto_approve_tier: int | None = None  # opt-in; None = off


class MediaSettings(_Model):
    encoder: Literal["nvenc", "x264"] = "nvenc"
    nvenc_preset: str = "p5"
    final_bitrate: str = "14M"
    final_width: int = 1080
    final_height: int = 1920
    fps: int = 30
    proxy_height: int = 640
    loudness_lufs: float = -14.0
    true_peak_db: float = -1.5
    discord_preview_mb: float = 9.5
    whisper_model: str = "large-v3"
    whisper_language: str | None = None
    max_concurrent_encodes: int = 3
    max_concurrent_transcribes: int = 1
    max_concurrent_downloads: int = 2
    default_caption_style: str = "bold-pop"
    silence_threshold_db: float = -35.0


class DiscordChannels(_Model):
    control: int | None = None
    campaigns: int | None = None
    clip_review: int | None = None  # forum channel
    published: int | None = None
    alerts: int | None = None


class DiscordSettings(_Model):
    enabled: bool = True
    guild_id: int | None = None
    reviewer_role_id: int | None = None
    reviewer_role_name: str = "Clipper"
    channels: DiscordChannels = DiscordChannels()
    core_url: str = "http://127.0.0.1:8765"


class BrowserSettings(_Model):
    ws_host: str = "127.0.0.1"
    ws_port: int = 8766
    action_timeout_s: float = 90.0
    domain_allowlist: dict[str, list[str]] = Field(
        default_factory=lambda: {
            "vyro": ["vyro.com"],
            "whop": ["whop.com"],
            "youtube": ["studio.youtube.com", "youtube.com"],
            "tiktok": ["tiktok.com"],
            "instagram": ["instagram.com"],
            "x": ["x.com"],
        }
    )


class RetentionSettings(_Model):
    sources_days_after_end: int = 14
    failure_screenshots_days: int = 30
    logs_days: int = 14
    backups_keep: int = 14
    nightly_backup_at: str = "03:30"


class NotifySettings(_Model):
    ntfy_url: str | None = None
    ntfy_topic: str | None = None


class UiSettings(_Model):
    theme: Literal["system", "light", "dark"] = "system"
    density: Literal["compact", "comfortable"] = "compact"
    accent: str | None = None  # None = follow Windows accent


class Settings(_Model):
    paths: PathsSettings = PathsSettings()
    api: ApiSettings = ApiSettings()
    agents: AgentSettings = AgentSettings()
    triggers: TriggerSettings = TriggerSettings()
    usage: UsageSettings = UsageSettings()
    posting: PostingSettings = PostingSettings()
    switches: SwitchSettings = SwitchSettings()
    marketplaces: MarketplaceSettings = MarketplaceSettings()
    scout: ScoutSettings = ScoutSettings()
    review: ReviewSettings = ReviewSettings()
    media: MediaSettings = MediaSettings()
    discord: DiscordSettings = DiscordSettings()
    browser: BrowserSettings = BrowserSettings()
    retention: RetentionSettings = RetentionSettings()
    notify: NotifySettings = NotifySettings()
    ui: UiSettings = UiSettings()
    dry_run_default: bool = True

    def with_data_dir(self, data_dir: Path) -> Settings:
        """Move the data folder. A sources folder still on its platform default moves with it (tests
        and fixture exports must never write into the real C:\\ClipperData\\sources); one the user chose
        stays where it is."""
        update: dict[str, Any] = {"data_dir": data_dir}
        if self.paths.sources_dir == _default_sources_dir():
            update["sources_dir"] = None
        return self.model_copy(update={"paths": self.paths.model_copy(update=update)})


def load_settings(path: Path | None = None, overrides: dict[str, Any] | None = None) -> Settings:
    env_path = os.environ.get("CLIPPER_SETTINGS")
    candidate = path or (Path(env_path) if env_path else DEFAULT_SETTINGS_PATH)
    raw: dict[str, Any] = {}
    if candidate.exists():
        with candidate.open("rb") as fh:
            raw = tomllib.load(fh)
    if overrides:
        raw = _deep_merge(raw, overrides)
    settings = Settings.model_validate(raw)
    data_dir = os.environ.get("CLIPPER_DATA_DIR")
    if data_dir:
        settings = settings.with_data_dir(Path(data_dir))
    return settings


def _deep_merge(base: dict[str, Any], extra: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for key, value in extra.items():
        current = out.get(key)
        if isinstance(current, dict) and isinstance(value, dict):
            out[key] = _deep_merge(current, value)  # type: ignore[arg-type]
        else:
            out[key] = value
    return out


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return load_settings()
