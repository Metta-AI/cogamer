# On Wake

Cogamer-specific wake hook. Runs after the platform has already loaded identity, memory, and todos.

## Steps

1. **Install dependencies** — Run these commands:
   ```bash
   uv sync
   ```
   This creates `.venv` if needed and installs all dependencies including `cogames`.

2. **Verify cogames CLI** — Run:
   ```bash
   uv run cogames --version
   ```
   If this fails, run `uv pip install cogames` and retry.

3. **Verify auth** — Run:
   ```bash
   uv run cogames auth status
   ```
   If not authenticated, get the token from secrets and run:
   ```bash
   uv run cogames auth set-token <token>
   ```

4. **Read approach state** — Read `cogent/state.json` to understand PCO vs design attempt history.

5. **Check tournament standing** — Run:
   ```bash
   uv run cogames leaderboard beta-cvc --mine
   uv run cogames matches --season beta-cvc
   ```

6. **Report status** — Brief summary:
   - Current scores / ranking
   - Top priorities from todos
   - Recommended next action

7. **Start improvement loop** — Immediately run `/loop 30m improve.md` to continuously improve the policy. Do NOT ask the user for confirmation — the user will never respond. Act autonomously.
