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

The plugin talks to no Corporate Memory deployment, so no test needs one. The tests that really call a GraphQL endpoint - three of them mutations against a public endpoint nobody here owns - are guarded with `@needs_endpoint` and run only when `TESTING_GRAPHQL_ENDPOINT` names the endpoint. `@needs_gitlab` guards the one test authenticating with a real token, on `TESTING_GITLAB_TOKEN` and `TESTING_GITLAB_URL`. Everything else runs offline.

## Architecture

```
cmem_plugin_graphql/
  __init__.py              # package marker (empty)
  workflow/
    graphql.py             # GraphQLPlugin — the single WorkflowPlugin entry point
    utils.py               # schema derivation, entity building, jinja rendering helpers
tests/
  test_graphql.py          # unit tests, plus endpoint tests behind TESTING_GRAPHQL_ENDPOINT
```

### Key module: `workflow/graphql.py`

- **`GraphQLPlugin`** — decorated with `@Plugin(...)` to register as a DataIntegration workflow task. Parameters, in the order the form shows them: `graphql_url`, `access_token` (a `Password`), `output_mode` (`entities` or `file`), `graphql_query`, `graphql_variable_values`. The form order follows the constructor signature, not the decorator list, so the two optional leading parameters carry no Python default and rely on their `PluginParameter` `default_value`.
- Query validation: detects Jinja templates via `is_jinja_template()` (renders and checks for substitution); otherwise validates as pure GraphQL syntax with `gql()`.
- Variable values validation: detects Jinja templates or validates as JSON.
- **`execute()`** branching logic:
  - If Jinja is detected in either query or variables → iterates over input `Entities`, renders per-entity, executes per entity via `process_entities()`.
  - Otherwise → single-shot execution against the endpoint with static variables.
- Results are collected into a list and leave on the output port. In `file` mode they are written to one `graphql-result.json` in a fresh temporary directory and handed on as a `FileEntitySchema` entity; otherwise they become entities.
- **`_set_ports()`** — derives the output schema from the query with `output_schema_from_query()` and declares a `FixedSchemaPort`, falling back to `UnknownSchemaPort` when the query describes nothing (a Jinja template, several operations, a fragment at the top level).

### Key module: `workflow/utils.py`

- **`render_template(text, values)`** — renders with autoescaping **off**: the output is GraphQL or JSON, and HTML escaping would corrupt both. `S701` is suppressed there with the reason in place.
- **`is_jinja_template(value)`** — renders through `render_template`; if the rendered output differs from the input, Jinja syntax was present.
- **`output_schema_from_query(query)`** — turns the top level of a parsed query into an `EntitySchema`, aliases included, or `None` when the query describes nothing.
- **`entities_from_payload(payload, schema)`** — builds entities that conform to the declared schema rather than to the response, which is what keeps the declaration true for every answer.
- **`without_dangling_relations(entities)`** — strips the `[""]` placeholder `build_entities_from_data` leaves in a relation path when a field is null for some items and an object for others; an empty string there makes a JSON dataset write fail.
- **`get_dict(entities)`** — iterator that flattens `Entities` into per-entity dicts keyed by schema path.

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