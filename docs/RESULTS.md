# RESULTS.md

Template. Fill every number from `make eval` output in `evals/results/`; never type a figure you did not measure. Record the date, git commit, model backend, and prompt versions for each run.

## Backends (T03)

`make smoke` runs three checks per backend, each live with the cache read skipped: a plain reply, a tool call with its result fed back, and a `Triage` object submitted through a tool and validated. Output cap 1,024 tokens. One run per model on 2026-11-21.

| Backend | Model | hello | tool_call | structured | Notes |
| --- | --- | --- | --- | --- | --- |
| ollama | qwen2.5:7b-instruct | fail | fail | fail | Model not pulled yet (HTTP 404); rerun `make smoke` after `ollama pull qwen2.5:7b-instruct` |
| openrouter | nvidia/nemotron-3-ultra-550b-a55b:free | ok | ok | ok | 2.1 to 5.4 s per call; structured answer used 363 output tokens |
| openrouter | nvidia/nemotron-3.5-super-vl:free | ok | ok | ok | 0.6 to 2.2 s per call; structured answer used 258 output tokens |
| openrouter | baidu/ernie-5.5-flash-preview:free | n/a | n/a | ok | Only the structured check ran live; the full rerun got HTTP 429 upstream |
| openrouter | google/gemma-4-31b-it, google/gemma-4-26b-a4b-it, inclusionai/ling-3.2-flash (all `:free`) | 429 | 429 | 429 | Rate-limited upstream during the probe; capability unknown |
| gemini | gemini-2.5-flash | skip | skip | skip | No `GEMINI_API_KEY`, so the daily quota could not be read |

Candidates were every free OpenRouter model listing `tools` support on 2026-11-21, newest and largest first. The two Nemotron models failed the structured check at the old 256-token cap: both spent the cap on reasoning and returned no tool call. At 1,024 they pass.

**Decision (PLAN section 4).** Gemini's quota is unknown, so it is not primary and is kept for the final demo run. The chain is `[ollama, openrouter, gemini]`: local is primary for evals, and OpenRouter runs Nemotron Ultra with Nemotron Super and Ernie as fallbacks.

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
