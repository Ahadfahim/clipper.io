"""`clipper doctor`: environment and health checks.

Each check returns a ``CheckResult``. Checks never change anything. The same results feed the
Health panel (Settings -> Health) and the first-run wizard.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal, cast

from clipper.agents.env import BILLING_ENV_KEYS
from clipper.settings import Settings

Status = Literal["ok", "warn", "fail", "skip"]


@dataclass(frozen=True)
class CheckResult:
    name: str
    status: Status
    detail: str
    fix: str = ""

    def as_dict(self) -> dict[str, str]:
        return asdict(self)


def _run(cmd: list[str], timeout: float = 20.0) -> tuple[int, str]:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 127, str(exc)
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def check_python() -> CheckResult:
    ok = sys.version_info[:2] == (3, 12)
    return CheckResult(
        "python",
        "ok" if ok else "warn",
        f"Python {sys.version.split()[0]} at {sys.executable}",
        "" if ok else "Run through `uv run` so the pinned 3.12 interpreter is used.",
    )


def check_no_api_key() -> CheckResult:
    found = [k for k in BILLING_ENV_KEYS if os.environ.get(k)]
    if found:
        return CheckResult(
            "claude-billing-env",
            "warn",
            f"{', '.join(found)} set in this shell; it is stripped from every agent subprocess",
            "Remove it from your user environment so nothing else bills the API.",
        )
    return CheckResult("claude-billing-env", "ok", "No API key in the environment; agents use the plan login")


def check_claude_login(settings: Settings) -> CheckResult:
    """Ask the Claude Code CLI which account is active (plan login, not API key)."""
    cli = (
        str(settings.agents.cli_path)
        if settings.agents.cli_path
        else _bundled_cli() or shutil.which("claude")
    )
    if not cli:
        return CheckResult(
            "claude-login", "fail", "Claude Code CLI not found", "Install claude-agent-sdk (bundles the CLI)."
        )
    env = {k: v for k, v in os.environ.items() if k not in BILLING_ENV_KEYS}
    try:
        proc = subprocess.run(
            [cli, "auth", "status"], capture_output=True, text=True, timeout=30, env=env, check=False
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return CheckResult("claude-login", "fail", f"could not run {cli}: {exc}")
    out = (proc.stdout + proc.stderr).strip()
    try:
        status = json.loads(proc.stdout)
    except ValueError:
        status = None
    if isinstance(status, dict):  # current CLIs answer `auth status` with JSON
        info = cast(dict[str, Any], status)
        method = str(info.get("authMethod") or "none")
        if not info.get("loggedIn"):
            return CheckResult(
                "claude-login",
                "fail",
                "Claude Code CLI is not logged in",
                f"Run `{cli}` and log in with /login.",
            )
        if "api" in method.lower():
            return CheckResult(
                "claude-login",
                "fail",
                f"logged in with {method}",
                "Log in with your Claude plan, not an API key.",
            )
        who = info.get("email") or info.get("subscriptionType") or ""
        return CheckResult("claude-login", "ok", f"logged in ({method}){f' · {who}' if who else ''}")
    lowered = out.lower()
    if proc.returncode != 0 or "not logged in" in lowered or "no auth" in lowered:
        return CheckResult(
            "claude-login",
            "fail",
            out[:200] or "not logged in",
            "Run `claude` once and log in with your Claude plan.",
        )
    if "api key" in lowered or "api_key" in lowered:
        return CheckResult("claude-login", "fail", out[:200], "Log in with your Claude plan, not an API key.")
    return CheckResult("claude-login", "ok", out.splitlines()[0][:200] if out else "logged in")


def _bundled_cli() -> str | None:
    try:
        import claude_agent_sdk

        bundled = Path(claude_agent_sdk.__file__).parent / "_bundled"
        for name in ("claude.exe", "claude"):
            if (bundled / name).exists():
                return str(bundled / name)
    except ImportError:
        return None
    return None


def check_ffmpeg(settings: Settings) -> CheckResult:
    ffmpeg = settings.paths.ffmpeg("ffmpeg")
    code, out = _run([ffmpeg, "-hide_banner", "-encoders"])
    if code != 0:
        return CheckResult("ffmpeg", "fail", f"{ffmpeg} not runnable", r"Install ffmpeg to C:\ffmpeg\bin.")
    has_nvenc = "h264_nvenc" in out
    has_x264 = "libx264" in out
    _, filters = _run([ffmpeg, "-hide_banner", "-filters"])
    has_ass = " ass " in filters
    detail = f"nvenc={'yes' if has_nvenc else 'no'} x264={'yes' if has_x264 else 'no'} libass={'yes' if has_ass else 'no'}"
    if settings.media.encoder == "nvenc" and not has_nvenc:
        return CheckResult("ffmpeg", "warn", detail, 'Set media.encoder = "x264" or install an NVENC build.')
    if not has_ass:
        return CheckResult("ffmpeg", "fail", detail, "Captions need an ffmpeg build with libass.")
    return CheckResult("ffmpeg", "ok", detail)


def check_yt_dlp(settings: Settings) -> CheckResult:
    code, out = _run([settings.paths.yt_dlp, "--version"])
    if code != 0:
        return CheckResult("yt-dlp", "fail", "yt-dlp not found", "Install yt-dlp and keep it updated.")
    return CheckResult("yt-dlp", "ok", out.strip())


def check_gpu_env(settings: Settings) -> CheckResult:
    py = settings.paths.gpu_python
    if not py.exists():
        return CheckResult(
            "gpu-env", "warn", f"{py} missing", "Run `just gpu-setup` (creates the CUDA WhisperX env)."
        )
    code, out = _run(
        [
            str(py),
            "-c",
            "import torch;print(torch.__version__, torch.cuda.is_available(), torch.version.cuda)",
        ],
        timeout=60,
    )
    if code != 0:
        return CheckResult("gpu-env", "fail", out.strip()[-200:])
    parts = out.split()
    if len(parts) >= 2 and parts[1] == "True":
        return CheckResult("gpu-env", "ok", out.strip())
    return CheckResult(
        "gpu-env", "fail", out.strip(), "Install the cu128 torch wheels (RTX 5080 needs CUDA 12.8+)."
    )


def check_face_model(settings: Settings) -> CheckResult:
    import importlib.util

    from clipper.media.faces import FACE_MODEL, FACE_MODEL_URL

    if importlib.util.find_spec("mediapipe") is None:
        return CheckResult(
            "faces", "warn", "mediapipe not installed", "Run `just setup` (the `faces` extra)."
        )
    model = settings.paths.models_dir / FACE_MODEL
    if not model.exists():
        return CheckResult("faces", "warn", f"{model} missing", f"Download {FACE_MODEL_URL} to {model}.")
    return CheckResult("faces", "ok", str(model))


def check_data_dir(settings: Settings) -> CheckResult:
    data = settings.paths.data_dir
    try:
        data.mkdir(parents=True, exist_ok=True)
        probe = data / ".write-probe"
        probe.write_text("ok")
        probe.unlink()
    except OSError as exc:
        return CheckResult("data-dir", "fail", f"{data}: {exc}")
    free_gb = shutil.disk_usage(data).free / 1e9
    status: Status = "ok" if free_gb > 30 else "warn"
    return CheckResult("data-dir", status, f"{data} writable, {free_gb:.0f} GB free")


def check_sources_dir(settings: Settings) -> CheckResult:
    """Source videos are the biggest files (1-3 GB per hour), so their folder gets its own check."""
    sources = settings.paths.sub("sources")
    try:
        sources.mkdir(parents=True, exist_ok=True)
        probe = sources / ".write-probe"
        probe.write_text("ok")
        probe.unlink()
    except OSError as exc:
        return CheckResult(
            "sources-dir", "fail", f"{sources}: {exc}", "Pick another folder in Settings → Storage."
        )
    free_gb = shutil.disk_usage(sources).free / 1e9
    if free_gb < 50:
        return CheckResult(
            "sources-dir",
            "warn",
            f"{sources}: {free_gb:.0f} GB free",
            "Less than 50 GB free: pick a bigger drive in Settings → Storage or shorten retention.",
        )
    return CheckResult("sources-dir", "ok", f"{sources} writable, {free_gb:.0f} GB free")


def check_database(settings: Settings) -> CheckResult:
    from clipper.db.migrate import current_revision, head_revision

    db = settings.paths.database
    if not db.exists():
        return CheckResult("database", "warn", f"{db} not created", "Run `clipper migrate`.")
    cur, head = current_revision(db), head_revision()
    if cur != head:
        return CheckResult("database", "warn", f"at {cur}, head is {head}", "Run `clipper migrate`.")
    return CheckResult("database", "ok", f"{db} at {cur}")


SECRETS_FIX = (
    "Save them in Settings: Discord (bot token), Accounts and browser (pairing token), "
    "Media and captions (Hugging Face token for speaker labels)."
)


def check_secrets() -> CheckResult:
    from clipper.secrets import SECRET_NAMES, get_secret

    missing = [name for name in SECRET_NAMES if get_secret(name) is None]
    if missing:
        return CheckResult("secrets", "warn", f"missing: {', '.join(missing)}", SECRETS_FIX)
    return CheckResult("secrets", "ok", "all secrets present in Credential Manager")


def run_checks(settings: Settings, *, include_slow: bool = True) -> list[CheckResult]:
    checks: list[Callable[[], CheckResult]] = [
        check_python,
        check_no_api_key,
        lambda: check_data_dir(settings),
        lambda: check_sources_dir(settings),
        lambda: check_database(settings),
        lambda: check_ffmpeg(settings),
        lambda: check_yt_dlp(settings),
        lambda: check_face_model(settings),
        check_secrets,
    ]
    if include_slow:
        checks += [lambda: check_claude_login(settings), lambda: check_gpu_env(settings)]
    results: list[CheckResult] = []
    for check in checks:
        try:
            results.append(check())
        except Exception as exc:  # a broken check must not hide the others
            results.append(CheckResult(getattr(check, "__name__", "check"), "fail", f"check crashed: {exc}"))
    return results


def format_results(results: list[CheckResult]) -> str:
    marks = {"ok": "OK  ", "warn": "WARN", "fail": "FAIL", "skip": "SKIP"}
    width = max((len(r.name) for r in results), default=10)
    lines = [
        f"{marks[r.status]}  {r.name.ljust(width)}  {r.detail}" + (f"\n      -> {r.fix}" if r.fix else "")
        for r in results
    ]
    return "\n".join(lines)
