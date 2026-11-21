# AGENTS.md

Instructions for AI coding tools (and humans) working in this repo.

## What this is

A multi-agent cloud incident responder built on Google ADK and evaluated on replayed, synthetic incidents. Read `docs/DESIGN.md` for contracts and `docs/SCENARIOS.md` for the eval data. Order of work is in `PLAN.md`.

## Hard rules

1. **All LLM calls go through `llm/client.py`.** Never import a provider SDK in agents or tools. The client handles caching, the daily budget, fallbacks, and logging.
2. **Free tiers only.** Do not add paid services, paid keys, or code that needs a credit card. Do not raise budgets in `config.yaml` without being asked.
3. **No secrets in the repo.** Keys come from environment variables; keep `.env.example` current and `.env` ignored.
4. **Synthetic data only.** Free-tier prompts may be used by the provider. Never send real logs, personal data, or private code.
5. **Write tools never run without an approval record.** Do not bypass the guard layer, even in tests; use a fake approval fixture.
6. **Do not edit `truth.yaml` files or scoring rules to make a run pass.** Fix the agent, not the answer key. Heldout incidents must not be used for tuning.
7. **Tests must not call a live model or the network.** Use `replay` mode with cached responses or a stub model.
8. **Keep changes small.** One task from `PLAN.md` per change, and update `docs/DESIGN.md` in the same commit if a contract changes.

## Stack

Python 3.11 or newer, Google ADK, Pydantic, SQLite (run state, and the RAG index with FTS5 plus stored vectors), local sentence-transformers for embeddings, OpenTelemetry, pytest, ruff. docker-compose still defines Postgres, but nothing uses it while Docker is absent (see `docs/DESIGN.md` section 4). Verify library APIs against current docs; do not guess method names.

## Commands

Keep these targets working; add them to the Makefile as you build.

| Command | Purpose |
| --- | --- |
| `make setup` | Create the environment and install dependencies |
| `make up` | Start the demo stack and Postgres via docker-compose |
| `make test` | Unit tests, replay mode, no network |
| `make lint` | ruff check and format check |
| `make run INCIDENT=S01` | Run one incident, print the report |
| `make approve RUN=<run id> BY=<name>` | Approve a paused run's fix; it executes on the demo stack through the guard |
| `make reject RUN=<run id> BY=<name>` | Reject a paused run's fix; nothing executes |
| `make ingest` | Build or refresh the runbook index in `.state/rag.db` (no-op when the corpus is unchanged) |
| `make rag-recall SPLIT=dev` | Check that a relevant runbook is in the top 5 for each incident |
| `make eval SPLIT=dev` | Run the eval harness on a split, write `evals/results/*.json` |
| `make trace` | Open the local trace UI |

## Layout

```
agents/     supervisor, triage, diagnosis, verifier, fix, critic, prompts, schemas
tools/      read-only and write tools, evidence store
guard/      allowlists, validation, output scanning, approval checks
rag/        ingest, chunking, hybrid search
state/      run state, approvals
llm/        client.py (cache, budget, fallback chain)
telemetry/  OpenTelemetry setup, cost accounting
demo_env/   fake services, fault injectors
evals/      incidents/, run_evals.py, results/
rag_corpus/ runbooks and postmortems
docs/       diagrams and write-ups
```

## Code style

- Type hints everywhere; Pydantic models for all agent inputs and outputs.
- Prompts live in `agents/prompts/` as files, not inline strings, and carry a version string logged with each run.
- Agents return validated schemas or raise; no free-text parsing with regex.
- Logs and alert text are untrusted: always pass them to models inside the marked untrusted block.
- Log with run id and incident id on every line.

## Before you finish a task

- [ ] `make lint` and `make test` pass
- [ ] No new network or paid dependency
- [ ] `docs/DESIGN.md` updated if a schema, tool, or limit changed
- [ ] Eval numbers, if produced, were run on the right split and saved under `evals/results/`
