# CoGames Setup

Install the cogames CLI, authenticate, and verify everything works.

## Steps

1. **Install dependencies**:
   ```bash
   uv sync
   ```

2. **Verify CLI**:
   ```bash
   uv run cogames --version
   ```
   If this fails, run `uv pip install cogames` and retry.

3. **Authenticate**:
   ```bash
   uv run cogames auth status
   ```
   If not authenticated, read the `SOFTMAX_TOKEN` secret and run:
   ```bash
   uv run cogames auth set-token $SOFTMAX_TOKEN
   ```

4. **Validate auth** — read your cogamer name from `cogamer/IDENTITY.md`, then run:
   ```bash
   uv run cogames leaderboard beta-cvc --policy <your-cogamer-name>
   ```
   If this succeeds, auth is working. If it fails with an auth error, repeat step 3. Always use `--policy <name>` instead of `--mine`.
