"""Keep agent subprocesses on the user's Claude plan login.

The Agent SDK merges ``os.environ`` into the CLI subprocess environment and lets
``ClaudeAgentOptions.env`` override it. So billing variables are removed in two places:

1. ``scrub_process_env()`` deletes them from this process at startup, so nothing is inherited.
2. ``agent_subprocess_env()`` sets each of them to an empty string in ``options.env``, which
   overrides anything that sneaks back into ``os.environ`` later (an empty value counts as unset).

``tests/test_agent_env.py`` spawns the SDK transport against a fake CLI and asserts the final
subprocess environment carries no usable key.
"""

from __future__ import annotations

import os
from collections.abc import MutableMapping

# Any of these would switch Claude Code away from the plan login to per-token API billing
# (or to a third-party provider). None of them may reach an agent subprocess.
BILLING_ENV_KEYS: tuple[str, ...] = (
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "CLAUDE_CODE_USE_BEDROCK",
    "CLAUDE_CODE_USE_VERTEX",
    "CLAUDE_CODE_USE_FOUNDRY",
    "AWS_BEARER_TOKEN_BEDROCK",
)


def scrub_process_env(environ: MutableMapping[str, str] | None = None) -> list[str]:
    """Remove billing variables from the given environment (default: this process). Returns removed keys."""
    env = os.environ if environ is None else environ
    removed = [key for key in BILLING_ENV_KEYS if key in env]
    for key in removed:
        del env[key]
    return removed


def agent_subprocess_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    """The ``env`` mapping for ``ClaudeAgentOptions``: billing keys blanked, plus our own markers."""
    env: dict[str, str] = {key: "" for key in BILLING_ENV_KEYS}
    env["CLAUDE_CODE_ENTRYPOINT"] = "clipper"
    env["DISABLE_AUTOUPDATER"] = "1"
    if extra:
        for key, value in extra.items():
            if key in BILLING_ENV_KEYS:
                raise ValueError(f"{key} may not be passed to an agent subprocess")
            env[key] = value
    return env


def effective_env(inherited: dict[str, str], options_env: dict[str, str]) -> dict[str, str]:
    """Mirror of the SDK's merge (inherited first, options.env wins), minus empty billing keys."""
    merged = {**inherited, **options_env}
    return {k: v for k, v in merged.items() if not (k in BILLING_ENV_KEYS and v == "")}
