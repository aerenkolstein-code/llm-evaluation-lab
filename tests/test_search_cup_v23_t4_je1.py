"""JE1 Phase A only: replay simulations stay in memory, never formal output."""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import socket
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from search_cup.contracts import canonical_json, fingerprint
from search_cup.protocol_v23 import reference, seal
from search_cup.v23_judgment import JudgmentJournal, integrity_gate, validate_record
from search_cup.v23_t4_execution import validate_planned_record
from search_cup import v23_t4_je1 as je1


TEST_AUTHORITY = "TEST-ONLY-NOT-A-BOARD-AUTHORIZATION"
TEST_SHA = "e" * 40
TEST_SOURCE = {
    "head": TEST_SHA, "tree": "d" * 40, "branch": "refs/heads/main",
    "origin_main": TEST_SHA, "clean": True,
    "ci": dict.fromkeys(("GITHUB_EVENT_NAME", "GITHUB_REF", "GITHUB_SHA", "GITHUB_RUN_ATTEMPT", "GITHUB_RUN_ID")),
}


class MemoryStore:
    # Never writes a simulated FIRST_PASS or JE1 run marker to disk.
    is_formal = False

    def __init__(self):
        self.data = {}
        self.history = []

    def exists(self, name):
        return name in self.data

    def read(self, name):
        return self.data[name]

    def names(self):
        return sorted(self.data)

    def write(self, name, data, *, replace=False):
        if name in self.data and not replace:
            raise je1.GateError("ARTIFACT_OVERWRITE_FORBIDDEN")
        self.data[name] = data
        self.history.append((name, data))


def memory_simulation(bundle, store=None):
    store = store or MemoryStore()
    je1._write_json(store, "preflight.json", {"test_only": True, "formal_record_count": 0})
    with patch.object(je1, "_source_snapshot", return_value=deepcopy(TEST_SOURCE)):
        receipt = je1._execute(store, bundle, deepcopy(TEST_SOURCE), TEST_AUTHORITY)
    return store, receipt


class JE1Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bundle = je1._frozen_bundle(je1.BINDING)
        cls.store, cls.receipt = memory_simulation(cls.bundle)
        cls.entries = json.loads(cls.store.read("judgment-journal.json"))
        cls.records = [entry["record"] for entry in cls.entries]

    def args(self, output=None):
        return {"authority_receipt_id": TEST_AUTHORITY, "expected_source_sha": TEST_SHA,
                "expected_binding": je1.BINDING, "run_id": je1.RUN_ID,
                "output_dir": output or Path("/tmp/je1-test-must-not-be-created")}

    def assertPrestart(self, args, source=None):
        with patch.object(je1, "_source_snapshot", return_value=source or deepcopy(TEST_SOURCE)), \
                patch.object(je1, "_DiskStore", side_effect=AssertionError("no disk execution")) as disk, \
                patch.object(je1, "fixture_decision", side_effect=AssertionError("no decision")) as decision:
            result = je1.replay(**args)
        disk.assert_not_called()
        decision.assert_not_called()
        self.assertEqual("PRESTART_NOT_EVALUABLE", result["terminal_status"])
        self.assertFalse(result["formal_execution_performed"])
        self.assertEqual(0, result["formal_record_count"])
        return result

    def test_retained_binding_is_independent_and_exact(self):
        self.assertEqual("a87a0ad172d6292cc7be52580e1ed7d85615e1298582249f892032fea83fd11d", je1.BINDING)
        self.assertEqual(je1.RUN_ID, self.bundle["first_pass_plan"]["run_id"])
        with self.assertRaises(je1.GateError):
            je1._frozen_bundle("0" * 64)

    def test_parent_profile_roster_plan_rubric_adjudication_drift(self):
        for component in ("parent_binding", "fixture_profiles", "execution_roster", "first_pass_plan",
                          "blind_input", "execution_binding"):
            bad = deepcopy(self.bundle)
            if isinstance(bad[component], list):
                bad[component].append({"changed": True})
            else:
                bad[component]["changed"] = True
                if "canonical_fingerprint" in bad[component]:
                    bad[component] = seal(bad[component])
            with self.subTest(component=component), patch.object(je1, "build_bundle", return_value=bad), self.assertRaises(ValueError):
                je1._frozen_bundle(je1.BINDING)
        for part in ("rubric", "adjudication", "candidate_pool", "evidence_packet"):
            bad = deepcopy(self.bundle)
            bad["blind_input"][part]["changed"] = True
            with self.subTest(part=part), patch.object(je1, "build_bundle", return_value=bad), self.assertRaises(ValueError):
                je1._frozen_bundle(je1.BINDING)

    def test_six_pairs_and_schedule_match_frozen_plan(self):
        planned = self.bundle["first_pass_plan"]["planned_records"]
        expected = [(p["judge_alias"], p["candidate_id"]) for p in planned]
        self.assertEqual(6, len(expected))
        self.assertEqual(6, len(set(expected)))
        self.assertEqual(expected, [(r["judge_alias"], r["candidate_id"]) for r in self.records])
        self.assertEqual(expected, sorted(expected))
        self.assertEqual(6, self.receipt["fixture_decision_calls"])

    def test_simulation_is_explicitly_non_formal_and_memory_only(self):
        self.assertTrue(self.receipt["test_only"])
        self.assertFalse(self.receipt["formal_execution_performed"])
        self.assertFalse(self.receipt["formal_execution_complete"])
        self.assertEqual(0, self.receipt["formal_record_count"])
        self.assertEqual(6, self.receipt["test_record_count"])
        self.assertFalse(self.receipt["run_identity_consumed"])

    def test_frozen_case_states_and_confidence(self):
        self.assertEqual(["ACCEPT", "UNKNOWN", "UNKNOWN"] * 2, [r["state"] for r in self.records])
        self.assertEqual([0.95, 0.5, 0.5, 0.9, 0.25, 0.25], [r["confidence"] for r in self.records])
        for record in self.records:
            validate_record(record, self.bundle["blind_input"])
            validate_planned_record(record, self.bundle, expected_fingerprint=je1.BINDING)

    def test_wrong_record_run_alias_candidate_and_identity_rejected(self):
        record = self.records[0]
        for key, value in (("record_id", "wrong"), ("run_id", "wrong"), ("judge_alias", "wrong"),
                           ("candidate_id", "wrong"), ("judge_identity", self.bundle["execution_roster"][1]),
                           ("confidence", 0.123)):
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_planned_record(seal({**record, key: value}), self.bundle, expected_fingerprint=je1.BINDING)

    def test_peer_injection_and_new_evidence_rejected(self):
        for key, value in (("observed_peer_records", ["injected-peer"]),
                           ("evidence_used", [reference({"test": "extra"}, "new-evidence")])):
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_planned_record(seal({**self.records[0], key: value}), self.bundle,
                                        expected_fingerprint=je1.BINDING)

    def test_noncanonical_or_changed_blind_input_rejected(self):
        profile = self.bundle["fixture_profiles"]["t4-fixture-judge-a"]
        candidate = self.records[0]["candidate_id"]
        for value in (json.dumps(self.bundle["blind_input"], indent=2).encode(),
                      canonical_json({**self.bundle["blind_input"], "peer_records": []}).encode()):
            with self.assertRaises(ValueError):
                je1.fixture_decision(value, profile, candidate)

    def test_hard_unknown_is_not_accept_or_reject(self):
        record = self.records[1]
        for state in ("ACCEPT", "REJECT"):
            with self.subTest(state=state), self.assertRaises(ValueError):
                validate_record(seal({**record, "state": state, "failure_class": "NONE"}), self.bundle["blind_input"])

    def test_six_terminal_schema_states_remain_typed(self):
        failures = {"ACCEPT": "NONE", "REJECT": "NONE", "UNKNOWN": "INSUFFICIENT_EVIDENCE",
                    "NOT_EVALUABLE": "INFRASTRUCTURE", "ERROR": "INFRASTRUCTURE", "BLOCKED": "POLICY"}
        for state, failure in failures.items():
            value = "YES" if state == "ACCEPT" else "NO" if state == "REJECT" else "UNKNOWN"
            record = seal({**self.records[0], "state": state, "failure_class": failure,
                           "dimensions": [{**d, "value": value} for d in self.records[0]["dimensions"]]})
            with self.subTest(state=state):
                validate_record(record, self.bundle["blind_input"])
                with self.assertRaises(ValueError):
                    validate_record(seal({**record, "failure_class": "POLICY" if failure != "POLICY" else "NONE"}),
                                    self.bundle["blind_input"])

    def test_record_overwrite_and_early_override_rejected(self):
        record = self.records[0]
        journal = JudgmentJournal(canonical_json(self.bundle["blind_input"]), tuple(self.bundle["first_pass_plan"]["judges"]))
        journal = journal.append({"kind": "FIRST_PASS", "record": record})
        with self.assertRaisesRegex(ValueError, "overwrite"):
            journal.append({"kind": "FIRST_PASS", "record": record})
        override = seal({"kind": "HUMAN_OVERRIDE", "candidate_id": record["candidate_id"],
                         "prior_machine_fingerprints": [record["canonical_fingerprint"]],
                         "adjudicator_alias": "test-only", "decision": "UNKNOWN", "trigger": "RUBRIC_EDGE",
                         "reason_code": "TEST_ONLY", "evidence_used": record["evidence_used"],
                         "timestamp": datetime.now(timezone.utc).isoformat(),
                         "previous_journal_fingerprint": fingerprint(json.loads(journal.entries_json))})
        with self.assertRaisesRegex(ValueError, "all independent first passes"):
            journal.append(override)
        self.assertEqual(0, self.receipt["human_override_count"])

    def test_phase_a_preflight_and_plan_never_execute_or_create_store(self):
        with patch.object(je1, "_source_snapshot", return_value=TEST_SOURCE), \
                patch.object(je1, "fixture_decision", side_effect=AssertionError("no decisions")), \
                patch.object(je1, "_DiskStore", side_effect=AssertionError("no files")):
            result = je1.preflight(je1.BINDING)
            plan = je1.frozen_plan(je1.BINDING)
        self.assertEqual("PASS", result["terminal_status"])
        self.assertFalse(result["formal_execution_allowed"])
        self.assertFalse(result["formal_execution_performed"])
        self.assertEqual(0, result["formal_record_count"])
        self.assertEqual(0, result["fixture_decision_calls"])
        self.assertEqual(6, len(plan["planned_records"]))
        self.assertTrue(all(p["status"] == "PLANNED_NOT_EXECUTED" for p in plan["planned_records"]))

    def test_missing_authority_rejected(self):
        for authority in (None, "", " "):
            self.assertEqual("AUTHORITY_RECEIPT_REQUIRED", self.assertPrestart(
                {**self.args(), "authority_receipt_id": authority})["reason_code"])

    def test_wrong_expected_source_binding_and_run_rejected(self):
        for key, value in (("expected_source_sha", "0" * 40), ("expected_binding", "0" * 64), ("run_id", "JE1-002")):
            with self.subTest(key=key):
                self.assertPrestart({**self.args(), key: value})

    def test_non_main_detached_or_dirty_source_rejected(self):
        for delta in ({"branch": "refs/heads/agent/test"}, {"branch": None},
                      {"branch": "refs/pull/1/merge"}, {"origin_main": "0" * 40}, {"clean": False}):
            with self.subTest(delta=delta):
                self.assertPrestart(self.args(), {**TEST_SOURCE, **delta})

    def test_ci_reruns_non_dispatch_and_wrong_ref_rejected(self):
        ci = {"GITHUB_EVENT_NAME": "workflow_dispatch", "GITHUB_REF": "refs/heads/main",
              "GITHUB_SHA": TEST_SHA, "GITHUB_RUN_ATTEMPT": "1", "GITHUB_RUN_ID": "test-only-ci"}
        je1._source_gate({**TEST_SOURCE, "ci": ci}, TEST_SHA)
        for delta in ({"GITHUB_RUN_ATTEMPT": "2"}, {"GITHUB_RUN_ATTEMPT": None},
                      {"GITHUB_REF": "refs/pull/1/merge"}, {"GITHUB_EVENT_NAME": "pull_request"},
                      {"GITHUB_SHA": "0" * 40}):
            with self.subTest(delta=delta):
                self.assertPrestart(self.args(), {**TEST_SOURCE, "ci": {**ci, **delta}})

    def test_source_probe_uses_only_read_only_git_and_public_context(self):
        requested = []
        allowed_context = set(TEST_SOURCE["ci"])

        class PublicContext(dict):
            def get(self, key, default=None):
                self_test.assertIn(key, allowed_context)
                requested.append(key)
                return super().get(key, default)

        self_test = self
        replies = {
            ("rev-parse", "HEAD"): TEST_SHA,
            ("rev-parse", "HEAD^{tree}"): TEST_SOURCE["tree"],
            ("symbolic-ref", "-q", "HEAD"): "refs/heads/main",
            ("rev-parse", "refs/remotes/origin/main"): TEST_SHA,
            ("status", "--porcelain=v1", "--untracked-files=normal"): "",
        }

        def read_only_git(argv, **kwargs):
            self.assertEqual("git", argv[0])
            self.assertIn("core.fsmonitor=false", argv)
            self.assertIn("core.hooksPath=/dev/null", argv)
            self.assertFalse(kwargs.get("shell", False))
            self.assertEqual({"PATH", "LC_ALL", "GIT_CONFIG_NOSYSTEM", "GIT_CONFIG_GLOBAL",
                              "GIT_TERMINAL_PROMPT", "GIT_OPTIONAL_LOCKS"}, set(kwargs["env"]))
            self.assertEqual("/dev/null", kwargs["env"]["GIT_CONFIG_GLOBAL"])
            self.assertEqual("0", kwargs["env"]["GIT_TERMINAL_PROMPT"])
            command = tuple(argv[argv.index("-C") + 2:])
            self.assertIn(command, replies)
            return SimpleNamespace(returncode=0, stdout=replies[command])

        with patch.object(je1.os, "environ", PublicContext(TEST_ONLY_UNREAD_SECRET="synthetic")), \
                patch.object(je1.subprocess, "run", side_effect=read_only_git) as calls:
            source = je1._source_snapshot()
        self.assertEqual(TEST_SOURCE, source)
        self.assertEqual(len(replies), calls.call_count)
        self.assertEqual(allowed_context, set(requested))

    def test_reused_output_directory_untouched(self):
        with tempfile.TemporaryDirectory() as temporary:
            sentinel = Path(temporary) / "sentinel.txt"
            sentinel.write_text("test-only-existing-directory")
            self.assertEqual("OUTPUT_DIRECTORY_REUSED", self.assertPrestart(self.args(Path(temporary)))["reason_code"])
            self.assertEqual("test-only-existing-directory", sentinel.read_text())
            self.assertEqual([sentinel], list(Path(temporary).iterdir()))

    def test_output_inside_source_rejected(self):
        result = self.assertPrestart(self.args(je1._repo_root() / "must-not-exist-je1"))
        self.assertEqual("OUTPUT_MUST_BE_NEW_OUTSIDE_SOURCE", result["reason_code"])

    def test_real_runtime_timestamps_and_sequential_commit(self):
        timestamps = [datetime.fromisoformat(r["committed_at"]) for r in self.records]
        self.assertEqual(timestamps, sorted(timestamps))
        self.assertLess((datetime.now(timezone.utc) - timestamps[0]).total_seconds(), 300)
        snapshots = [json.loads(data) for name, data in self.store.history if name == "judgment-journal.json"]
        self.assertEqual(list(range(7)), [len(s) for s in snapshots])
        for old, new in zip(snapshots, snapshots[1:]):
            self.assertEqual(old, new[:-1])
        start_index = next(i for i, (name, _) in enumerate(self.store.history) if name == "run-start.json")
        first_commit = next(i for i, (name, data) in enumerate(self.store.history)
                            if name == "judgment-journal.json" and json.loads(data))
        self.assertLess(start_index, first_commit)

    def test_partial_failure_preserves_two_commits_and_never_retries(self):
        original = je1.fixture_decision
        calls = []
        def fail_third(*args):
            calls.append(args[2])
            if len(calls) == 3:
                raise ValueError("test-only simulated failure")
            return original(*args)
        with patch.object(je1, "fixture_decision", side_effect=fail_third):
            store, result = memory_simulation(self.bundle)
        self.assertEqual("NOT_EVALUABLE", result["terminal_status"])
        self.assertEqual("PARTIAL", result["completion_status"])
        self.assertEqual(2, result["test_record_count"])
        self.assertEqual(3, result["fixture_decision_calls"])
        self.assertEqual(0, result["automatic_retries"])
        self.assertEqual(2, len(json.loads(store.read("judgment-journal.json"))))
        self.assertTrue(store.exists("run-start.json"))
        self.assertTrue(store.exists("post-run-receipt.json"))

    def test_post_replace_failure_reads_durable_journal_instead_of_old_memory(self):
        class FailsAfterCommit(MemoryStore):
            def write(self, name, data, *, replace=False):
                super().write(name, data, replace=replace)
                if name == "judgment-journal.json" and len(json.loads(data)) == 2:
                    raise OSError("simulated directory fsync failure")
        store, result = memory_simulation(self.bundle, FailsAfterCommit())
        self.assertEqual(2, result["test_record_count"])
        self.assertEqual(2, len(json.loads(store.read("judgment-journal.json"))))
        self.assertEqual("NOT_EVALUABLE", result["terminal_status"])

    def test_source_drift_stops_before_the_next_decision(self):
        store = MemoryStore()
        je1._write_json(store, "preflight.json", {"test_only": True})
        drifted = {**TEST_SOURCE, "head": "0" * 40}
        with patch.object(je1, "_source_snapshot", side_effect=[TEST_SOURCE, drifted, drifted]):
            receipt = je1._execute(store, self.bundle, TEST_SOURCE, TEST_AUTHORITY)
        self.assertEqual("MIDRUN_SOURCE_OR_PACKAGE_DRIFT", receipt["reason_code"])
        self.assertEqual("NOT_EVALUABLE", receipt["terminal_status"])
        self.assertEqual(1, receipt["fixture_decision_calls"])
        self.assertEqual(1, receipt["test_record_count"])
        self.assertEqual(0, receipt["automatic_retries"])
        self.assertEqual(1, len(json.loads(store.read("judgment-journal.json"))))

    def test_prestart_marker_failure_has_zero_formal_records(self):
        class NoStart(MemoryStore):
            def write(self, name, data, *, replace=False):
                if name == "run-start.json":
                    raise OSError("test-only storage failure")
                super().write(name, data, replace=replace)
        store, receipt = memory_simulation(self.bundle, NoStart())
        self.assertEqual("PRESTART_NOT_EVALUABLE", receipt["terminal_status"])
        self.assertEqual(0, receipt["formal_record_count"])
        self.assertEqual(0, receipt["fixture_decision_calls"])
        self.assertFalse(store.exists("run-start.json"))

    def test_each_missing_or_failed_j_gate_is_not_evaluable(self):
        checks = json.loads(self.store.read("integrity-checks.json"))
        self.assertEqual("PASS", integrity_gate(checks))
        for key in checks:
            for bad in ({"status": "FAIL", "evidence": checks[key]["evidence"]},
                        {"status": "PASS", "evidence": []}):
                with self.subTest(gate=key, bad=bad):
                    self.assertEqual("NOT_EVALUABLE", integrity_gate({**checks, key: bad}))

    def test_integrity_uses_actual_delivery_source_and_journal_evidence(self):
        start = json.loads(self.store.read("run-start.json"))
        end = json.loads(self.store.read("run-end.json"))
        deliveries = json.loads(self.store.read("input-delivery-audit.json"))
        leakage = json.loads(self.store.read("leakage-audit.json"))
        resources = json.loads(self.store.read("resource-receipt.json"))
        args = [self.bundle, start, end, self.entries, deliveries, leakage, resources]
        for index, replacement in ((3, self.entries[:-1]), (4, deliveries[:-1]),
                                   (5, {**leakage, "provenance_absent": False}),
                                   (2, {**end, "source": {**TEST_SOURCE, "head": "0" * 40}})):
            changed = args.copy()
            changed[index] = replacement
            with self.subTest(index=index):
                self.assertEqual("NOT_EVALUABLE", integrity_gate(je1._integrity(*changed)))

    def test_nonzero_resource_counters_reject_candidate(self):
        for key in je1.ZERO_COUNTERS:
            resources = je1._resource_receipt(6)
            resources[key] = 1
            self.assertFalse(je1._zero_resources(resources), key)
        for delta in ({"external_tools": ["tool"]}, {"spend": {"value": 1, "currency": "USD"}},
                      {"official_prompt_consumed": True}, {"hidden_registry_loaded": True}):
            self.assertFalse(je1._zero_resources({**je1._resource_receipt(6), **delta}))

    def test_network_and_environment_capabilities_are_trapped(self):
        for action in (lambda: socket.socket(), lambda: os.getenv("TEST_ONLY_ENV_NAME"),
                       lambda: Path("/not-read-test-only").read_text()):
            resources = je1._resource_receipt()
            with self.subTest(action=action), self.assertRaises(je1.GateError):
                with je1._decision_guard(resources):
                    action()
            self.assertFalse(je1._zero_resources(resources))

    def test_forbidden_decision_capability_causes_partial_without_retry(self):
        with patch.object(je1, "fixture_decision", side_effect=lambda *args: socket.socket()):
            store, receipt = memory_simulation(self.bundle)
        self.assertEqual("NOT_EVALUABLE", receipt["terminal_status"])
        self.assertEqual(1, receipt["network_calls"])
        self.assertEqual(1, receipt["fixture_decision_calls"])
        self.assertEqual(0, receipt["test_record_count"])

    def test_manifest_covers_every_emitted_payload_file(self):
        manifest = self.store.read("MANIFEST.sha256").decode().splitlines()
        expected = {name for name in self.store.names() if name != "MANIFEST.sha256"}
        self.assertEqual(expected, {line.split("  ", 1)[1] for line in manifest})
        for line in manifest:
            digest, name = line.split("  ", 1)
            self.assertEqual(digest, hashlib.sha256(self.store.read(name)).hexdigest())
        self.assertEqual(11, len(self.store.names()))

    def test_durable_writer_atomic_replace_fsync_and_overwrite_guard(self):
        # Generic storage bytes only; no JE1 marker/record is written to disk.
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "generic-storage-test"
            with patch("os.fsync", wraps=os.fsync) as fsync, patch("os.replace", wraps=os.replace) as replace:
                store = je1._DiskStore(root)
                store.write("checkpoint.txt", b"synthetic old")
                self.assertGreaterEqual(fsync.call_count, 3)
                self.assertEqual(1, replace.call_count)
                with self.assertRaises(je1.GateError):
                    store.write("checkpoint.txt", b"not permitted")
                with patch("os.replace", side_effect=OSError("test-only atomic failure")), self.assertRaises(OSError):
                    store.write("checkpoint.txt", b"synthetic new", replace=True)
                self.assertEqual(b"synthetic old", store.read("checkpoint.txt"))
                self.assertEqual(["checkpoint.txt"], store.names())


if __name__ == "__main__":
    unittest.main()
