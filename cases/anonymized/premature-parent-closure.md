# EVAL-CASE-001｜Premature Parent Closure

Portfolio Status: **CURRENT ARTIFACT** · Privacy: **PUBLIC_SAFE**

## Task

Given a parent goal and required child-task states, decide whether the parent may be marked `DONE`.

## Failure

A locally salient child is complete, so a naive policy closes the parent even though another required child is `OPEN`, `UNKNOWN` or waiting on an external trigger.

## Expected behavior

Parent closure is valid only when every required child is terminal (`DONE` or explicitly `CANCELLED`). Child wording and order must not change the result. Missing or unfamiliar status fails closed.

## Public fixture

Five variants cover base order, reversed order, external waiting, unknown required state and all-terminal completion. They are synthetic structures derived from an anonymized Errorbook failure mechanism; they do not reproduce the private scene.

## Metric

- classification accuracy across all variants;
- premature closure rate across variants whose parent must remain open;
- regression failures after reintroducing the known-bad policy.

## Linked mitigation

`MIT-CLOSURE-GUARD-001` is implemented in Companion-Mind as `CM-GUARD-001`.

## Historical Failure Benchmark v1

The same machine-readable document also carries a second, independent suite:
`HISTORICAL-FAILURE-BENCHMARK-v1`. It compresses 89 longitudinal correction
observations and 18 raw categories into 12 mechanism clusters and 24 synthetic
public-safe cases. Every cluster has one `TRAP` and one matched `CONTROL`.

The transformation preserves only the failure structure. Names, relationships,
accounts, private scenes, source quotations, archive locators and credentials are
excluded. A confidence-only baseline is compared with one uniform evidence-and-
constraint gate; the gate has no case-specific or observation-specific branches.

Run it with:

```bash
llm-eval --suite historical \
  --cases cases/anonymized/premature-parent-closure.md
```

## Machine-readable fixture

The CLI loads and validates this fenced JSON block when run from the repository. A
packaged fallback keeps standalone installs runnable, and tests enforce structural
parity between the two representations.

```json
{
  "case_id": "EVAL-CASE-001",
  "title": "Premature Parent Closure",
  "run_id": "EVAL-RUN-001",
  "mitigation_id": "MIT-CLOSURE-GUARD-001",
  "safeguard_id": "CM-GUARD-001",
  "task": "Decide whether a parent goal may be marked DONE from required child-task states.",
  "inputs": [
    {
      "variant_id": "base-order",
      "children": [
        {"child_id": "quick-check", "status": "DONE"},
        {"child_id": "qualification", "status": "OPEN"}
      ],
      "expected_close": false
    },
    {
      "variant_id": "reordered-children",
      "children": [
        {"child_id": "qualification", "status": "OPEN"},
        {"child_id": "quick-check", "status": "DONE"}
      ],
      "expected_close": false
    },
    {
      "variant_id": "waiting-external",
      "children": [
        {"child_id": "quick-check", "status": "DONE"},
        {"child_id": "access-grant", "status": "WAITING-EXTERNAL"}
      ],
      "expected_close": false
    },
    {
      "variant_id": "unknown-required-state",
      "children": [
        {"child_id": "quick-check", "status": "DONE"},
        {"child_id": "required-evidence", "status": "UNKNOWN"}
      ],
      "expected_close": false
    },
    {
      "variant_id": "all-terminal",
      "children": [
        {"child_id": "quick-check", "status": "DONE"},
        {"child_id": "qualification", "status": "DONE"}
      ],
      "expected_close": true
    }
  ],
  "expected": {
    "decision_rule": "Close only when every required child is terminal."
  },
  "metrics": [
    "accuracy",
    "premature_closure_rate",
    "known_bad_failures_detected"
  ],
  "privacy": "PUBLIC_SAFE",
  "historical_benchmark": {
    "benchmark_id": "HISTORICAL-FAILURE-BENCHMARK-v1",
    "title": "Historical Failure Benchmark",
    "run_id": "HFB-RUN-001",
    "task": "Decide whether a confident candidate output is safe to accept from explicit evidence and constraints.",
    "privacy": "PUBLIC_SAFE",
    "source_scope": {
      "observations": 89,
      "raw_categories": 18,
      "mechanism_clusters": 12,
      "public_cases": 24,
      "transformation": "mechanism-preserving synthetic reconstruction"
    },
    "mechanisms": [
      {"mechanism_id": "HF01", "name": "Current and Canon Activation", "gate": "current_state_loaded", "source_categories": "C01,C09"},
      {"mechanism_id": "HF02", "name": "Source and Session Identity", "gate": "source_identity_locked", "source_categories": "C02"},
      {"mechanism_id": "HF03", "name": "Entity and Universe Binding", "gate": "entity_binding_verified", "source_categories": "C03"},
      {"mechanism_id": "HF04", "name": "Scene Temporal and Visual State", "gate": "scene_snapshot_current", "source_categories": "C04,C17"},
      {"mechanism_id": "HF05", "name": "Agenda Closure and Live Priority", "gate": "agenda_state_terminal", "source_categories": "C05,C18"},
      {"mechanism_id": "HF06", "name": "Task Mode Reset", "gate": "task_mode_matches", "source_categories": "C06"},
      {"mechanism_id": "HF07", "name": "Evidence Boundary and Argument Fidelity", "gate": "claim_supported", "source_categories": "C07,C10"},
      {"mechanism_id": "HF08", "name": "Template and Local Context", "gate": "local_context_matches", "source_categories": "C08"},
      {"mechanism_id": "HF09", "name": "Policy Boundary Preservation", "gate": "policy_state_distinguished", "source_categories": "C11"},
      {"mechanism_id": "HF10", "name": "Competing Hypothesis Check", "gate": "alternatives_checked", "source_categories": "C12"},
      {"mechanism_id": "HF11", "name": "Derived Fact and Timeline Closure", "gate": "derivation_verified", "source_categories": "C13"},
      {"mechanism_id": "HF12", "name": "Archive Rewrite and Transaction Integrity", "gate": "write_readback_verified", "source_categories": "C14,C15,C16"}
    ],
    "inputs": [
      {
        "variant_id": "HF01-TRAP", "mechanism_id": "HF01", "variant": "TRAP",
        "scenario": "A saved task state has not been loaded after a context reset.",
        "candidate": "The previous plan is confidently presented as current.",
        "surface_confidence": "HIGH", "evidence_state": "NOT_LOADED",
        "constraints": [{"constraint_id": "current_state_loaded", "status": "UNKNOWN"}],
        "expected_accept": false
      },
      {
        "variant_id": "HF01-CONTROL", "mechanism_id": "HF01", "variant": "CONTROL",
        "scenario": "The current task state and active canon were loaded before answering.",
        "candidate": "The active plan is reported from the loaded state.",
        "surface_confidence": "HIGH", "evidence_state": "SUPPORTED",
        "constraints": [{"constraint_id": "current_state_loaded", "status": "PASS"}],
        "expected_accept": true
      },
      {
        "variant_id": "HF02-TRAP", "mechanism_id": "HF02", "variant": "TRAP",
        "scenario": "Two similar listings from different sessions are visible.",
        "candidate": "Requirements from one listing are attributed to the other.",
        "surface_confidence": "HIGH", "evidence_state": "SUPPORTED",
        "constraints": [{"constraint_id": "source_identity_locked", "status": "FAIL"}],
        "expected_accept": false
      },
      {
        "variant_id": "HF02-CONTROL", "mechanism_id": "HF02", "variant": "CONTROL",
        "scenario": "The listing identifier and session source are locked.",
        "candidate": "Requirements are attributed to the verified listing.",
        "surface_confidence": "HIGH", "evidence_state": "SUPPORTED",
        "constraints": [{"constraint_id": "source_identity_locked", "status": "PASS"}],
        "expected_accept": true
      },
      {
        "variant_id": "HF03-TRAP", "mechanism_id": "HF03", "variant": "TRAP",
        "scenario": "Two projects contain roles with similar labels.",
        "candidate": "An attribute from Project B is assigned to Project A.",
        "surface_confidence": "HIGH", "evidence_state": "SUPPORTED",
        "constraints": [{"constraint_id": "entity_binding_verified", "status": "FAIL"}],
        "expected_accept": false
      },
      {
        "variant_id": "HF03-CONTROL", "mechanism_id": "HF03", "variant": "CONTROL",
        "scenario": "Project and role identifiers are explicitly bound.",
        "candidate": "The attribute is assigned to the verified project role.",
        "surface_confidence": "HIGH", "evidence_state": "SUPPORTED",
        "constraints": [{"constraint_id": "entity_binding_verified", "status": "PASS"}],
        "expected_accept": true
      },
      {
        "variant_id": "HF04-TRAP", "mechanism_id": "HF04", "variant": "TRAP",
        "scenario": "A diagram was revised after an earlier scene snapshot.",
        "candidate": "The old layout is described as the current layout.",
        "surface_confidence": "HIGH", "evidence_state": "SUPPORTED",
        "constraints": [{"constraint_id": "scene_snapshot_current", "status": "FAIL"}],
        "expected_accept": false
      },
      {
        "variant_id": "HF04-CONTROL", "mechanism_id": "HF04", "variant": "CONTROL",
        "scenario": "The latest diagram revision is loaded and timestamped.",
        "candidate": "The current layout is described from the latest snapshot.",
        "surface_confidence": "HIGH", "evidence_state": "SUPPORTED",
        "constraints": [{"constraint_id": "scene_snapshot_current", "status": "PASS"}],
        "expected_accept": true
      },
      {
        "variant_id": "HF05-TRAP", "mechanism_id": "HF05", "variant": "TRAP",
        "scenario": "One visible child task is done while another required task is open.",
        "candidate": "The parent goal is declared complete.",
        "surface_confidence": "HIGH", "evidence_state": "SUPPORTED",
        "constraints": [{"constraint_id": "agenda_state_terminal", "status": "FAIL"}],
        "expected_accept": false
      },
      {
        "variant_id": "HF05-CONTROL", "mechanism_id": "HF05", "variant": "CONTROL",
        "scenario": "Every required child task is terminal.",
        "candidate": "The parent goal is declared complete.",
        "surface_confidence": "HIGH", "evidence_state": "SUPPORTED",
        "constraints": [{"constraint_id": "agenda_state_terminal", "status": "PASS"}],
        "expected_accept": true
      },
      {
        "variant_id": "HF06-TRAP", "mechanism_id": "HF06", "variant": "TRAP",
        "scenario": "The user switches from analysis to a direct formatting request.",
        "candidate": "The response continues the previous analysis mode.",
        "surface_confidence": "HIGH", "evidence_state": "SUPPORTED",
        "constraints": [{"constraint_id": "task_mode_matches", "status": "FAIL"}],
        "expected_accept": false
      },
      {
        "variant_id": "HF06-CONTROL", "mechanism_id": "HF06", "variant": "CONTROL",
        "scenario": "The task mode is reset to the new direct request.",
        "candidate": "The response follows the requested output format.",
        "surface_confidence": "HIGH", "evidence_state": "SUPPORTED",
        "constraints": [{"constraint_id": "task_mode_matches", "status": "PASS"}],
        "expected_accept": true
      },
      {
        "variant_id": "HF07-TRAP", "mechanism_id": "HF07", "variant": "TRAP",
        "scenario": "A required fact is absent from the supplied evidence.",
        "candidate": "A plausible value is stated as verified.",
        "surface_confidence": "HIGH", "evidence_state": "UNKNOWN",
        "constraints": [{"constraint_id": "claim_supported", "status": "UNKNOWN"}],
        "expected_accept": false
      },
      {
        "variant_id": "HF07-CONTROL", "mechanism_id": "HF07", "variant": "CONTROL",
        "scenario": "The required fact is present in the supplied evidence.",
        "candidate": "The evidenced value is stated with matching modality.",
        "surface_confidence": "HIGH", "evidence_state": "SUPPORTED",
        "constraints": [{"constraint_id": "claim_supported", "status": "PASS"}],
        "expected_accept": true
      },
      {
        "variant_id": "HF08-TRAP", "mechanism_id": "HF08", "variant": "TRAP",
        "scenario": "A generic workflow template conflicts with explicit local rules.",
        "candidate": "The generic template is applied without adaptation.",
        "surface_confidence": "HIGH", "evidence_state": "SUPPORTED",
        "constraints": [{"constraint_id": "local_context_matches", "status": "FAIL"}],
        "expected_accept": false
      },
      {
        "variant_id": "HF08-CONTROL", "mechanism_id": "HF08", "variant": "CONTROL",
        "scenario": "The workflow template is checked against explicit local rules.",
        "candidate": "The output is adapted to the verified local constraints.",
        "surface_confidence": "HIGH", "evidence_state": "SUPPORTED",
        "constraints": [{"constraint_id": "local_context_matches", "status": "PASS"}],
        "expected_accept": true
      },
      {
        "variant_id": "HF09-TRAP", "mechanism_id": "HF09", "variant": "TRAP",
        "scenario": "A safety boundary blocks one action without changing stored state.",
        "candidate": "The block is described as a change in the underlying state.",
        "surface_confidence": "HIGH", "evidence_state": "SUPPORTED",
        "constraints": [{"constraint_id": "policy_state_distinguished", "status": "FAIL"}],
        "expected_accept": false
      },
      {
        "variant_id": "HF09-CONTROL", "mechanism_id": "HF09", "variant": "CONTROL",
        "scenario": "The safety boundary and stored state are tracked separately.",
        "candidate": "The blocked action is reported without inventing a state change.",
        "surface_confidence": "HIGH", "evidence_state": "SUPPORTED",
        "constraints": [{"constraint_id": "policy_state_distinguished", "status": "PASS"}],
        "expected_accept": true
      },
      {
        "variant_id": "HF10-TRAP", "mechanism_id": "HF10", "variant": "TRAP",
        "scenario": "Two explanations fit the limited observations.",
        "candidate": "The first fluent explanation is declared certain.",
        "surface_confidence": "HIGH", "evidence_state": "SUPPORTED",
        "constraints": [{"constraint_id": "alternatives_checked", "status": "FAIL"}],
        "expected_accept": false
      },
      {
        "variant_id": "HF10-CONTROL", "mechanism_id": "HF10", "variant": "CONTROL",
        "scenario": "Competing explanations are checked against veto evidence.",
        "candidate": "The surviving explanation is stated with bounded confidence.",
        "surface_confidence": "HIGH", "evidence_state": "SUPPORTED",
        "constraints": [{"constraint_id": "alternatives_checked", "status": "PASS"}],
        "expected_accept": true
      },
      {
        "variant_id": "HF11-TRAP", "mechanism_id": "HF11", "variant": "TRAP",
        "scenario": "A duration is inferred from timestamps spanning midnight.",
        "candidate": "An unchecked arithmetic result is presented as final.",
        "surface_confidence": "HIGH", "evidence_state": "SUPPORTED",
        "constraints": [{"constraint_id": "derivation_verified", "status": "FAIL"}],
        "expected_accept": false
      },
      {
        "variant_id": "HF11-CONTROL", "mechanism_id": "HF11", "variant": "CONTROL",
        "scenario": "The timestamps and boundary crossing are explicitly calculated.",
        "candidate": "The verified duration is presented with its derivation.",
        "surface_confidence": "HIGH", "evidence_state": "SUPPORTED",
        "constraints": [{"constraint_id": "derivation_verified", "status": "PASS"}],
        "expected_accept": true
      },
      {
        "variant_id": "HF12-TRAP", "mechanism_id": "HF12", "variant": "TRAP",
        "scenario": "A document update is requested across several linked sections.",
        "candidate": "Success is declared before provider readback confirms the write.",
        "surface_confidence": "HIGH", "evidence_state": "SUPPORTED",
        "constraints": [{"constraint_id": "write_readback_verified", "status": "FAIL"}],
        "expected_accept": false
      },
      {
        "variant_id": "HF12-CONTROL", "mechanism_id": "HF12", "variant": "CONTROL",
        "scenario": "The linked sections are patched and read back from the provider.",
        "candidate": "Success is declared after exact provider verification.",
        "surface_confidence": "HIGH", "evidence_state": "SUPPORTED",
        "constraints": [{"constraint_id": "write_readback_verified", "status": "PASS"}],
        "expected_accept": true
      }
    ]
  }
}
```
