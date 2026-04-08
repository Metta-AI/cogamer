# cogamer

Autonomous Claude Code agents for CoGames. Merged from the cogent + cogamer repos into this monorepo package.

## Commands

- Run tests: `uv run pytest packages/cogamer/tests/ -v`
- Lint: `uv run ruff check packages/cogamer/`
- CLI entry point: `cogamer` (defined in pyproject.toml `[project.scripts]`)

## Architecture

- **CLI** (`src/cogamer/cli.py`): `cogamer` command-line tool
- **Game layer** (`src/cogamer/cvc/`): Claude-vs-Claude game orchestration
- **Agent runtime** (`src/cogamer/entrypoint.py`): container entrypoint
- **API/platform** lives in `packages/cogamer-api` (separate package)
