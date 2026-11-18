# DEMO.md

A 2-minute demo script. Record it last, after the README results are final. Use free tools only (OBS Studio or your OS screen recorder). Record on a cached run so timing is stable.

## Setup before recording

- [ ] `make up`, stack healthy, local trace UI running
- [ ] Scenario chosen: **S01 (bad deploy)** for the main flow; one **H3 (injection)** clip for safety
- [ ] LLM mode `replay` or a warmed cache, so the run finishes in under 30 seconds
- [ ] Terminal font large; close notifications; light, uncluttered desktop
- [ ] Results table open in a second tab

## Script (about 2:00)

| Time | Show | Say |
| --- | --- | --- |
| 0:00 to 0:15 | Title and one-line problem | "On-call engineers lose time gathering evidence and doubting fixes. This agent system investigates an incident and never acts without approval." |
| 0:15 to 0:35 | Inject fault in the demo stack; the alert fires | "A deploy just broke checkout. The alert goes to the supervisor." |
| 0:35 to 1:00 | Run on S01; trace view showing triage, diagnosis tool calls | "Triage picks the service. Diagnosis queries logs, metrics and deploys, and searches past runbooks." |
| 1:00 to 1:20 | Verifier rejecting one unsupported claim, then passing the rest | "Every claim must cite a real log line. The verifier rejects one it cannot support." |
| 1:20 to 1:40 | Fix proposal, critic revise, approval prompt; approve | "The critic checks the rollback plan and blast radius. Nothing runs until I approve." |
| 1:40 to 1:50 | H3 clip: injected log line ignored, flagged | "A log line tried to give the agent orders. It was ignored and flagged." |
| 1:50 to 2:00 | Results table | "On N incidents: X% root-cause accuracy, zero unapproved actions, Y cents per incident, all on free tiers." |

## After recording

- [ ] Trim to 2 minutes or less
- [ ] Add the link to the top of `README.md`
- [ ] Export a short GIF of the approval step for the README
- [ ] Check that no keys or private paths are visible on screen
