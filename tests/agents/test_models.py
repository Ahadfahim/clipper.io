"""Which model each agent runs on: resolution, app choices (no restart), checks, and the SDK wiring."""

from __future__ import annotations

import pytest

from clipper.agents import models as am
from clipper.agents.definitions import agent_definitions
from clipper.core import Core
from clipper.settings import Settings


def test_resolution_subagent_then_role_then_default(core: Core) -> None:
    s = core.settings
    assert am.model_for(s, core.db, "campaign") == s.agents.model
    assert am.model_for(s, core.db, "campaign", "cutter") == s.agents.model
    am.set_models(
        core.db,
        {"default": am.SONNET, "roles": {"campaign": am.OPUS}, "subagents": {"qa-checker": am.HAIKU}},
    )
    assert am.model_for(s, core.db, "scout") == am.SONNET  # default
    assert am.model_for(s, core.db, "campaign") == am.OPUS  # role choice
    assert am.model_for(s, core.db, "campaign", "cutter") == am.OPUS  # inherits its role
    assert am.model_for(s, core.db, "campaign", "qa-checker") == am.HAIKU  # its own


def test_the_settings_file_is_the_fallback(settings: Settings, core: Core) -> None:
    roles = dict(settings.agents.roles)
    roles["scout"] = roles["scout"].model_copy(update={"model": am.HAIKU})
    s = settings.model_copy(update={"agents": settings.agents.model_copy(update={"roles": roles})})
    assert am.model_for(s, core.db, "scout") == am.HAIKU
    am.set_models(core.db, {"roles": {"scout": am.SONNET}})
    assert am.model_for(s, core.db, "scout") == am.SONNET  # the app's choice wins


def test_presets_are_valid_and_balanced_is_light_where_work_is_frequent(core: Core) -> None:
    for preset in am.PRESETS.values():
        am.set_models(core.db, preset)
    am.set_models(core.db, {**am.PRESETS["balanced"], "preset": "balanced"})
    r = am.resolved(core.settings, core.db)
    assert r["director"] == am.OPUS and r["campaign"] == am.SONNET and r["scout"] == am.HAIKU
    assert r["campaign/qa-checker"] == am.HAIKU and r["campaign/cutter"] == am.SONNET
    assert am.overrides(core.db)["preset"] == "balanced"


def test_unknown_or_untested_models_are_refused(core: Core) -> None:
    for bad, msg in (
        ({"default": ""}, "not a model id"),
        ({"default": "claude-fable-5-1"}, "test it first"),
        ({"roles": {"nobody": am.SONNET}}, "unknown agent"),
        ({"subagents": {"ghost": am.SONNET}}, "unknown subagent"),
    ):
        with pytest.raises(ValueError, match=msg):
            am.set_models(core.db, bad)
    am.mark_tested(core.db, "claude-custom-9")
    am.set_models(core.db, {"default": "claude-custom-9"})
    assert am.model_for(core.settings, core.db, "director") == "claude-custom-9"


def test_sessions_get_the_resolved_models_and_a_fallback(core: Core) -> None:
    am.set_models(core.db, am.PRESETS["balanced"])
    defs = agent_definitions("campaign", core.settings, core.db)
    assert defs["campaign"].model == am.SONNET and defs["qa-checker"].model == am.HAIKU
