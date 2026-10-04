# Plan: choose the Claude model per agent in Settings

Status: proposed (2026-10-03). For whoever implements it. Read CLAUDE.md first (plan login only, rules in code, UI routine).

## Why
Every agent and subagent runs on one model: `agents.model = "claude-opus-5-5"` (`core/clipper/settings.py`, `config/settings.toml`). Settings only shows it as text. On a Claude Pro plan, Opus uses the shared usage allowance much faster than Sonnet or Haiku. So the busiest, simplest work (Scout every 15 minutes, QA checks, captions) spends the same budget per token as the hardest work. The user should be able to pick a model per role, see what each choice costs, and change it without restarting.

## What exists to build on
- `AgentSettings.model` (one string) → `agent_definitions()` and `build_options()` in `core/clipper/agents/definitions.py` pass it to the main agent and every subagent.
- The SDK (claude-agent-sdk 0.2.163) takes any model string on `ClaudeAgentOptions.model` and `AgentDefinition.model`, plus `ClaudeAgentOptions.fallback_model`.
- `RoleSettings` / `SubagentSettings` already hold per-agent `effort` and `max_turns`. Settings → Agents shows them as a grid ("Effort and turn limits").
- Live controls (`services/control.py`: `set_control`, `configured_slots`) change behaviour without a restart; file settings (`PATCH /api/settings`) need one.
- `UsageService` tracks the plan's usage window (`utilization`, `rate_limited`, pacing).

## Design
1. **Settings model** (`settings.py`)
   - `AgentSettings.model` stays as the default for everything.
   - `RoleSettings.model: str | None = None` and `SubagentSettings.model: str | None = None`. `None` means: role → `agents.model`; subagent → its role's model.
   - `AgentSettings.fallback_model: str | None = "claude-sonnet-5-5"`, passed to the SDK, so a session keeps going if its model is unavailable.
   - A `MODELS` catalogue in code: id, label, and a one-line "use for" note. It holds `claude-opus-5-5`, `claude-sonnet-5-5`, `claude-haiku-4-5-20251001` and `claude-fable-5-1`. The app lists only these, plus "Custom…" for an ID typed by hand, validated by the test in step 5.
   - Effective-model resolution lives in one function, `model_for(role, sub=None)`, and both `agent_definitions()` and `build_options()` use it.
2. **Live, no restart**
   - Store model overrides in the control KV, like `slots`: keys `model.default` and `model.<role>` / `model.<role>.<sub>`. `model_for()` reads the KV first, then the settings file.
   - Changes apply to the **next** session. A running session keeps its model, and the UI says so.
   - `ControlIn.key` grows a `model` form (or a dedicated `PUT /api/agents/models` taking the whole map; preferred, one request per Save).
   - `set_control` validation: the value is a catalogue ID, or a custom ID that passed the test in step 5. Never accept an empty string.
3. **Presets** (one click, written as the whole map)
   - **Balanced (recommended for Pro)**: Director on Opus. Campaign, Analyst, brief-reader, cutter, editor and browser-fixer on Sonnet. Scout, qa-checker, copywriter and research on Haiku.
   - **Save usage**: everything on Sonnet except Scout, qa-checker, copywriter and research on Haiku.
   - **Best quality**: everything on Opus. Show a warning that it hits the plan limit fastest.
   - **Custom**: whatever the grid holds.
4. **UI** (Settings → Agents; follow CLAUDE.md "UI work": frontend-design skill, shadcn MCP, utility style, check dark/light at 1280×800 and 1920×1080)
   - Replace the "Model: claude-opus-5-5" text with a **Preset** select and a **Default model** select.
   - Add a **Model** column to the "Effort and turn limits" grid (rename it "Model, effort and turn limits"). Each row gets a select whose first option is "Default (Sonnet 5.5)" or "Role's model (…)", showing what it resolves to.
   - A muted line under the grid: "Opus uses your plan's allowance fastest; Haiku slowest. Changes apply to the next agent session."
   - On the Agents screen, show the model in each slot row and in the session property grid. The board already has the slot row; add a `model` field to the slot and session schemas.
5. **Check a model works on this plan**
   - A **Test** button next to the default and custom models: `POST /api/agents/models/test {model}` runs one tiny turn ("Reply OK") through the plan login, with the same env scrubbing as agents (no `ANTHROPIC_API_KEY`).
   - Show "Works on your plan" or the error (e.g. model not available on this plan). Doctor gets the same check for the configured models.
   - Never add API-key billing as a fallback.
6. **Record what ran**
   - `agent_session.model` (migration 0002) is set when a session starts. The SDK's init message reports the model actually used, so record that one: it shows when the fallback kicked in.
   - The Agents screen and the run history show it. This lets the user compare quality per model on real campaigns.
7. **Usage pacing** (later, optional)
   - When `utilization` crosses `usage.downgrade_at` (e.g. 0.75), new background sessions (P2/P3) use the fallback model instead of Opus. Your own requests (P0) keep their model.
   - Off by default and set in Settings → Usage, next to "Slow down first under high usage".

## Tests
- `model_for` resolution: subagent override → role override → default. The KV beats the file.
- `build_options()` and `agent_definitions()` carry the resolved models and `fallback_model`.
- The control route refuses unknown or empty models and accepts a tested custom ID. The change applies to the next session only.
- Model test route: success and "not available" paths with a fake runner; `ANTHROPIC_API_KEY` is stripped.
- Migration adds `agent_session.model`, and the session records the reported model.
- UI: the grid renders resolved defaults, a preset fills the grid, and Save sends one request (vitest). Regenerate OpenAPI, TS types and fixtures (`just gen-api`, fixtures export, no secrets).

## Order of work
1. Settings fields + `model_for` + SDK wiring + tests (no UI). Ship with defaults = today's behaviour except `fallback_model`.
2. KV overrides + route + presets.
3. Settings UI + Agents screen model display.
4. Model test button + doctor check.
5. `agent_session.model` + migration.
6. Usage-based downgrade (optional).

## Out of scope
- Any API-key or pay-per-token path.
- Models from other providers.
- Per-campaign model choice. That's possible later on the same KV keys (`model.campaign.<id>`).
