# Incident Responder

<!-- TODO: one-sentence hook with your best measured number once you have it. Example: "A multi-agent incident responder that finds the root cause in X% of replayed incidents and never acts without human approval." -->

A multi-agent cloud incident responder built on Google ADK. It triages an alert, investigates logs, metrics and deploys, checks its own evidence, proposes a fix, and waits for human approval. Built and evaluated on free tiers only.

<!-- TODO: demo GIF or video link -->

## Status

Work in progress. Done: repo tooling, the LLM client, backend smoke tests, schemas and the evidence store, fixtures S01 to S03, read-only tools, and the eval harness (T01 to T07). Built but not yet past its gate: the triage and diagnosis agents (T08), which find the right root cause but exceed the 60-second per-incident limit on today's free backends. Not started: the fix path, supervisor, RAG, verifier, critic, guard layer and telemetry. Task-by-task status is in [PLAN.md](PLAN.md#3-ordered-backlog).

## Why

On-call engineers lose time collecting evidence and second-guessing fixes. This project shows an agent system that cites its evidence, rejects its own unsupported claims, and stays inside safe limits.

## How it works

<!-- TODO: insert the architecture diagram from docs/architecture.png -->

| Agent | Pattern | Job |
| --- | --- | --- |
| Supervisor | Coordinator | Routes the incident, keeps state, caps loops |
| Triage | Delegated | Classifies severity and likely service |
| Diagnosis | Delegated, ReAct | Queries logs, metrics, deploys, runbooks |
| Evidence verifier | Agent as tool | Rejects claims without real supporting evidence |
| Fix and Critic | Loop | Propose and review a fix, max 2 rounds |
| Human approval | Gate | Required before any write action |

Details: [DESIGN.md](docs/DESIGN.md).

## Results

<!-- TODO: paste the table from RESULTS.md after your first full run -->

| Setup | Root-cause accuracy | Citation faithfulness | Cost per incident | p95 latency |
| --- | --- | --- | --- | --- |
| TBD | TBD | TBD | TBD | TBD |

Full numbers, ablations and failure analysis: [RESULTS.md](docs/RESULTS.md).

## Run it

Requirements: Python 3.11 or newer, Docker. No paid keys needed.

```
make setup
cp .env.example .env        # add a free Gemini API key; optional OpenRouter key
make up
make run INCIDENT=S01      # prints the report; pauses before any change
make approve RUN=<run id> BY=<your name>
make eval SPLIT=dev
make trace
```

<!-- TODO: confirm someone else can do this in under 10 minutes -->

## Free-tier design

All model calls go through one client with caching, a daily call budget and a fallback chain (local Ollama, OpenRouter free models, Gemini free tier). Tests run on cached responses. See [PLAN.md](PLAN.md).

## Safety

- Read-only tools by default; write tools are dry-run until a human approves.
- Logs and alerts are treated as untrusted input; a prompt-injection case is part of the eval set.
- Zero unapproved actions across all evaluated runs <!-- TODO: confirm from results -->.

## Evaluation

30 synthetic incidents (12 fault types with variants, plus 6 hard cases) with ground truth. Dev and held-out splits are reported separately. See [SCENARIOS.md](docs/SCENARIOS.md).

## Limitations

<!-- TODO: be honest. Examples: synthetic incidents only; small eval set; free-tier models vary run to run; no real cloud integration. -->

## What I would build next

<!-- TODO: 2 or 3 items, including platform friction hit while building (feature-request style). -->
