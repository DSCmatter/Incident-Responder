# RESULTS.md

Template. Fill every number from `make eval` output in `evals/results/`; never type a figure you did not measure. Record the date, git commit, model backend, and prompt versions for each run.

## Run log

| Run | Date | Commit | Backend | Split | Repeats | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| baseline | TBD | TBD | TBD | dev | 3 | Plain loop, no RAG, no verifier |

## Main results

| Setup | Root-cause accuracy | Fix correct | Citation faithfulness | Evidence recall | Unsafe actions | LLM calls per incident | Cost per incident (equiv.) | p95 latency |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Baseline (no RAG, no verifier) | TBD | TBD | TBD | TBD | 0 | TBD | TBD | TBD |
| + RAG | TBD | TBD | TBD | TBD | 0 | TBD | TBD | TBD |
| + RAG + verifier | TBD | TBD | TBD | TBD | 0 | TBD | TBD | TBD |
| + critic loop (full system) | TBD | TBD | TBD | TBD | 0 | TBD | TBD | TBD |

Report dev and held-out separately. Core-set rows include the spread over 3 repeats.

## Ablations

| Question | Setup A | Setup B | Result |
| --- | --- | --- | --- |
| Does RAG help? | no RAG | RAG | TBD |
| Does the verifier help? | no verifier | verifier as tool | TBD |
| Critic rounds | 1 | up to 2 | TBD |
| Small model for triage and verifier | single model | routed | TBD |

## Cost and latency optimization

| Change | Cost per incident before | after | p95 latency before | after | Accuracy change |
| --- | --- | --- | --- | --- | --- |
| Model routing | TBD | TBD | TBD | TBD | TBD |
| Context trimming | TBD | TBD | TBD | TBD | TBD |
| Tool-result caching | TBD | TBD | TBD | TBD | TBD |

## Failure analysis

Pick three runs that went wrong. For each:

1. **Incident and run id:**
2. **What the system did:**
3. **Why it was wrong (trace evidence):**
4. **What changed afterward, and the effect on dev score:**

## Threats to validity

- Synthetic incidents may be easier or more regular than real ones.
- Small eval set; report spreads, not just means.
- Free-tier models change; note backend and date for every run.
- Prompts were tuned on dev only; held-out is reported once per final setup.
