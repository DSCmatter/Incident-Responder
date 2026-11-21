# DESIGN.md

Contracts for the incident responder: data schemas, tool signatures, agent behavior, state, and limits. Build against this file. If code and this file disagree, fix one of them in the same commit.

Verify ADK class and method names against the current ADK docs before coding; this file names the roles, not the exact API.

## 1. Flow

```
Alert -> Supervisor (coordinator)
           |-- delegates --> Triage
           |-- delegates --> Diagnosis (ReAct) --calls--> read-only tools, runbook RAG
           |                       \--calls (as tool)--> Evidence verifier
           |-- delegates --> Fix <-> Critic (loop, max 2 rounds)
           \-- Approval gate (human) -> dry-run or execute in demo env -> Report
```

Patterns: coordinator (delegation), agent as tool (verifier), loop (fix and critic). Delegated agents own their turn and keep state; the verifier is stateless and returns a result to its caller.

## 2. Evidence store

Every tool result is saved to a per-run evidence store and given an id. Agents cite ids, never raw text alone.

| Field | Meaning |
| --- | --- |
| `id` | `ev_<kind>_<n>` minted by the store (`ev_log_3`, `ev_metric_1`, `ev_deploy_2`, `ev_runbook_4`) |
| `kind` | `log`, `metric`, `deploy`, `runbook` |
| `source` | file or document path plus line or section |
| `content` | the exact text or summarized numbers returned to the agent |
| `query` | the tool call that produced it |

Rule: an agent can only cite an id that exists in the store for the current run.

## 3. Schemas (Pydantic)

```python
from enum import Enum
from pydantic import BaseModel, Field

class Severity(str, Enum):
    sev1 = "sev1"; sev2 = "sev2"; sev3 = "sev3"

class RootCause(str, Enum):
    bad_deploy = "bad_deploy"
    resource_exhaustion = "resource_exhaustion"
    slow_query = "slow_query"
    dependency_failure = "dependency_failure"
    disk_full = "disk_full"
    misconfiguration = "misconfiguration"
    capacity = "capacity"
    cert_expiry = "cert_expiry"
    network_dns = "network_dns"
    unknown = "unknown"

class FixClass(str, Enum):
    rollback_deploy = "rollback_deploy"
    restart_service = "restart_service"
    config_change = "config_change"
    scale_out = "scale_out"
    add_index = "add_index"
    rotate_cert = "rotate_cert"
    free_disk = "free_disk"
    escalate_human = "escalate_human"

class Triage(BaseModel):
    service: str                       # most likely affected service
    severity: Severity
    areas_to_check: list[str]          # e.g. ["recent deploys", "db latency"]
    known_pattern: bool                # true if a runbook strongly matches (routing hint)

class Claim(BaseModel):
    text: str                          # one factual statement
    evidence_ids: list[str] = Field(min_length=1)
    quote: str                         # verbatim snippet from a cited evidence item

class Findings(BaseModel):
    root_cause: RootCause
    service: str
    summary: str
    confidence: float                  # 0..1, self-reported; not used for scoring
    claims: list[Claim]

class ClaimVerdict(BaseModel):
    claim_index: int
    supported: bool
    reason: str                        # e.g. "quote not found in ev_log_3"

class Verification(BaseModel):
    all_supported: bool
    verdicts: list[ClaimVerdict]

class FixProposal(BaseModel):
    action: FixClass
    target: str                        # service, deploy id, or config key
    params: dict[str, str] = {}
    rationale: str
    risk: Severity                     # reuse low/med/high semantics: sev3=low, sev1=high
    blast_radius: str
    rollback_plan: str                 # required unless action is escalate_human
    supported_by: list[int]            # indexes of verified claims

class CriticVerdict(BaseModel):
    approved: bool
    issues: list[str]
    required_changes: list[str]

class Approval(BaseModel):
    run_id: str
    decision: str                      # "approved" | "rejected" | "edited"
    decided_by: str
    note: str = ""
```

## 4. Tools

Read-only (any delegated agent may call, subject to guard allowlist):

| Tool | Signature | Returns |
| --- | --- | --- |
| `query_logs` | `(service, start, end, pattern=None, limit=50)` | log lines, each batch saved as one evidence item |
| `query_metrics` | `(service, metric, start, end, step)` | summarized series (min, max, trend, spikes) as one evidence item |
| `list_recent_deploys` | `(service=None, hours=24)` | deploy records with ids and times |
| `get_deploy_diff` | `(deploy_id)` | changed files or config keys |
| `search_runbooks` | `(query, service=None, k=5)` | top chunks with source and score |

Write tools (dry-run by default; execute only after an `Approval` record exists):

| Tool | Signature |
| --- | --- |
| `rollback_deploy` | `(deploy_id)` |
| `restart_service` | `(service)` |
| `apply_config_change` | `(service, key, value)` |
| `scale_service` | `(service, replicas)` |
| `rotate_certificate` | `(service)` |

Write tools take effect only on the fake demo stack. The guard layer refuses any write call without a matching approval for the same run, action, and target.

## 5. Agents

| Agent | Mode | Tools | Output | Stop |
| --- | --- | --- | --- | --- |
| Supervisor | coordinator | none | final report | report built, or step cap |
| Triage | delegated | alert payload, service map | `Triage` | one call |
| Diagnosis | delegated, ReAct | read-only tools, `search_runbooks`, verifier (as tool) | `Findings` | all claims verified, or 6 steps |
| Evidence verifier | tool | evidence store (read-only) | `Verification` | one call |
| Fix | delegated, in loop | `get_deploy_diff`, `search_runbooks` | `FixProposal` | per loop round |
| Critic | in loop | evidence store, findings | `CriticVerdict` | approve or round limit |

ADK wiring: every agent is an ADK `LlmAgent` whose model is `ClientModel` in `agents/adk.py`, so each call still goes through `llm/client.py`. That module is the only one allowed to import `google.genai` types (ruff TID251 enforces it). An agent answers only by calling its `submit_<schema>` tool. The tool validates the arguments against the schema plus agent checks (known service, cited ids exist in the store), returns the reason on a rejection, and ends the agent on the second rejection with no result, which the run reports as `FAILED`. Prompts live in `agents/prompts/<agent>.md` and start with `version: <id>`, which is logged with every call.

### Supervisor routing

1. Run Triage.
2. If `known_pattern` is true and the top runbook score is at or above the configured threshold, run a short diagnosis (max 3 steps) guided by that runbook. Otherwise run full diagnosis (max 6 steps).
3. If verification fails, send the rejected claims back to Diagnosis once. If still unsupported, mark the run `ESCALATED` with the unverified findings attached.
4. Run the fix and critic loop. If the critic does not approve after 2 rounds, mark `ESCALATED`.
5. Move to `AWAITING_APPROVAL`. Never call a write tool before an `Approval` exists.

### Verifier checks

Code first, model second:

1. Every claim has at least one evidence id, and every id exists in the store.
2. The claim's `quote` is a substring of the cited evidence `content` (exact match after whitespace normalization). This is plain code, no model.
3. A model judges whether the quote supports the claim text. It sees only the claim, quote, and evidence, not the diagnosis reasoning.

A claim fails if any step fails. Step 2 catches fabricated citations; step 3 catches real quotes that do not support the claim.

### Critic checklist

Approve only if all hold: every claim in `supported_by` is verified; a rollback plan exists (unless escalating); blast radius is named; the action class fits the root cause; no write action is proposed outside the demo stack's allowed targets. Otherwise return `required_changes`.

## 6. Run state

Persist to SQLite (or Postgres) so a run can pause for approval and resume.

States: `NEW`, `TRIAGED`, `DIAGNOSED`, `VERIFIED`, `FIX_PROPOSED`, `CRITIQUED`, `AWAITING_APPROVAL`, `APPROVED`, `REJECTED`, `EXECUTED`, `DONE`, `ESCALATED`, `FAILED`.

Table `runs`: `run_id`, `incident_id`, `state`, `payloads` (JSON per stage), `llm_calls`, `tokens_in`, `tokens_out`, `cost_usd_equiv`, `started_at`, `updated_at`. Table `evidence`: `run_id`, `id`, `kind`, `source`, `content`, `query`. Table `approvals`: the `Approval` fields plus `ts`.

## 7. LLM client (single entry point)

All model calls go through `llm/client.py`. No agent or tool imports a provider SDK directly.

- **Cache:** key is a hash of the system prompt, messages, tool schemas, temperature and output limit. It excludes the model and backend on purpose, so a transcript recorded on one backend replays on another and CI can replay without a key. A cache hit costs no quota, is logged, and still counts as a turn.
- **Budget:** derived from the ledger, never stored. Each call reserves a row in SQLite before the request, and spend today is `SUM(quota_spent)` for that backend, so a crash wastes at most one call. At the limit, move to the next backend; when every backend is at its limit, raise `QuotaExhausted`.
- **Fallback chain:** local Ollama, OpenRouter free models, Gemini free tier, chosen by the T03 smoke test (see RESULTS.md). Configured in `config.yaml`.
- **Per-call log:** model, tokens in and out, latency, tokens per second, cost-equivalent, cache hit, agent name.
- **Modes:** `live`, `record` (call and cache), `replay` (cache only; a miss is an error). CI uses `replay`.
- **Run cap:** once a run has `max_llm_calls_per_run` turns (hits included), the client raises `CallCapReached` before calling out, and the run is `ESCALATED`.

## 8. Guard layer

- Per-agent tool allowlist.
- Argument validation against schemas; reject unknown services and ids.
- Write-tool rule: needs a matching `Approval`.
- Output scanning: strip or flag instruction-like text in logs and alerts before it reaches a model, and wrap log content in a clearly marked untrusted block.
- Every allow or deny decision is logged with run id.

## 9. Telemetry

One OpenTelemetry span per agent step and tool call. Attributes: `agent.name`, `tool.name`, `llm.model`, `llm.tokens_in`, `llm.tokens_out`, `llm.latency_ms`, `llm.tokens_per_sec`, `llm.cost_usd_equiv`, `llm.cache_hit`, `run.id`, `incident.id`. Export to local Jaeger or Langfuse. Cost-equivalent uses a price table in config even on free tiers, so optimization results are comparable.

## 10. Config (defaults)

```yaml
limits:
  max_llm_calls_per_run: 12
  max_react_steps: 6
  max_react_steps_fast_path: 3
  max_critic_rounds: 2
  run_timeout_seconds: 60
routing:
  runbook_score_threshold: 0.75     # tune on dev split only
llm:
  mode: live                        # live | record | replay
  chain: [ollama, openrouter, gemini]
  daily_budget: {gemini: 200, openrouter: 45, ollama: unlimited}
rag:
  k: 5
  embedding: local-sentence-transformers
```

## 11. Failure handling

| Failure | Behavior |
| --- | --- |
| Model returns invalid schema | Retry once with the validation error; then `FAILED` with raw output saved |
| Tool error or empty result | Record it as evidence ("no logs in window"); agent decides next step |
| Backend 429 or quota | Fall through the chain; log the switch |
| Step, call, or time cap hit | `ESCALATED` with partial findings, never a guess |
| Critic and fix disagree after 2 rounds | `ESCALATED` with both views |
