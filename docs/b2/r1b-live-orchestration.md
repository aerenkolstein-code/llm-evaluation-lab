# B2 R1b One-Shot Live Orchestration

Status: **Draft PR scaffold / implementation handoff only**.

Authority:
- `PLAN-B2-BLIND-R1b v0.1` — Drive `1fR125gjS2WqSJaedAuQAxw2pcvXK8WJN00v8Rd_gOh0`
- `WO-B2-BLIND-R1B-01 v0.1` — Drive `1v2X3H9Ke2Z1Veic7ZNMQRv09M12ix-7Ps1L0byFVzwg`
- implementation issue `#36`
- P0 baseline receipt — Drive `12GHMbw6jrAbF5A9bNo_KXpaxMqCpCfe5OYVy1iPYUjA`

Starting baseline: `main@0ba7c2572762afe38ccf6a71b012d9d8a6dae3a5`, tree `f88f3f77429a52639c0fa5b5444a9d10b01235d9`.

This scaffold exists only to anchor the dedicated R1b review lineage. It does **not** create a live provider workflow and does **not** authorize a provider call, credential access, spend, merge, or R1b execution.

## Implementation contract

Program-group implementation under the Work Order must keep the provider lane manual-only and unreachable from PR, push, scheduled, ordinary-CI, or smoke events. The preferred live workflow path is `.github/workflows/b2_blind_handoff_v5_live.yml` and its only allowed trigger class is explicit manual dispatch.

The implementation should reuse the independently reviewed v5.2 handoff and blind-eval contracts. `b2/blind_handoff.py`, `b2/blind_eval.py`, schemas, dependency files, ordinary CI, and the existing no-provider smoke are no-touch by default unless a separately justified scope expansion is approved.

Before any future provider gate can open, the orchestration must preserve exact binding/freshness, runner-generated return-key possession proof, one-time acknowledgement/replay protection, `automatic_retries = 0`, maximum provider attempts = 1, private/public evidence separation, body-free EMPTY_FINAL_CONTENT diagnostics, result decryptability, atomic publication, and verified cleanup.

## Expected review surface

Preferred minimal final PR surface:
1. `.github/workflows/b2_blind_handoff_v5_live.yml` — manual-only orchestration.
2. `docs/b2/r1b-live-orchestration.md` — this contract, updated with exact implementation evidence.
3. `tests/test_b2_r1b_live_orchestration.py` — static/adversarial trigger, retry, secret-lane and cleanup gates.

The exact implementation head must pass focused tests, full repository tests, the existing deterministic no-provider smoke, static trigger audit, leak scan, cleanup/publication tests, and distinct Independent QA. Engineering/IQA completion does not authorize merge; merge does not authorize the final one-shot provider execution.

Historical Q1-R1 remains `HISTORICAL-EXECUTION-ONLY / HTTP 200 / EMPTY_FINAL_CONTENT / NO SCORABLE ANSWER / NOT_EVALUABLE`.
