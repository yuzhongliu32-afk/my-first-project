from copy import deepcopy
import json
from pathlib import Path
import unittest
from harbourline.contracts import ContractError, check_schemas, common_projection, validate, verify_evidence
from harbourline.integration import aggregate, empty_backend, run_handoff
from modules.member_b.adapter import run as run_b
from modules.member_c.adapter import run as run_c

ROOT = Path(__file__).resolve().parents[1]


def fixture(name):
    return json.loads((ROOT / "examples" / name).read_text())


class BoundaryTests(unittest.TestCase):
    def setUp(self):
        self.common = fixture("request.json")
        self.b = fixture("b_output.json")
        self.c = fixture("c_output.json")
        self.a = empty_backend(self.common)

    def reject_b(self, mutate):
        mutate(self.b)
        with self.assertRaises(ContractError):
            validate(self.b, "B", expected_producer="B")

    def test_meta_schemas(self):
        check_schemas()

    def test_module_fixtures(self):
        validate(self.b, "B", expected_producer="B")
        validate(self.c, "C", expected_producer="C")
        validate(self.a, "A", expected_producer="A")

    def test_common_requires_projection(self):
        with self.assertRaises(ContractError):
            validate(self.b, "Common")
        validate(common_projection(self.b), "Common")

    def test_no_extra_governance_in_b(self):
        self.reject_b(lambda b: b.update(governance={"approvals": []}))

    def test_no_extra_governance_in_c(self):
        self.c["governance"] = self.a["governance"]
        with self.assertRaises(ContractError):
            aggregate(self.a, self.b, self.c)

    def test_wrong_producer(self):
        self.reject_b(lambda b: b.update(producer="A"))

    def test_empty_run_id(self):
        self.reject_b(lambda b: b.update(run_id=""))

    def test_duplicate_work_id(self):
        self.reject_b(lambda b: b["planning"]["wbs_items"].append(deepcopy(b["planning"]["wbs_items"][0])))

    def test_wrong_parent(self):
        self.reject_b(lambda b: b["planning"]["wbs_items"][2].update(parent_wbs_id="MISSING"))

    def test_wbs_level(self):
        self.reject_b(lambda b: b["planning"]["wbs_items"][0].update(level=9))

    def test_dependency_cycle(self):
        self.reject_b(lambda b: b["planning"]["wbs_items"][0].update(predecessor_wbs_ids=["FIXTURE-W1"]))

    def test_unknown_dependency(self):
        self.reject_b(lambda b: b["planning"]["wbs_items"][0].update(predecessor_wbs_ids=["UNKNOWN"]))

    def test_risk_reference(self):
        self.reject_b(lambda b: b["risk"]["risks"][0].update(related_wbs_ids=["UNKNOWN"]))

    def test_risk_arithmetic(self):
        self.reject_b(lambda b: b["risk"]["risks"][0].update(probability=3, impact=4, score=9))

    def test_risk_arithmetic_valid(self):
        self.b["risk"]["risks"][0].update(probability=3, impact=4, score=12)
        validate(self.b, "B")

    def test_partial_risk_rating(self):
        self.reject_b(lambda b: b["risk"]["risks"][0].update(probability=3, impact=None, score=3))

    def test_negative_metric(self):
        self.reject_b(lambda b: b["metrics"].update(api_calls=-1))

    def test_invalid_date(self):
        self.reject_b(lambda b: b["request"]["reporting_period"].update(start_date="2026-02-30"))

    def test_reversed_period(self):
        self.reject_b(lambda b: b["request"]["reporting_period"].update(start_date="2026-11-03", end_date="2026-11-01"))

    def test_unknown_metrics_remain_null(self):
        full = aggregate(self.a, self.b, self.c)
        self.assertIsNone(full["metrics"]["estimated_cost_usd"])
        self.assertEqual(full["metrics"]["api_calls"], 0)

    def test_mixed_snapshot_rejected(self):
        self.b["source_snapshot_id"] = "OTHER"
        with self.assertRaises(ContractError):
            aggregate(self.a, self.b, self.c)

    def test_mixed_run_rejected(self):
        self.b["run_id"] = "OTHER"
        with self.assertRaises(ContractError):
            aggregate(self.a, self.b, self.c)

    def test_changed_request_rejected(self):
        self.b["request"]["instructions"] = "Changed"
        with self.assertRaises(ContractError):
            aggregate(self.a, self.b, self.c)

    def test_module_status_propagated(self):
        self.c["status"] = "BLOCKED"
        self.assertEqual(aggregate(self.a, self.b, self.c)["status"], "BLOCKED")

    def test_inputs_not_mutated_by_aggregation(self):
        before = deepcopy(self.a)
        aggregate(self.a, self.b, self.c)
        self.assertEqual(self.a, before)

    def test_ready_report_without_review(self):
        self.c["reporting"]["reports"][0]["status"] = "READY_FOR_HUMAN_REVIEW"
        with self.assertRaises(ContractError):
            validate(self.c, "C")

    def test_report_snapshot_mismatch(self):
        self.c["reporting"]["reports"][0]["source_snapshot_id"] = "OTHER"
        with self.assertRaises(ContractError):
            validate(self.c, "C")

    def test_fake_fact_reference(self):
        self.c["reporting"]["reports"][0]["included_fact_ids"] = ["MISSING"]
        with self.assertRaises(ContractError):
            validate(self.c, "C")

    def test_automatic_handoff_consumes_b_context(self):
        full, trace = run_handoff(self.common, run_b, run_c, {})
        self.assertTrue(full["integration"]["handoff_completed"])
        self.assertEqual([t["event"] for t in trace], ["B_OUTPUT_VALIDATED", "A_HANDOFF_TO_C", "C_OUTPUT_VALIDATED"])
        self.assertIn("3 proposed WBS items", full["memory"]["open_questions"][-1])
        self.assertEqual(full["governance"]["approvals"], [])
        self.assertEqual(full["integration"]["jira_actions"], [])

    def test_blocked_b_stops_c(self):
        called = []
        def b(req, ctx):
            out = run_b(req, ctx)
            out["status"] = "BLOCKED"
            return out
        def c(req, ctx):
            called.append(True)
            return run_c(req, ctx)
        with self.assertRaises(ContractError):
            run_handoff(self.common, b, c, {})
        self.assertFalse(called)

    def test_misrouted_b_stops_c(self):
        def b(req, ctx):
            out = run_b(req, ctx)
            out["recipient"] = "C"
            return out
        with self.assertRaises(ContractError):
            run_handoff(self.common, b, run_c, {})

    def test_exact_evidence_quote(self):
        evidence = {"source_evidence": [{"document_id": "FIXTURE", "document_version": "1", "source_type": "BRIEF",
                    "page": None, "line_start": 1, "line_end": 1, "chunk_id": None, "quote": "Test fixture only."}]}
        verify_evidence(evidence, {("FIXTURE", "1"): ["Test fixture only."]})
        evidence["source_evidence"][0]["quote"] = "Invented quote"
        with self.assertRaises(ContractError):
            verify_evidence(evidence, {("FIXTURE", "1"): ["Test fixture only."]})

    def test_unloaded_evidence_version(self):
        with self.assertRaises(ContractError):
            verify_evidence({"source_evidence": [{"document_id": "FIXTURE", "document_version": "2", "source_type": "BRIEF"}]}, {})

    def test_oversized_source_line(self):
        with self.assertRaises(ContractError):
            verify_evidence({"source_evidence": [{"document_id": "FIXTURE", "document_version": "1", "source_type": "BRIEF",
                             "line_start": 1, "line_end": 5, "quote": "Test"}]}, {("FIXTURE", "1"): ["Test"]})


if __name__ == "__main__":
    unittest.main()
