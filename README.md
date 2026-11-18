# Incident Responder

<!-- TODO: one-sentence hook with your best measured number once you have it. Example: "A multi-agent incident responder that finds the root cause in X% of replayed incidents and never acts without human approval." -->

A multi-agent cloud incident responder built on Google ADK. It triages an alert, investigates logs, metrics and deploys, checks its own evidence, proposes a fix, and waits for human approval. Built and evaluated on free tiers only.

<!-- TODO: demo GIF or video link -->

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
make run INCIDENT=S01
make eval SPLIT=dev
make trace
```

<!-- TODO: confirm someone else can do this in under 10 minutes -->

## Free-tier design

All model calls go through one client with caching, a daily call budget and a fallback chain (Gemini free tier, OpenRouter free models, local Ollama). Tests run on cached responses. See [PLAN.md](PLAN.md).

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
