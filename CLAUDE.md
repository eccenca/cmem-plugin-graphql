# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

`cmem-plugin-graphql` is a [Corporate Memory (CMEM)](https://documentation.eccenca.com) plugin that executes GraphQL queries/mutations against an endpoint and saves results to a JSON dataset. It is generated from the [`eccenca/cmem-plugin-template`](https://github.com/eccenca/cmem-plugin-template).

## Quick Commands

```bash
# Install dependencies
poetry install

# Run all checks (linters + tests)
task check

# Run only unit tests (no CMEM server required)
task check:pytest

# Lint / format
task check:ruff          # lint only (non-fatal --exit-zero)
task check:mypy          # type checking
task check:deptry        # unused/missing deps
task check:trivy         # vulnerability scan
task format:fix          # auto-format + safe fixes
task format:fix-unsafe   # auto-format + unsafe fixes

# Build distribution
task build               # poetry build + export requirements.txt

# Install/uninstall plugin in a CMEM workspace
task install             # build + cmemc admin workspace python install
task uninstall           # cmemc admin workspace python uninstall
```

Tests that require a live CMEM server are guarded with `@needs_cmem` (skips unless `CMEM_BASE_URI` is set). The lone non-CMEM test is `test_is_string_jinja_template` and `test_dummy`.

## Architecture

```
cmem_plugin_graphql/
  __init__.py              # package marker (empty)
  workflow/
    graphql.py             # GraphQLPlugin — the single WorkflowPlugin entry point
    utils.py               # jinja template detection, entity/dict conversion helpers
tests/
  test_graphql.py          # integration tests against a public test GraphQL endpoint
```

### Key module: `workflow/graphql.py`

- **`GraphQLPlugin`** — decorated with `@Plugin(...)` to register as a CMEM workflow task. Parameters: `graphql_url`, `graphql_query`, `graphql_variable_values`, `graphql_dataset` (optional), `oauth_access_token` (optional).
- Query validation: detects Jinja templates via `is_jinja_template()` (renders and checks for substitution); otherwise validates as pure GraphQL syntax with `gql()`.
- Variable values validation: detects Jinja templates or validates as JSON.
- **`execute()`** branching logic:
  - If Jinja is detected in either query or variables → iterates over input `Entities`, renders per-entity, executes per entity via `process_entities()`.
  - Otherwise → single-shot execution against the endpoint with static variables.
- Results are collected into a list; if `graphql_dataset` is set, payload is written to that CMEM dataset via `write_to_dataset()`.

### Key module: `workflow/utils.py`

- **`is_jinja_template(value)`** — renders through Jinja's `Environment`; if the rendered output differs from the input, Jinja variables were present.
- **`get_dict(entities)`** — iterator that flattens `Entities` into per-entity dicts keyed by schema path.
- **`get_entities_from_list(data)` / `create_entity(paths, dict_)`** — bidirectional helpers for converting between `list[dict]` and `Entities`.

## Dependencies

| Category | Key packages |
|----------|-------------|
| Runtime | `graphql-core`, `gql[all]`, `Jinja2`, `validators` |
| CMEM base | `cmem-plugin-base ^4.19.0` (declared as a Poetry `[tool.poetry.dependencies.cmem-plugin-base]` extra) |
| Dev | `ruff`, `mypy`, `deptry`, `trivy-py-ecc`, `pytest` + cov, html, memray, dotenv |

Python version: **3.13** (pinned in `.python-version`).

## CI/CD

- `.github/workflows/check.yml` — runs mypy, ruff, pytest, deptry, trivy on PRs/pushes to `main`/`develop`.
- `.github/workflows/publish.yml` — publishes to PyPI on tag push or manual dispatch.
- Pre-commit hooks mirror the CI linters (ruff, poetry-check, poetry-lock) plus trivy.