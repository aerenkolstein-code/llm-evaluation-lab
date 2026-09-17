"""JE0 conformance. Records here are ephemeral synthetic test fixtures only."""
from __future__ import annotations

import ast
from copy import deepcopy
import io
import json
import os
from pathlib import Path
import socket
import tempfile
import unittest
from contextlib import ExitStack, redirect_stderr
from unittest.mock import patch

from search_cup.contracts import canonical_json, fingerprint
from search_cup.protocol_v23 import reference, seal, verify_seal
from search_cup.v23_judgment import JudgmentJournal, integrity_gate, validate_record
from search_cup import v23_t4_execution as je0
from search_cup.v23_t4_instance import build_bundle as build_parent


def test_only_records(bundle):
    """Never serialized into the formal JE0 bundle or returned as T4 results."""
    records = []
    for planned in bundle["first_pass_plan"]["planned_records"]:
        alias = planned["judge_alias"]
        record = {k: planned[k] for k in ("run_id", "record_id", "candidate_id", "judge_alias")}
        record.update(je0.fixture_decision(
            canonical_json(bundle["blind_input"]).encode(),
            bundle["fixture_profiles"][alias], planned["candidate_id"],
        ))
        record.update(
            judge_identity=next(j for j in bundle["execution_roster"] if j["entrant_id"] == alias),
            package_fingerprint=bundle["blind_input"]["canonical_fingerprint"],
            rubric_fingerprint=fingerprint(bundle["blind_input"]["rubric"]),
            committed_at="2026-09-17T00:00:00+00:00",
        )
        records.append(seal(record))
    return records


def test_override(journal, records, previous=None):
    target = next(r for r in records if r["state"] == "UNKNOWN")
    return seal({
        "kind": "HUMAN_OVERRIDE", "candidate_id": target["candidate_id"],
        "prior_machine_fingerprints": [r["canonical_fingerprint"] for r in records
                                       if r["candidate_id"] == target["candidate_id"]],
        "adjudicator_alias": "synthetic-test-only-human", "decision": "UNKNOWN",
        "trigger": "CRITICAL_UNKNOWN", "reason_code": "TEST_ONLY_PRESERVE_UNRESOLVED",
        "evidence_used": target["evidence_used"], "timestamp": "2026-09-17T00:01:00+00:00",
        "previous_journal_fingerprint": previous or fingerprint(json.loads(journal.entries_json)),
    })


class ExecutionReadinessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bundle = je0.build_bundle()
        cls.pin = cls.bundle["execution_binding"]["canonical_fingerprint"]

    def assertInvalidBundle(self, bundle):
        with self.assertRaises(ValueError):
            je0.validate_bundle(bundle, expected_fingerprint=self.pin)

    def test_deterministic_canonical_bundle_and_fingerprints(self):
        self.assertEqual(canonical_json(self.bundle), canonical_json(je0.build_bundle()))
        je0.validate_bundle(self.bundle, expected_fingerprint=self.pin)
        for key in ("parent_binding", "execution_binding", "first_pass_plan", "integrity_plan", "receipt"):
            verify_seal(self.bundle[key])
        for profile in self.bundle["fixture_profiles"].values():
            verify_seal(profile)

    def test_exact_accepted_parent_and_artifact_lineage(self):
        parent = build_parent()
        for name, expected in je0.PARENT_HASHES.items():
            self.assertEqual(expected, fingerprint(parent[name]), name)
        lineage = self.bundle["parent_binding"]["lineage"]
        self.assertEqual(58, lineage["accepted_pr"])
        self.assertEqual(10448455537, lineage["artifact_id"])
        self.assertEqual(je0.BASELINE, lineage["publication_commit"])
        self.assertEqual(parent["judgment_package"]["canonical_fingerprint"],
                         self.bundle["execution_binding"]["parent_package_fingerprint"])
        self.assertNotEqual(parent["manifest"]["instance_id"], je0.EXECUTION_ID)
        self.assertEqual(parent["blind_judge_view"], self.bundle["blind_input"])

    def test_parent_drift_rejected_before_authoring(self):
        for name in je0.PARENT_HASHES:
            with self.subTest(component=name):
                changed = build_parent()
                if isinstance(changed[name], list):
                    changed[name].append({"mutation": True})
                else:
                    changed[name]["mutation"] = True
                with patch.object(je0, "build_parent", return_value=changed), self.assertRaisesRegex(ValueError, "parent drift"):
                    je0.build_bundle()

    def test_frozen_binding_detects_even_resealed_mutations(self):
        for key in self.bundle:
            with self.subTest(component=key):
                changed = deepcopy(self.bundle)
                if isinstance(changed[key], list):
                    changed[key].append({"extra": True})
                else:
                    changed[key]["extra"] = True
                    if "canonical_fingerprint" in changed[key]:
                        changed[key] = seal(changed[key])
                self.assertInvalidBundle(changed)
        with self.assertRaisesRegex(ValueError, "retained review pin"):
            je0.validate_bundle(self.bundle, expected_fingerprint="0" * 64)

    def test_behavior_mutation_changes_successor_and_run_identity(self):
        altered = deepcopy(self.bundle)
        alias = je0.ALIASES[0]
        profile = altered["fixture_profiles"][alias]
        profile["semantic_cases"][0]["decision_fields"]["confidence"] = 0.8
        profile = seal(profile)
        altered["fixture_profiles"][alias] = profile
        binding = altered["execution_binding"]
        binding["fixture_profile_fingerprints"][alias] = profile["canonical_fingerprint"]
        altered["execution_binding"] = seal(binding)
        self.assertNotEqual(self.pin, altered["execution_binding"]["canonical_fingerprint"])
        self.assertInvalidBundle(altered)
        self.assertIn(self.pin, self.bundle["first_pass_plan"]["run_id"])
        with self.assertRaisesRegex(ValueError, "unfrozen fixture"):
            je0.fixture_decision(canonical_json(self.bundle["blind_input"]).encode(), profile,
                                 profile["semantic_cases"][0]["candidate_id"])

    def test_exact_six_record_future_plan_and_barrier(self):
        plan = self.bundle["first_pass_plan"]
        rows = plan["planned_records"]
        expected = [(j, c["candidate_id"]) for j in je0.ALIASES
                    for c in self.bundle["blind_input"]["candidate_pool"]["candidates"]]
        self.assertEqual(expected, [(p["judge_alias"], p["candidate_id"]) for p in rows])
        self.assertEqual(6, len(rows))
        self.assertEqual(6, len({p["record_id"] for p in rows}))
        self.assertEqual({plan["run_id"]}, {p["run_id"] for p in rows})
        self.assertEqual({je0.PARENT_HASHES["blind_judge_view"]}, {p["blind_input_sha256"] for p in rows})
        self.assertEqual("ALL_SIX_FIRST_PASSES_COMMITTED", plan["human_override_barrier"])
        self.assertTrue(all(p["observed_peer_records"] == [] for p in rows))
        self.assertTrue(all("state" not in p and "committed_at" not in p for p in rows))

    def test_fixture_behavior_is_deterministic_valid_and_evidence_limited(self):
        records = test_only_records(self.bundle)
        self.assertEqual(records, test_only_records(self.bundle))
        for record in records:
            je0.validate_planned_record(record, self.bundle, expected_fingerprint=self.pin)
            candidate = next(c for c in self.bundle["blind_input"]["candidate_pool"]["candidates"]
                             if c["candidate_id"] == record["candidate_id"])
            self.assertLessEqual({canonical_json(e) for e in record["evidence_used"]},
                                 {canonical_json(e) for e in candidate["evidence"]})
        # These are expected unit-test behaviors, not measured T4 results.
        self.assertEqual(["ACCEPT", "UNKNOWN", "UNKNOWN"] * 2, [r["state"] for r in records])

    def test_no_extra_evidence_or_peer_output_can_enter_record(self):
        record = test_only_records(self.bundle)[0]
        for key, value in (("observed_peer_records", ["peer-test-record"]),
                           ("evidence_used", [reference({"extra": "test evidence"}, "extra")] )):
            with self.subTest(key=key):
                with self.assertRaises(ValueError):
                    je0.validate_planned_record(seal({**record, key: value}), self.bundle,
                                                expected_fingerprint=self.pin)

    def test_record_cannot_swap_run_roster_or_frozen_semantics(self):
        record = test_only_records(self.bundle)[0]
        for key, value in (("run_id", "another-run"), ("record_id", "another-record"),
                           ("confidence", 0.75), ("judge_identity", build_parent()["judge_roster"][0])):
            with self.subTest(key=key), self.assertRaises(ValueError):
                je0.validate_planned_record(seal({**record, key: value}), self.bundle,
                                            expected_fingerprint=self.pin)

    def test_blind_payload_change_extra_fields_order_or_evidence_rejected(self):
        profile = self.bundle["fixture_profiles"][je0.ALIASES[0]]
        for mutation in ("peer_records", "evidence_packet", "candidate_pool", "rubric", "provider"):
            changed = deepcopy(self.bundle["blind_input"])
            changed[mutation] = []
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                je0.fixture_decision(canonical_json(changed).encode(), profile,
                                     profile["semantic_cases"][0]["candidate_id"])
        with self.assertRaises(ValueError):
            je0.fixture_decision(json.dumps(self.bundle["blind_input"], indent=2).encode(), profile, "none")
        with self.assertRaises(ValueError):
            je0.fixture_decision(canonical_json(self.bundle["blind_input"]).encode(), profile, "none")

    def test_unknown_cannot_be_coerced_to_reject(self):
        record = next(r for r in test_only_records(self.bundle) if r["state"] == "UNKNOWN")
        with self.assertRaisesRegex(ValueError, "hard-constraint UNKNOWN"):
            validate_record(seal({**record, "state": "REJECT", "failure_class": "NONE"}), self.bundle["blind_input"])

    def test_all_six_states_remain_distinct_in_inherited_schema(self):
        # Deliberately manufactured schema probes, not fixture outputs.
        template = test_only_records(self.bundle)[0]
        failures = {"ACCEPT": "NONE", "REJECT": "NONE", "UNKNOWN": "INSUFFICIENT_EVIDENCE",
                    "NOT_EVALUABLE": "INFRASTRUCTURE", "ERROR": "INFRASTRUCTURE", "BLOCKED": "POLICY"}
        for state, failure in failures.items():
            value = "YES" if state == "ACCEPT" else "NO" if state == "REJECT" else "UNKNOWN"
            record = seal({**template, "state": state, "failure_class": failure,
                           "dimensions": [{**d, "value": value} for d in template["dimensions"]]})
            with self.subTest(state=state):
                validate_record(record, self.bundle["blind_input"])
                wrong = seal({**record, "failure_class": "POLICY" if failure != "POLICY" else "NONE"})
                with self.assertRaises(ValueError):
                    validate_record(wrong, self.bundle["blind_input"])

    def test_first_pass_overwrite_forbidden(self):
        record = test_only_records(self.bundle)[0]
        journal = JudgmentJournal(canonical_json(self.bundle["blind_input"]), je0.ALIASES)
        first = journal.append({"kind": "FIRST_PASS", "record": record})
        with self.assertRaisesRegex(ValueError, "overwrite"):
            first.append({"kind": "FIRST_PASS", "record": record})
        self.assertEqual("[]", journal.entries_json)

    def test_human_override_rejected_at_every_incomplete_barrier(self):
        records = test_only_records(self.bundle)
        journal = JudgmentJournal(canonical_json(self.bundle["blind_input"]), je0.ALIASES)
        for count in range(6):
            with self.subTest(first_pass_count=count), self.assertRaisesRegex(ValueError, "all independent first passes"):
                journal.append(test_override(journal, records))
            journal = journal.append({"kind": "FIRST_PASS", "record": records[count]})

    def test_append_only_adjudication_preserves_six_records_and_hash_chain(self):
        records = test_only_records(self.bundle)
        journal = JudgmentJournal(canonical_json(self.bundle["blind_input"]), je0.ALIASES)
        for record in records:
            journal = journal.append({"kind": "FIRST_PASS", "record": record})
        first = journal.append(test_override(journal, records))
        second = first.append(test_override(first, records))
        self.assertEqual(6, len(json.loads(journal.entries_json)))
        self.assertEqual(8, len(json.loads(second.entries_json)))
        self.assertEqual(json.loads(journal.entries_json), json.loads(second.entries_json)[:6])
        with self.assertRaisesRegex(ValueError, "chain mismatch"):
            first.append(test_override(journal, records))
        bad = seal({**test_override(first, records), "evidence_used": [reference({"new": True}, "new")]})
        with self.assertRaisesRegex(ValueError, "cannot add evidence"):
            first.append(bad)

    def test_complete_j1_j10_plan_keeps_future_gate_not_run(self):
        checks = self.bundle["integrity_plan"]["checks"]
        self.assertEqual({f"J{i}" for i in range(1, 11)}, set(checks))
        for check in checks.values():
            self.assertEqual("NOT_RUN", check["run_status"])
            self.assertTrue(check["required_evidence"])
        self.assertEqual("NOT_RUN", self.bundle["receipt"]["post_run_integrity"])

    def test_any_failed_or_unevidenced_j_gate_is_not_evaluable(self):
        evidence = reference({"test_only": True}, "synthetic-integrity-test")
        checks = {f"J{i}": {"status": "PASS", "evidence": [evidence]} for i in range(1, 11)}
        self.assertEqual("PASS", integrity_gate(checks))
        for key in checks:
            for failure in ({"status": "FAIL", "evidence": [evidence]}, {"status": "PASS", "evidence": []}):
                with self.subTest(gate=key, failure=failure):
                    self.assertEqual("NOT_EVALUABLE", integrity_gate({**checks, key: failure}))

    def test_no_hidden_provenance_in_any_returned_artifact(self):
        rendered = canonical_json(self.bundle)
        for token in ("t4-origin-", "t4-pv1-sealed-submission-", "provenance_ledger", "provenance-ledger"):
            self.assertNotIn(token, rendered)
        blind = canonical_json(self.bundle["blind_input"])
        for token in (*je0.ALIASES, "synthetic-not-connected", je0.BASELINE, "4ff845a2"):
            self.assertNotIn(token, blind)

    def test_authoring_never_invokes_fixture_or_reads_network_env_or_files(self):
        def forbidden(*args, **kwargs):
            raise AssertionError("forbidden authoring capability")

        class NoEnvironment(dict):
            __getitem__ = get = __iter__ = forbidden

        with ExitStack() as stack:
            for target in ("socket.socket", "socket.create_connection", "subprocess.Popen", "subprocess.run",
                           "os.getenv", "builtins.open", "pathlib.Path.read_text", "pathlib.Path.read_bytes"):
                stack.enter_context(patch(target, side_effect=forbidden))
            stack.enter_context(patch.object(os, "environ", NoEnvironment()))
            stack.enter_context(patch.object(je0, "fixture_decision", side_effect=forbidden))
            built = je0.build_bundle()
            je0.validate_bundle(built, expected_fingerprint=self.pin)
        self.assertEqual(canonical_json(self.bundle), canonical_json(built))

    def test_pure_fixture_has_no_io_or_peer_argument(self):
        import inspect
        self.assertEqual(["blind_bytes", "profile", "candidate_id"], list(inspect.signature(je0.fixture_decision).parameters))
        with patch.object(socket, "socket", side_effect=AssertionError("no network")), patch(
            "os.getenv", side_effect=AssertionError("no environment")
        ):
            self.assertEqual(6, len(test_only_records(self.bundle)))

    def test_zero_receipt_and_no_formal_execution(self):
        receipt = self.bundle["receipt"]
        for key in ("provider_calls", "search_calls", "judge_network_calls", "network_calls", "follow_links",
                    "automatic_retries", "credential_reads", "credit_consumption", "formal_record_count",
                    "fixture_decision_calls_on_authoring_path"):
            self.assertEqual(0, receipt[key], key)
        for key in ("execution_allowed", "formal_execution_performed", "official_prompt_consumed", "hidden_registry_loaded",
                    "real_world_candidate_claim", "benchmark_claim", "model_quality_claim", "leaderboard_claim"):
            self.assertIs(False, receipt[key], key)
        self.assertEqual([], receipt["external_tools"])
        self.assertEqual({"value": 0, "currency": "USD"}, receipt["spend"])

    def test_canonical_export_is_byte_stable_and_refuses_reuse(self):
        with tempfile.TemporaryDirectory() as temporary:
            roots = [Path(temporary) / name for name in ("one", "two")]
            for root in roots:
                je0.write_bundle(root)
                self.assertEqual(set(je0.FILENAMES.values()), {p.name for p in root.iterdir()})
                for key, name in je0.FILENAMES.items():
                    self.assertEqual(canonical_json(self.bundle[key]).encode(), (root / name).read_bytes())
            self.assertEqual([(p.name, p.read_bytes()) for p in sorted(roots[0].iterdir())],
                             [(p.name, p.read_bytes()) for p in sorted(roots[1].iterdir())])
            with self.assertRaises(FileExistsError):
                je0.write_bundle(roots[0])

    def test_cli_has_no_execute_or_journal_command(self):
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
            je0.main(["execute"])
        self.assertEqual(2, error.exception.code)

    def test_new_module_imports_only_declared_inert_dependencies(self):
        tree = ast.parse(Path(je0.__file__).read_text())
        names = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
        names |= {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
        self.assertEqual({"__future__", "argparse", "json", "pathlib", "contracts", "protocol_v23",
                          "v23_judgment", "v23_t4_instance"}, names)


if __name__ == "__main__":
    unittest.main()
