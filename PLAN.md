# PLAN.md

Build order, free-tier budget, and gates for the incident responder. Companion docs: [DESIGN.md](docs/DESIGN.md) (contracts), [SCENARIOS.md](docs/SCENARIOS.md) (eval data), [AGENTS.md](AGENTS.md) (rules for coding tools), [RESULTS.md](docs/RESULTS.md), [DEMO.md](docs/DEMO.md), [README.md](README.md). Longer design write-up: [Build doc](https://claude.ai/artifact/EGugGQMP1Qpj2rv19Cc8Kk).

## 1. Order of attack

1. **Riskiest first.** Free-tier quota and tool-calling quality decide everything, so test the model backends before writing agents.
2. **Measure before you build.** Write the eval harness before the agents, so every change gets a number.
3. **One vertical slice, then widen.** Get one incident running end to end (alert to proposed fix), then add scenarios.
4. **Add one capability at a time and re-measure.** RAG, verifier, critic loop: each is an ablation row in RESULTS.md.
5. **Polish last.** Telemetry, guard hardening, docs and demo come after the core scores exist.

## 2. Start here (first 90 minutes)

- [x] Create the repo; copy in the seven docs
- [x] T01: Makefile, config, `.env.example`, docker-compose with Postgres
- [ ] Get a Gemini API key; read your real daily quota in AI Studio and write it in `config.yaml` (not done: no key yet)
- [x] Install Ollama and pull a 7B to 8B instruct model that supports tool calling
- [x] Optional: OpenRouter key; pick 2 or 3 `:free` models (Nemotron Ultra, Nemotron Super, Ernie 5.5 Flash)
- [x] T03: smoke test "hello plus one tool call plus one structured output" on each backend; record which pass

## 3. Ordered backlog

Size: S under 2 hours, M half a day, L a day or more. Do tasks in order; a task needs the ones before it unless noted.

**Status on 2026-11-21.** T01 to T07 are done. T03 chose the backends: local Ollama (qwen2.5:7b-instruct) is primary, OpenRouter (Nemotron Ultra) is the fallback, and Gemini is unused until a key exists. T08's agents run end to end, but the gate is not met: Nemotron Ultra found S01's root cause in 61.2 s against the 60 s cap, and local qwen2.5:7b on a GTX 1650 timed out on S02 and S03 after 3 calls. Passing needs a faster backend, a higher `run_timeout_seconds`, or context trimming (T21) moved earlier. T09 onward waits on that decision.

### Week 1: foundation

| ID | Task | Size | Done when | Status |
| --- | --- | --- | --- | --- |
| T01 | Repo tooling: Makefile, ruff, pytest, config, docker-compose | S | `make setup`, `make lint`, `make test` run | Done |
| T02 | `llm/client.py`: cache, daily budget, fallback chain, record and replay modes, per-call log | M | Same call twice costs one live call; budget switch tested with a stub | Done |
| T03 | Backend smoke tests: tool calling and structured output on Gemini, OpenRouter free, Ollama | S | Table of which backends pass; primary chosen by the decision rule in section 4 | Done (see RESULTS.md) |
| T04 | Pydantic schemas and evidence store from DESIGN.md | S | Schemas validate sample payloads; store enforces "cite only existing ids" | Done |
| T05 | Fixture generator and S01 to S03 fixtures | M | Three incidents with logs, metrics, deploys, truth; manually solvable | Done |
| T06 | Read-only tools over fixtures (logs, metrics, deploys, diffs) | M | Tools return evidence-id-tagged results | Done |
| T07 | Eval harness skeleton: loader, scoring per SCENARIOS.md, JSON results | M | `make eval SPLIT=dev` runs a stub agent and prints a score table | Done |
| T08 | Triage and diagnosis (ReAct) agents, no RAG, no verifier | L | **Gate: solves S01 to S03 end to end** | Built; **gate not met** (60 s cap, see status note above) |

### Week 2: fix path and baseline

| ID | Task | Size | Done when | Status |
| --- | --- | --- | --- | --- |
| T09 | Fix agent, write tools (dry-run), approval gate, persisted run state | M | A run pauses at `AWAITING_APPROVAL` and resumes after approval | Not started |
| T10 | Supervisor (fixed routing for now) and `make run INCIDENT=...` CLI | M | One command prints the report | Not started |
| T11 | Fixtures for the rest of dev: S04 to S08, H1, H3 | M | 10 dev incidents, each manually checked | Not started |
| T12 | **Baseline eval:** dev set, 3 repeats, plain loop | S | **Gate: baseline numbers in RESULTS.md** | Not started |

### Week 3: the capabilities

| ID | Task | Size | Done when | Status |
| --- | --- | --- | --- | --- |
| T13 | RAG: runbooks and postmortems corpus, ingest, hybrid search, `search_runbooks` tool, recall@k check | L | Right runbook in top 5 for most dev incidents; own postmortem excluded on replay | Not started |
| T14 | Evidence verifier as a tool (code checks, then model check) | M | Fabricated quote rejected in a unit test; claims without ids rejected | Not started |
| T15 | Critic and the fix loop with exit conditions | M | Loop stops on approval or after 2 rounds, then escalates | Not started |
| T16 | Supervisor dynamic routing (fast path vs full diagnosis) | S | Known-runbook incidents use fewer calls | Not started |
| T17 | Heldout fixtures: remaining 16 variants and H2, H4, H5, H6 | L | 30 incidents total; do not tune on heldout | Not started |
| T18 | Ablation runs: no RAG, no verifier, 1 vs 2 critic rounds | M | **Gate: ablation table in RESULTS.md** | Not started |

### Week 4: observability and safety

| ID | Task | Size | Done when | Status |
| --- | --- | --- | --- | --- |
| T19 | OpenTelemetry spans and cost-equivalent accounting; local trace UI | M | Trace shows agents, tools, tokens, tokens per second, cost | Not started |
| T20 | Guard layer: allowlists, validation, output scanning, approval check; injection test | M | H3 passes; unapproved write call is refused in a test | Not started |
| T21 | Optimization experiments: model routing, context trimming, tool-result caching | M | **Gate: before and after cost and latency table** | Not started |
| T22 | CI: lint, tests, replay-mode eval on a small subset, accuracy regression gate | S | CI fails if accuracy drops below the recorded baseline | Not started |

### Week 5: ship

| ID | Task | Size | Done when | Status |
| --- | --- | --- | --- | --- |
| T23 | README, architecture diagram, RESULTS.md final, failure analysis | M | Someone else runs it from the README in 10 minutes | Not started |
| T24 | Demo video per DEMO.md | S | 2 minutes, no secrets visible | Not started |
| T25 | Optional: Cloud Run deploy with budget alert | M | Only if you have a billing account and want it | Not started |

## 4. Free-tier ground rules

Checked 2026-11-18. Limits change often; re-read your AI Studio console each week.

| Resource | Free allowance | Use |
| --- | --- | --- |
| Gemini API (AI Studio) | Not fixed. One 2026 source lists 20 requests/day for Flash models and 500/day for Flash-Lite; Google does not publish per-model numbers, so read yours in the console | Primary only if quota is 250/day or more |
| OpenRouter free models | 20 requests/minute; 50/day (1,000/day only after buying $10 of credits, which is not free). Per account, not per model | Second fallback; test tool calling per model |
| Ollama (local) | Free, limited by your laptop | Dev loop, bulk evals, last fallback |
| Embeddings | Local sentence-transformers | Keeps embeddings off API quota |
| Postgres and pgvector | Local Docker | Default |
| Tracing | Local Jaeger or self-hosted Langfuse | No hosted account |
| CI | GitHub Actions, free for public repos | Replay mode only |
| Cloud Run | 2M requests, 180k vCPU-seconds, 360k GiB-seconds per month; needs a billing account | Optional last step |

Rules: no paid keys or cards for core work; synthetic data only; every LLM call through `llm/client.py`; hard stops of 12 LLM calls, 6 ReAct steps, 2 critic rounds and 60 seconds per incident.

### Call budget

One incident is about 11 calls (triage 1, diagnosis up to 6, verifier 1, fix 1, critic up to 2).

| Activity | Calls |
| --- | --- |
| Dev iterations | Local model and cache; no Gemini quota |
| Baseline: 10 incidents x 3 repeats | about 330 |
| Full run: 30 incidents x 1 | about 330 |
| Ablations: 2 runs of 30 | about 660 |
| Headline total | about 1,320 (about 3 days at 500/day; about 26 days at OpenRouter's 50/day; about 66 days at 20/day) |

**Decision rule (T03):** Gemini quota of 250/day or more makes Gemini primary. Lower means a local model is primary for all evals, OpenRouter is a fallback, and Gemini is used for the final demo run only. If you use LiteLLM for non-Gemini backends, pin a current version (ADK's docs require 1.84 or newer) and keep keys out of the repo.

## 5. If time runs short

Cut in this order: Cloud Run (T25), optimization experiments (T21), heldout hard cases H5 and H6, guard extras beyond the injection test. Never cut: eval harness (T07), baseline (T12), verifier (T14), README results.

Rough LoC: about 4,000 Python for the full plan; about 2,500 if you stop after week 3.

## 6. Risks and fallbacks

| Risk | Fallback |
| --- | --- |
| Gemini daily quota too low | Local model primary; OpenRouter second; cache; batch evals across days |
| Local model weak at tool calling | JSON-schema output with a parser instead of native tool calls; smaller tool set |
| OpenRouter free model disappears or returns 429 | Config lists 2 or 3 fallbacks; wrapper falls through to local |
| Eval variance hides real gains | Repeat the dev core set 3 times; report the spread |
| Fixtures too easy or unsolvable | Manually solve each new fixture from its evidence before adding it |
| Scope creep | Follow the order in section 3; each capability must produce an ablation row or it waits |

## 7. Done means

- [ ] 30 incidents with ground truth; one command runs them
- [ ] RESULTS.md filled from real runs: main table, ablations, cost and latency, three failure analyses
- [ ] Zero unapproved actions across all evaluated runs; injection case blocked
- [ ] Trace view and cost per incident visible locally
- [ ] README: problem, diagram, results, 10-minute run instructions
- [ ] Demo video linked

Resume bullets, once numbers exist (fill only from measured runs):

- Built a multi-agent incident responder on Google ADK (coordinator, ReAct diagnosis, evidence verifier as a tool, fix and critic loop) with human-approval gating; X% root-cause accuracy on Y replayed incidents.
- Added hybrid RAG (pgvector plus full-text) over runbooks and past incidents, lifting accuracy from A% to B% in ablation.
- Instrumented agents with OpenTelemetry; cut cost per incident by C% and p95 latency by D% through model routing and context trimming, entirely on free tiers.

## Sources (checked 2026-11-18)

- Cloud Run pricing: https://cloud.google.com/run/pricing
- Gemini API free-tier limits (third-party summaries; confirm in AI Studio): https://www.scriptbyai.com/gemini-api-free-tier-limits/ and https://benchlm.ai/md/free-tier/google-ai-studio.md
- OpenRouter free-model limits: https://openrouter.ai/docs/api/reference/limits.md and https://benchlm.ai/md/free-tier/openrouter.md
- ADK with OpenRouter via LiteLlm: https://www.bitdoze.com/google-adk-openrouter-models
