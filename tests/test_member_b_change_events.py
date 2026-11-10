"""Member B change mapping: ID schemes and the Week 12 change events (CE-01, CE-02)."""
import json
import unittest
from pathlib import Path

from modules.member_b.change import analyse_change, id_scheme

ROOT = Path(__file__).resolve().parents[1]


def plan(wbs, milestones):
    return {"wbs_items": [{"wbs_id": w} for w in wbs],
            "milestones": [{"milestone_id": m} for m in milestones]}


def risks(ids):
    return {"risks": [{"risk_id": r} for r in ids]}


# IDs as produced by planning_risk.py alone (brief-only draft).
BRIEF_PLAN = plan(["1", "1.1", "1.1.1", "1.1.2", "1.2", "1.2.1", "1.2.2", "1.2.3", "1.3", "1.3.1",
                   "1.3.2", "1.3.3", "1.3.4", "1.3.5", "1.4", "1.4.1", "1.4.2"],
                  [f"M{i:02d}" for i in range(1, 10)])
BRIEF_RISK = risks([f"R{i:02d}" for i in range(1, 8)])

# IDs as produced after data_pack.py amends the draft.
PACK_PLAN = plan([w["wbs_id"] for w in BRIEF_PLAN["wbs_items"]] + ["1.2.4", "1.3.6", "1.4.3"],
                 [f"M{i:02d}" for i in range(1, 18)])
PACK_RISK = risks([f"R{i:02d}" for i in range(1, 18)])


class IdSchemeTests(unittest.TestCase):
    def test_detects_both_schemes(self):
        self.assertEqual(id_scheme(BRIEF_PLAN, BRIEF_RISK), "BRIEF_ONLY")
        self.assertEqual(id_scheme(PACK_PLAN, PACK_RISK), "DATA_PACK")

    def test_brief_only_mapping_unchanged(self):
        out = analyse_change({"event_id": "T", "change_type": "LIFT_DELAY"}, BRIEF_PLAN, BRIEF_RISK)
        self.assertEqual(out["stale_risk_ids"], ["R03", "R06"])
        self.assertEqual(out["stale_wbs_ids"], ["1.2.2", "1.4.1"])

    def test_data_pack_lift_delay_uses_pack_risk_ids(self):
        # In the pack scheme R03 is noise complaints and R06 the ageing operator:
        # neither belongs to a lift delay.
        out = analyse_change({"event_id": "T", "change_type": "LIFT_DELAY"}, PACK_PLAN, PACK_RISK)
        self.assertEqual(out["stale_risk_ids"], ["R02", "R11", "R16"])
        self.assertNotIn("R03", out["stale_risk_ids"])

    def test_pack_only_type_is_unclassified_on_brief_only_draft(self):
        out = analyse_change({"event_id": "T", "change_type": "GRANT_ELIGIBILITY_RULING"},
                             BRIEF_PLAN, BRIEF_RISK)
        self.assertEqual(out["status"], "UNCLASSIFIED_REVIEW_REQUIRED")
        self.assertFalse(out["approved"])


class Week12EventTests(unittest.TestCase):
    def load(self, name):
        return json.loads((ROOT / "examples/change_events" / name).read_text(encoding="utf-8"))

    def test_ce01_grant_eligibility_ruling(self):
        out = analyse_change(self.load("CE-01.json"), PACK_PLAN, PACK_RISK)
        self.assertEqual(out["status"], "REVIEW_REQUIRED")
        self.assertEqual(out["classified_as"], "GRANT_ELIGIBILITY_RULING")
        self.assertIn("1.2.4", out["stale_wbs_ids"])
        self.assertIn("1.4.3", out["stale_wbs_ids"])
        for rid in ("R01", "R08", "R09"):
            self.assertIn(rid, out["stale_risk_ids"])
        self.assertIn("M16", out["stale_milestone_ids"])
        notes = " ".join(out["impact_notes"])
        self.assertIn("S$10.2m", notes)
        self.assertIn("UNKNOWN", notes)  # roof strengthening stays unpriced, not zero
        self.assertFalse(out["approved"])

    def test_ce02_operator_withdrawal(self):
        out = analyse_change(self.load("CE-02.json"), PACK_PLAN, PACK_RISK)
        self.assertEqual(out["classified_as"], "OPERATOR_WITHDRAWAL")
        self.assertIn("1.3.3", out["stale_wbs_ids"])
        self.assertIn("M12", out["stale_milestone_ids"])
        for rid in ("R06", "R17"):
            self.assertIn(rid, out["stale_risk_ids"])
        self.assertTrue(any("D14" in a for a in out["human_actions"]))
        self.assertFalse(out["approved"])

    def test_memo_ids_work_as_change_type_aliases(self):
        out = analyse_change({"event_id": "CE-02", "change_type": "CE-02"}, PACK_PLAN, PACK_RISK)
        self.assertEqual(out["classified_as"], "OPERATOR_WITHDRAWAL")
        self.assertEqual(out["change_type"], "CE-02")

    def test_only_existing_ids_are_returned(self):
        small_plan = plan(["1.3.3"], ["M12"])
        out = analyse_change({"event_id": "CE-02", "change_type": "CE-02"}, small_plan, risks(["R06", "R17"]))
        self.assertEqual(out["stale_wbs_ids"], ["1.3.3"])
        self.assertEqual(out["stale_milestone_ids"], ["M12"])
        self.assertEqual(out["stale_risk_ids"], ["R06", "R17"])


if __name__ == "__main__":
    unittest.main()
