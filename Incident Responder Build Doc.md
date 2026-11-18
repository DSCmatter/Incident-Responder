# Incident Responder: Build Doc

Nov 18, 2026 · @Vasant Mogia

## Overview

Build a multi-agent incident responder on Google ADK that triages alerts, diagnoses root cause from logs, metrics and deploys, verifies its own evidence, proposes a fix, and waits for human approval. It runs on free tiers and is scored by replaying injected incidents.

Why it is resume-worthy: it matches the JD (multi-agent patterns, RAG, evals, tracing, cost metrics, secure tool access) and has an objective score, so every resume bullet carries a number.

**Target metrics (set real targets after the first baseline run):**

- Root-cause accuracy of at least 70% on 30 replayed incidents.
- Citation faithfulness: every claim in the root-cause report cites a log line, metric, deploy or runbook.
- p95 end-to-end latency under 60 seconds; cost per incident tracked per run.
- Zero fix actions executed without human approval.

## Scope and stages

Build in four stages so a working demo exists after each one. Stop at whichever stage is solid by your deadline.

1. **Stage 1:** plain loop (triage, diagnosis, fix proposal, human approval) on one demo app.
2. **Stage 2:** RAG over runbooks and past incidents.
3. **Stage 3:** evidence verifier and critic loop.
4. **Stage 4:** tracing, cost metrics, eval CI, Cloud Run deploy.

**Non-goals:** no access to real production systems, no fix executed without approval, no multi-cloud, no polished UI (a CLI or one simple web page is enough).

## Architecture

&#91;embedded content: agent architecture · 3 patterns\]

The supervisor routes each incident through delegated sub-agents (triage, diagnosis); diagnosis calls read-only tools and the evidence verifier as a tool; the fix and critic loop until the critic approves or 2 rounds pass, then a human decides.

## Agent specs

A supervisor (root) agent delegates to five specialists and owns state, loop caps and the approval gate. Every agent returns a typed Pydantic object, not free text. Check the current ADK docs for exact class names (LLM agent, sequential, loop); the loop is what implements the critic retry.

| Agent | Job | Tools | Output |
| --- | --- | --- | --- |
| Supervisor | Routes work, keeps run state, caps loops, enforces approval | none (delegates) | Final incident report |
| Triage | Classifies severity and affected service from the alert | alert payload, service map | Triage: service, severity, areas to check |
| Diagnosis (ReAct) | Queries evidence in a loop until a root cause is supported | query\_logs, query\_metrics, list\_recent\_deploys, search\_runbooks | Findings: root cause plus evidence ids |
| Evidence verifier | Checks every claim cites real evidence; rejects unsupported claims | read-only fetch by evidence id | Verified and rejected claims |
| Fix | Proposes a rollback, config change or patch with a rollback plan | get\_deploy, diff, runbook lookup | FixProposal: action, params, risk, rollback |
| Critic | Challenges the fix against verified evidence and blast radius | read-only | Approve or revise with reasons (max 2 loops) |

## Design patterns

Three ADK patterns are used on purpose, each where it fits best. Check the current ADK docs for the exact loop-exit and agent-as-tool APIs.

| Pattern | Where | Why | Stops when |
| --- | --- | --- | --- |
| Loop (review and critique) | Fix agent generates, critic reviews | The proposal corrects itself before a human sees it | Critic approves (rollback plan present, blast radius low, every claim cited) or 2 rounds pass, then escalate to a human |
| Coordinator (dynamic routing) | Supervisor routes to triage, diagnosis and the fix loop | Known incidents skip deep diagnosis; complex ones split into log, metric and deploy checks | Supervisor has a final report or hits its step cap |
| Agent as tool | Evidence verifier, and any stateless check such as a risk scorer | A stateless call returns a verdict; the caller keeps control and the audit trail stays in one place | The single call returns |

**Delegate or tool?** Delegate to a sub-agent when it needs its own multi-step reasoning and state (triage, diagnosis, fix). Wrap it as a tool when it is a stateless check whose result you want back in your own context (verifier). A delegated agent takes over the turn; a tool cannot wander off.

**Extra ablation for the README:** compare 1 critic round vs up to 2, and verifier as tool vs no verifier, and report accuracy and cost for each.

## Demo environment and fault injection

Do not pay for real infrastructure. Run a small fake service stack locally and break it on purpose, so you get real logs, metrics and deploy records with known answers.

- **Stack:** docker-compose with three small services (API, worker, database). Start with JSON log files and synthetic metric files; add Prometheus and Loki only if time allows.
- **Fault scenarios (start with 5):** bad deploy (broken env var), memory leak, slow query from a missing index, dependency timeout, disk full. Later: config typo, noisy-neighbour CPU, expired certificate.
- **Each scenario ships:** an alert JSON, logs, metric series, a deploy history entry, and a ground-truth label (root cause and the correct fix).
- **Extra material:** public postmortems and open log datasets (for example Loghub) can seed more scenarios and runbook text.
- **Hard cases to include:** a red herring (a harmless recent deploy), a missing log, and a log line containing a prompt-injection string.

## Data layer and RAG

The diagnosis agent searches past knowledge as one of its tools, next to the live log and metric queries.

- **Corpus:** 15 to 20 runbooks you write in Markdown, postmortems of your own injected incidents, and a few public postmortems.
- **Chunking:** split by heading; attach metadata (service, severity, date, source).
- **Index:** Postgres with pgvector, plus Postgres full-text search for keywords.
- **Retrieval:** hybrid search (keyword plus vector) merged with reciprocal rank fusion, then an optional rerank of the top results.
- **Embeddings:** a Gemini embedding model on the free tier, or a local sentence-transformers model if you hit rate limits.
- **Leakage rule:** when replaying an incident, exclude that incident's own postmortem from the index, or the eval is meaningless.
- **Metric:** recall@k, meaning how often the right runbook or similar incident appears in the top k.

## State, safety and approval

- **Read vs write tools:** querying logs, metrics and deploys is read-only. Rollback, restart and config change are write tools and run as dry-run only until a human approves.
- **Approval gate:** the run pauses with the proposed action, evidence and rollback plan; a person approves or rejects in the CLI or a simple page. Every decision is logged.
- **Guard layer:** a small guard wrapper around every tool call, built in this repo: per-agent tool allowlist, argument validation, and output scanning.
- **Untrusted input:** treat logs and alert text as untrusted. Include an eval case where a log line tries to instruct the agent, and assert it is ignored.
- **State:** persist run state (SQLite or Postgres) with checkpoints so a run can pause for approval, resume after a crash, and be replayed.
- **Limits:** cap loop counts, tool calls per run and wall-clock time, so a bad run cannot burn your free-tier quota.

## Observability and cost metrics

- **Tracing:** OpenTelemetry spans for every agent step and tool call, with attributes for model, input and output tokens, latency, tokens per second, estimated cost and cache hit.
- **Backends:** local Jaeger or self-hosted Langfuse; Cloud Trace is an option on GCP.
- **Run replay:** store every run's trace and tool results so failed runs can be replayed and inspected.
- **Dashboard numbers:** cost per incident, p50 and p95 latency, tool calls per incident, loop count, failure reasons.
- **Optimization experiments (record before and after for each):** route easy steps (triage, verifier) to a smaller model; trim context passed between agents; cache repeated tool results; cap ReAct steps.
- **Output:** one results table in the README showing accuracy, latency and cost before and after optimization.

## Evals

The eval harness is what makes the project credible. Build it in week 2, not at the end.

- **Dataset:** start with 10 incidents, grow to 30. Each has alert, logs, metrics, deploys, ground-truth root cause and expected fix class.
- **Metrics:**
  - Root-cause accuracy (match on service and cause category, with an LLM judge for free-text agreement).
  - Citation faithfulness (every cited evidence id exists and supports the claim; check this with code, not only the model).
  - Fix correctness (action class matches the expected one).
  - Unsafe action rate (must be 0).
  - Latency and cost per incident.
- **Runs:** repeat each incident 3 times and report the spread, since LLM runs vary.
- **CI:** GitHub Actions runs a small subset on every change with cached model responses, and fails if accuracy drops below the last recorded baseline.
- **Ablations to report:** with and without RAG, with and without the verifier. These make strong resume numbers.

## Free-tier stack and deployment

Free-tier limits change, so check the current terms before relying on any row.

| Need | Choice | Note |
| --- | --- | --- |
| LLM | Gemini API free tier (AI Studio), Flash-class model | Rate limited; prompts may be used to improve models, so use only synthetic data |
| Agent framework | ADK (open source), runs locally | Optional LangGraph comparison note |
| Database and vectors | Local Postgres with pgvector in Docker, or a free Neon or Supabase tier | Same code either way |
| Tracing | Local Jaeger or self-hosted Langfuse | Cloud Trace if you deploy on GCP |
| Deployment | Cloud Run, scale to zero, low max instances | Set a budget alert and quota cap before deploying |
| CI | GitHub Actions | Cache model responses to save quota |

Deploy last. A local docker-compose demo plus a recorded run is enough until the core works.

## Repo structure

```
incident-responder/
  agents/          # supervisor, triage, diagnosis, verifier, fix, critic
  tools/           # query_logs, query_metrics, deploys, runbook search
  guard/           # firewall policy, allowlists, output scanning
  rag/             # ingest, chunking, hybrid search
  state/           # run state, checkpoints, approval records
  telemetry/       # OpenTelemetry setup, cost and token accounting
  demo_env/        # docker-compose services, fault injectors
  evals/
    incidents/     # 30 scenarios with ground truth
    run_evals.py   # metrics, repeats, JSON report
  docs/            # architecture diagram, results, write-up
  README.md
```

## Build plan

Five weeks at a steady pace; compress by dropping stage 3 or 4 if you are short on time. Each step ends with a gate you can demo.

1. **Week 1:** demo app, 5 fault scenarios with ground truth, ADK skeleton with triage and diagnosis using log, metric and deploy tools. *Gate: solves 3 scenarios end to end.*
2. **Week 2:** fix agent, approval gate, persisted state, eval harness v1 on 10 incidents. *Gate: a baseline accuracy number exists.*
3. **Week 3:** RAG over runbooks and postmortems, evidence verifier, critic loop, grow to 30 incidents. *Gate: RAG and verifier ablations measured.*
4. **Week 4:** OpenTelemetry tracing, cost and latency metrics, optimization experiments, firewall guard, prompt-injection test. *Gate: before and after cost table.*
5. **Week 5:** Cloud Run deploy, CI eval gate, README with architecture diagram, 2-minute demo video, short write-up. *Gate: someone else can run it from the README.*

## Resume bullets and README checklist

Fill the numbers only with results you measured. Do not write a bullet you cannot back with a run.

**Bullet templates**

- Built a multi-agent incident responder on Google ADK (triage, ReAct diagnosis, evidence verifier, fix, critic) with human-approval gating; reached X% root-cause accuracy on Y replayed incidents.
- Added hybrid RAG (pgvector plus full-text) over runbooks and past incidents, lifting accuracy from A% to B% in ablation.
- Instrumented agents with OpenTelemetry; cut cost per incident by C% and p95 latency by D% through model routing and context trimming.
- Guarded tool access with a zero-trust policy layer; 0 unsafe actions and prompt-injection cases blocked in eval.

**README checklist**

- [ ] One-paragraph problem statement and a demo GIF or video
- [ ] Architecture diagram and agent table
- [ ] Results table: accuracy, citation faithfulness, latency, cost, with and without RAG and verifier
- [ ] How to run locally in under 10 minutes
- [ ] Failure analysis: three runs that went wrong and what you changed
- [ ] Notes on what you would build next, and what the platform friction was (feature-request style)
