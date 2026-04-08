# Cogamer Package Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Create `packages/cogamer/` in the metta monorepo by merging the cogent platform (ECS orchestration, CLI, API, DynamoDB) and cogamer game code (CvC policy, coglet, PCO) into a single package.

**Architecture:** Single Python package `cogamer` with platform code (cli, api, db, ecs, etc.) at the top level and game code under `cogamer.cvc`. The coglet framework is folded into `cogamer.cvc`. All references to "cogent" are renamed to "cogamer". AWS infra gets fresh cogamer-named resources.

**Tech Stack:** Python 3.12, FastAPI, Click, boto3, pydantic, AWS CDK, mettagrid/cogames workspace deps

**Source repos:**
- Platform (cogent): `/Users/daveey/code/cogent/cogent.0/`
- Game (cogamer): `/Users/daveey/code/cogamer/cogamer.0/`
- Target: `/Users/daveey/code/metta.4/packages/cogamer/`

---

### Task 1: Scaffold package and register in workspace

**Files:**
- Create: `packages/cogamer/pyproject.toml`
- Create: `packages/cogamer/src/cogamer/__init__.py`
- Create: `packages/cogamer/src/cogamer/py.typed`
- Modify: `pyproject.toml` (root — add workspace member + source)

**Step 1: Create directory structure**

```bash
mkdir -p packages/cogamer/src/cogamer
mkdir -p packages/cogamer/tests
```

**Step 2: Create pyproject.toml**

Create `packages/cogamer/pyproject.toml`:

```toml
[build-system]
requires = ["setuptools==80.9.0", "wheel==0.45.1"]
build-backend = "setuptools.build_meta"

[project]
name = "cogamer"
version = "0.1.0"
description = "Autonomous Claude Code agents for CoGames"
requires-python = ">=3.12,<3.13"
dependencies = [
    "click>=8.1",
    "httpx>=0.27",
    "fastapi>=0.115",
    "fastapi-mcp>=0.1",
    "uvicorn>=0.34",
    "pydantic>=2.0",
    "boto3>=1.35",
    "rich>=13.0",
    "pyyaml>=6.0.3",
    "mangum>=0.19",
    "cogames",
    "mettagrid",
]

[project.scripts]
cogamer = "cogamer.cli:main"

[project.optional-dependencies]
test = ["pytest>=8.0", "pytest-asyncio>=0.24", "pytest-timeout>=2.3", "ruff"]
infra = ["aws-cdk-lib>=2.170", "constructs>=10.0"]

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
timeout = 60
pythonpath = ["src"]
addopts = "--import-mode=importlib -m 'not e2e'"
markers = ["e2e: end-to-end tests requiring external services"]

[tool.ruff]
extend = "../../.ruff.toml"

[tool.uv.sources]
cogames = { workspace = true }
mettagrid = { workspace = true }
```

**Step 3: Create __init__.py and py.typed**

`packages/cogamer/src/cogamer/__init__.py`: empty file
`packages/cogamer/src/cogamer/py.typed`: empty file

**Step 4: Register in root pyproject.toml**

Add `"packages/cogamer"` to `[tool.uv.workspace] members` list.
Add `cogamer = { workspace = true }` to `[tool.uv.sources]`.

**Step 5: Verify workspace resolution**

Run: `cd /Users/daveey/code/metta.4 && uv pip install -e packages/cogamer --dry-run 2>&1 | head -20`
Expected: resolves without errors (dry run)

**Step 6: Commit**

```bash
git add packages/cogamer/ pyproject.toml
git commit -m "feat: scaffold cogamer package in monorepo"
```

---

### Task 2: Copy and rename platform code (cogent → cogamer)

**Source:** `/Users/daveey/code/cogent/cogent.0/src/cogent/`
**Target:** `packages/cogamer/src/cogamer/`

This task copies all platform source files and renames cogent→cogamer in all code.

**Files to copy (with renames applied):**
- `auth.py` — rename imports, `AuthenticatedCogent` → `AuthenticatedCogamer`
- `cli.py` — rename CLI command `cogent` → `cogamer`, all references
- `config.py` — `~/.cogent/` → `~/.cogamer/`, `COGENT_*` → `COGAMER_*`
- `dashboard_server.py` — rename imports
- `db.py` — `COGENT#` → `COGAMER#`, table name `cogent` → `cogamer`
- `ecs.py` — rename cluster/task refs
- `entrypoint.py` — rename all references
- `models.py` — `CogentState` → `CogamerState`, `CogentConfig` → `CogamerConfig`, token prefix `cgt_` → `cgm_`
- `secrets.py` — `cogent/` → `cogamer/` prefix
- `tunnel.py` — rename imports
- `api/__init__.py`, `api/app.py`, `api/routes.py`, `api/lambda_handler.py` — rename routes `/cogents/` → `/cogamers/`
- `channel/__init__.py`, `channel/mcp_server.py` — rename all references

**Step 1: Copy files preserving directory structure**

```bash
# Copy platform source files
cp -r /Users/daveey/code/cogent/cogent.0/src/cogent/api packages/cogamer/src/cogamer/
cp -r /Users/daveey/code/cogent/cogent.0/src/cogent/channel packages/cogamer/src/cogamer/
cp /Users/daveey/code/cogent/cogent.0/src/cogent/{auth,cli,config,dashboard_server,db,ecs,entrypoint,models,secrets,tunnel}.py packages/cogamer/src/cogamer/
```

**Step 2: Rename all cogent references to cogamer**

Apply these renames across all copied files:
- `cogent` → `cogamer` (package/import references)
- `Cogent` → `Cogamer` (class names)
- `COGENT` → `COGAMER` (env vars, DynamoDB keys)
- `cgt_` → `cgm_` (token prefix)
- `~/.cogent/` → `~/.cogamer/`
- `/cogents/` → `/cogamers/` (API routes)

Use sed or manual edits. Be careful not to rename inside strings that reference external things (e.g. `cogames` should stay `cogames`).

**Step 3: Verify imports parse**

Run: `cd /Users/daveey/code/metta.4 && python -c "import ast; [ast.parse(open(f).read()) for f in __import__('glob').glob('packages/cogamer/src/cogamer/**/*.py', recursive=True)]"`
Expected: no syntax errors

**Step 4: Commit**

```bash
git add packages/cogamer/src/cogamer/
git commit -m "feat: copy cogent platform code, rename to cogamer"
```

---

### Task 3: Copy and integrate game code (CvC + coglet)

**Source:** `/Users/daveey/code/cogamer/cogamer.0/src/`
**Target:** `packages/cogamer/src/cogamer/cvc/` and `packages/cogamer/src/cogamer/pco/`

**Step 1: Copy CvC game code**

```bash
cp -r /Users/daveey/code/cogamer/cogamer.0/src/cogamer/cvc packages/cogamer/src/cogamer/
cp /Users/daveey/code/cogamer/cogamer.0/src/cogamer/__init__.py packages/cogamer/src/cogamer/cvc/__init__.py  # if needed
cp /Users/daveey/code/cogamer/cogamer.0/src/cogamer/setup_policy.py packages/cogamer/src/cogamer/cvc/
```

**Step 2: Copy coglet into cvc/ (fold it in)**

```bash
# Copy coglet core files into cvc/
cp /Users/daveey/code/cogamer/cogamer.0/src/coglet/{coglet,proglet,runtime,llm_executor,channel,handle,lifelet}.py packages/cogamer/src/cogamer/cvc/
```

**Step 3: Copy PCO framework**

```bash
mkdir -p packages/cogamer/src/cogamer/pco
cp /Users/daveey/code/cogamer/cogamer.0/src/coglet/pco/{__init__,optimizer,learner,constraint,loss}.py packages/cogamer/src/cogamer/pco/
```

**Step 4: Fix imports**

All files that imported from `coglet` now import from `cogamer.cvc`:
- `from coglet.coglet import Coglet` → `from cogamer.cvc.coglet import Coglet`
- `from coglet.proglet import ...` → `from cogamer.cvc.proglet import ...`
- `from coglet.pco.optimizer import ...` → `from cogamer.pco.optimizer import ...`
- `from cogamer.cvc.xxx import ...` stays the same (already correct namespace)

Also fix any `from cogamer.cvc.agent` imports that assumed the old `pythonpath = ["src/cogamer"]` — they now need full paths from `cogamer.cvc.agent`.

**Step 5: Verify imports parse**

Run: `cd /Users/daveey/code/metta.4 && python -c "import ast; [ast.parse(open(f).read()) for f in __import__('glob').glob('packages/cogamer/src/cogamer/cvc/**/*.py', recursive=True)]"`

**Step 6: Commit**

```bash
git add packages/cogamer/src/cogamer/cvc/ packages/cogamer/src/cogamer/pco/
git commit -m "feat: add CvC game code and coglet/PCO framework"
```

---

### Task 4: Copy and merge lifecycle, skills, memory, docs

**Step 1: Copy lifecycle prompts**

```bash
mkdir -p packages/cogamer/lifecycle
# From cogent (platform lifecycle)
cp /Users/daveey/code/cogent/cogent.0/src/cogent/lifecycle/{wake,tick,sleep,die,start,message-owner}.md packages/cogamer/lifecycle/
# From cogamer (agent hooks — merge content into lifecycle files)
# on-wake.md content merges into wake.md
# on-sleep.md content merges into sleep.md
# on-create.md content merges into start.md
```

Merge the cogamer hook content into the corresponding lifecycle files by appending the cogamer-specific sections.

**Step 2: Copy skills**

```bash
mkdir -p packages/cogamer/skills
# From cogent
cp /Users/daveey/code/cogent/cogent.0/src/cogent/skills/dashboard.md packages/cogamer/skills/
# From cogamer
cp /Users/daveey/code/cogamer/cogamer.0/cogent/skills/{cogames,improve,proximal-cogent-optimize}.md packages/cogamer/skills/
```

Rename any "cogent" references in skill files to "cogamer".

**Step 3: Copy memory docs**

```bash
mkdir -p packages/cogamer/memory
cp /Users/daveey/code/cogent/cogent.0/src/cogent/memory/{memory,memory-load,memory-save,memory-wipe}.md packages/cogamer/memory/
```

**Step 4: Copy and merge docs**

```bash
mkdir -p packages/cogamer/docs
# From cogamer (game docs)
cp /Users/daveey/code/cogamer/cogamer.0/docs/{architecture,cogames,cvc,strategy,rules,tools,ideas}.md packages/cogamer/docs/
# From cogent (capabilities + design docs)
cp /Users/daveey/code/cogent/cogent.0/src/cogent/{capabilities,cogent}.md packages/cogamer/docs/
mv packages/cogamer/docs/cogent.md packages/cogamer/docs/platform.md
# Plans directory
mkdir -p packages/cogamer/docs/plans
cp /Users/daveey/code/cogent/cogent.0/docs/plans/2026-04-07-cogamer-merge-design.md packages/cogamer/docs/plans/
```

**Step 5: Copy IDENTITY.md and other top-level files**

```bash
cp /Users/daveey/code/cogamer/cogamer.0/cogent/INTENTION.md packages/cogamer/IDENTITY.md
```

**Step 6: Commit**

```bash
git add packages/cogamer/lifecycle/ packages/cogamer/skills/ packages/cogamer/memory/ packages/cogamer/docs/ packages/cogamer/IDENTITY.md
git commit -m "feat: add lifecycle, skills, memory, and docs"
```

---

### Task 5: Copy and merge tests

**Source (cogent tests):** `/Users/daveey/code/cogent/cogent.0/tests/`
**Source (cogamer tests):** `/Users/daveey/code/cogamer/cogamer.0/tests/`
**Target:** `packages/cogamer/tests/`

**Step 1: Copy cogent platform tests**

```bash
cp /Users/daveey/code/cogent/cogent.0/tests/{test_api,test_auth,test_channel_plugin,test_cli,test_db,test_ecs,test_models,test_secrets}.py packages/cogamer/tests/
```

**Step 2: Copy cogamer game tests**

```bash
mkdir -p packages/cogamer/tests/cvc/agent
cp /Users/daveey/code/cogamer/cogamer.0/tests/conftest.py packages/cogamer/tests/
cp /Users/daveey/code/cogamer/cogamer.0/tests/cvc/{__init__,test_coglet_policy,test_programs}.py packages/cogamer/tests/cvc/
cp /Users/daveey/code/cogamer/cogamer.0/tests/cvc/agent/{__init__,test_budgets,test_decisions,test_geometry,test_pathfinding,test_resources,test_scoring,test_tick_context,test_world_model}.py packages/cogamer/tests/cvc/agent/
touch packages/cogamer/tests/__init__.py packages/cogamer/tests/cvc/__init__.py packages/cogamer/tests/cvc/agent/__init__.py
```

**Step 3: Fix imports in all test files**

Platform tests: `from cogent.xxx` → `from cogamer.xxx`, `CogentState` → `CogamerState`, etc.
Game tests: `from cvc.xxx` → `from cogamer.cvc.xxx`, `from coglet.xxx` → `from cogamer.cvc.xxx`

**Step 4: Run tests**

Run: `cd /Users/daveey/code/metta.4 && uv run pytest packages/cogamer/tests/ -v --tb=short 2>&1 | tail -40`
Expected: tests pass (some may need fixture updates for CogentState→CogamerState renames)

**Step 5: Fix any test failures**

Likely fixes:
- Update fixture data that references "cogent" strings
- Update mock paths (`cogent.db` → `cogamer.db`, etc.)
- Update DynamoDB key assertions (`COGENT#` → `COGAMER#`)
- Update token prefix assertions (`cgt_` → `cgm_`)

**Step 6: Commit**

```bash
git add packages/cogamer/tests/
git commit -m "feat: add merged test suite"
```

---

### Task 6: Copy and rename infra (CDK + Docker)

**Step 1: Copy infra**

```bash
mkdir -p packages/cogamer/infra
cp /Users/daveey/code/cogent/cogent.0/infra/{app,stack}.py packages/cogamer/infra/
cp /Users/daveey/code/cogent/cogent.0/infra/cdk.json packages/cogamer/infra/
```

**Step 2: Rename in stack.py**

- `CogentStack` → `CogamerStack`
- Table name `cogent` → `cogamer`
- ECS cluster `cogent` → `cogamer`
- ECR repo name → `cogamer`
- IAM role names `cogent-*` → `cogamer-*`
- All construct IDs

**Step 3: Rename in app.py**

- `CogentStack` → `CogamerStack`
- Stack name → `cogamer`

**Step 4: Copy Dockerfile**

```bash
mkdir -p packages/cogamer/docker
cp /Users/daveey/code/cogent/cogent.0/docker/Dockerfile packages/cogamer/docker/
```

**Step 5: Rename in Dockerfile**

- User `cogent` → `cogamer`
- Any `cogent` references in labels, paths, entrypoint
- Entrypoint: `python -m cogent.entrypoint` → `python -m cogamer.entrypoint`

**Step 6: Commit**

```bash
git add packages/cogamer/infra/ packages/cogamer/docker/
git commit -m "feat: add infra and Dockerfile renamed to cogamer"
```

---

### Task 7: Create CLAUDE.md and final wiring

**Step 1: Create CLAUDE.md**

Create `packages/cogamer/CLAUDE.md` with package-specific instructions: how to run tests, deploy, key architecture notes.

**Step 2: Verify full test suite passes**

Run: `cd /Users/daveey/code/metta.4 && uv run pytest packages/cogamer/tests/ -v --tb=short`
Expected: all tests pass

**Step 3: Verify lint passes**

Run: `cd /Users/daveey/code/metta.4 && uv run ruff check packages/cogamer/`
Expected: no errors (fix any that come up)

**Step 4: Verify CLI entry point works**

Run: `cd /Users/daveey/code/metta.4 && uv run cogamer --help`
Expected: shows help text with cogamer commands

**Step 5: Commit**

```bash
git add packages/cogamer/CLAUDE.md
git commit -m "feat: add CLAUDE.md and finalize cogamer package"
```

---

### Task 8: Final cleanup and validation

**Step 1: Remove any leftover cogent references**

Run: `grep -r "cogent" packages/cogamer/src/ --include="*.py" -l`
Review and fix any remaining `cogent` references (but not `cogent` as substring of other words).

**Step 2: Remove __pycache__ and .pyc files**

```bash
find packages/cogamer/ -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null
```

**Step 3: Full test run**

Run: `cd /Users/daveey/code/metta.4 && uv run pytest packages/cogamer/tests/ -v`
Expected: all tests pass

**Step 4: Commit any final fixes**

```bash
git add -A packages/cogamer/
git commit -m "chore: final cleanup of cogamer package"
```
