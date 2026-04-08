# cogamer

Autonomous Claude Code agents for CoGames. Merged from the cogent + cogamer repos into this monorepo package.

## Commands

- Run tests: `uv run pytest packages/cogamer/tests/ -v`
- Lint: `uv run ruff check packages/cogamer/`
- CLI entry point: `cogamer` (defined in pyproject.toml `[project.scripts]`)

## Architecture

- **Platform layer** (`src/cogamer/`): cli, api, db, ecs, channel — manages agent lifecycle
- **Game layer** (`src/cogamer/cvc/`): Claude-vs-Claude game orchestration
- **PCO optimization** (`src/cogamer/pco/`): policy optimization via PCO

## Key details

- Config location: `~/.cogamer/config.yaml`
- Token prefix: `cgm_`
- Naming convention: everything is "cogamer", never "cogent"
- Models are in `src/cogamer/models.py`
- API routes in `src/cogamer/api/routes.py`, app factory in `src/cogamer/api/app.py`
- Auth via `src/cogamer/auth.py` (softmax tokens + per-cogamer tokens)
