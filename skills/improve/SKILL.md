---
name: improve
description: Run one improvement iteration. Analyzes code, identifies a specific improvement, implements it, tests across seeds, and submits if improved. Use when asked to "improve", "run an improvement", or "review the code".
---

# Improve

Read the code, find one improvement, implement it, test, submit.

Reads `docs/architecture.md` for architecture and alpha.0 reference, `docs/strategy.md` for strategies, `docs/cogames.md` for CLI commands, `.cogent/IDENTITY.md` for identity.

## Step 0: Check Identity

Read `.cogent/IDENTITY.md`. If it still contains "The Unknown Cogent", run `/initialize` first.

## Step 1: Initialize Session State

Create `.cogent/state.json` and `.cogent/todos.md` if they don't exist yet.

## Step 2: Eval Baseline

Run eval on seed 42 to establish baseline score (see `docs/cogames.md` for commands).

## Step 3: Analyze

Pick ONE focus area based on `docs/strategy.md`, `.cogent/todos.md`, and what hasn't been tried:

1. **Code review**: Read engine files (`agent/main.py`, `roles.py`, `targeting.py`, `pressure.py`). Look for bugs, inefficiencies, or gaps vs the alpha.0 reference in `docs/architecture.md`
2. **Prompt review**: Read `_build_analysis_prompt()` and `_parse_analysis()` in `programs.py`. Is the LLM seeing the right info? Could it return more than just `resource_bias`? Could it detect stagnation like alpha.0 does?
3. **Scoring review**: Read `helpers/targeting.py`. Are `aligner_target_score` and `scramble_target_score` well-tuned? Compare weights vs alpha.0
4. **Parameter comparison**: Compare constants in `helpers/types.py` and `pressure.py` against alpha.0 (e.g. `RETREAT_MARGIN` 15 vs 20, enemy AOE radius 4 vs 20)
5. **Architecture improvement**: Read `cvc_policy.py`. Is the LLM feedback loop working? Could the `analyze` program influence more than mining? Could it adjust role allocation or targeting?

## Step 4: Implement

Make a focused, isolated change. Write the code directly.

- **Prompt improvements**: modify `_build_analysis_prompt()` or `_parse_analysis()` in `programs.py`
- **Code improvements**: modify the relevant engine file in `agent/`
- **Parameter changes**: modify `helpers/types.py` or the relevant mixin
- **New programs**: add to `programs.py` and wire into `all_programs()`

## Step 5: Test Across Seeds

Run eval across 5+ seeds. If average score drops vs baseline, **revert**.

## Step 6: Submit if Improved

If scores improved, automatically submit to freeplay without asking. Read the cogent name from `.cogent/IDENTITY.md` (the `# heading`) and use it as the policy name. See `docs/cogames.md` for the upload command.

Do NOT ask the user for confirmation — submit automatically. Log the submission version.

## Step 7: Update State

Update `.cogent/state.json` and `.cogent/todos.md` with the result.

## Output

Report back with:
- `improved`: whether scores improved
- `score_before`: baseline average
- `score_after`: post-change average (or null if reverted)
- `focus`: which area was analyzed
- `description`: what changed and why

## Principles

- **One change per session.** Isolate what works vs what breaks.
- **Track what works.** Update state and todos after every session.
- **Revert on regression.** If average score drops, revert immediately.
