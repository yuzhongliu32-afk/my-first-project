"""Supplement tests use model doubles, never real OpenAI or live Jira."""
import copy
import unittest
from modules.member_b.schedule_forecast import compute_network, generate_forecast
from modules.member_b.adapter import forecast
from test_member_b_dynamic_ai import FakeLibrary, request


REF = {"document_id":"TEST","source_type":"BRIEF","page":1}


def task(task_id, duration, predecessors=()):
    return {"id":task_id,"wbs_id":None,"duration_days":duration,
            "predecessors":list(predecessors),"source_refs":[REF]}


def sample_activities():
    return [task("A",4),task("B",6,["A"]),task("C",3,["A"]),
            task("D",8,["B","C"]),task("E",2,["D"])]


class GatewayDouble:
    def __init__(self, proposal):
        self.proposal=copy.deepcopy(proposal)
        self.calls=[]
    def ask(self,name,shape,instructions,payload):
        self.calls.append((name,payload))
        return copy.deepcopy(self.proposal)
    def metrics(self):
        return {"api_calls":0,"input_tokens":0,"output_tokens":0,
                "estimated_cost_usd":0.0}


def model_proposal():
    return {"anchor_date":"2027-01-04","anchor_source_ids":["E001"],
            "activities":[{"id":x["id"],"wbs_id":None,
                "duration_days":x["duration_days"],
                "predecessors":x["predecessors"],"source_ids":["E001"]}
                for x in sample_activities()],
            "external_triggers":[{"id":"GRANT","date":"2027-01-24","source_ids":["E001"]}],
            "driving_assumption":"Durations are illustrative and must be confirmed.",
            "unresolved":[]}


class ScheduleForecastTests(unittest.TestCase):
    def test_cpm_critical_path_float_and_external_trigger(self):
        out=compute_network(sample_activities(),"2027-01-04",
            [{"id":"GRANT","date":"2027-01-24","source_refs":[REF]}])
        self.assertEqual(out["completion_offset_days"],20)
        self.assertEqual(out["forecast_finish"],"2027-01-24")
        self.assertEqual(out["critical_activity_ids"],["A","B","D","E"])
        c=next(x for x in out["activities"] if x["id"]=="C")
        self.assertEqual(c["total_float_days"],3)
        self.assertEqual(out["external_trigger_float"][0]["float_to_trigger_days"],0)

    def test_delay_on_noncritical_task_under_float_does_not_move_finish(self):
        out=compute_network(sample_activities(),"2027-01-04",
                            scenario={"scenario_id":"X","activity_id":"C","additional_days":2})
        self.assertEqual(out["scenario"]["project_finish_shift_days"],0)

    def test_delay_above_float_and_critical_delay(self):
        out=compute_network(sample_activities(),"2027-01-04",
                            scenario={"activity_id":"C","additional_days":4})
        self.assertEqual(out["scenario"]["project_finish_shift_days"],1)
        out=compute_network(sample_activities(),"2027-01-04",
                            scenario={"activity_id":"B","additional_days":2})
        self.assertEqual(out["scenario"]["project_finish_shift_days"],2)

    def test_cycle_and_unknown_dependency_rejected(self):
        with self.assertRaisesRegex(ValueError,"cycle"):
            compute_network([task("A",3,["B"]),task("B",4,["A"])],"2027-01-04")
        with self.assertRaisesRegex(ValueError,"predecessor"):
            compute_network([task("A",3,["X"])],"2027-01-04")

    def test_scenario_unknown_activity_rejected(self):
        with self.assertRaisesRegex(ValueError,"Scenario"):
            compute_network(sample_activities(),"2027-01-04",
                            scenario={"activity_id":"NOPE","additional_days":42})

    def test_b_adapter_uses_existing_model_gateway(self):
        gw=GatewayDouble(model_proposal())
        out=forecast(request(),{"cutoff":None,"evidence_library":FakeLibrary()},gateway=gw)
        self.assertEqual(out["status"],"PROPOSED")
        self.assertEqual(out["forecast"]["completion_offset_days"],20)
        self.assertEqual(gw.calls[0][0],"harbourline_b_schedule")
        self.assertEqual(out["source_snapshot_id"],"SRC-TEST-ONLY")

    def test_conflicting_dates_do_not_create_a_false_forecast(self):
        p=model_proposal()
        p["anchor_date"]=None
        p["anchor_source_ids"]=[]
        p["unresolved"]=["Contract schedule conflicts with contractor report"]
        gw=GatewayDouble(p)
        out=generate_forecast(request(), FakeLibrary(), gw)
        self.assertEqual(out["status"],"UNRESOLVED")
        self.assertIsNone(out["forecast"])

    def test_missing_duration_is_unresolved(self):
        p=model_proposal()
        p["activities"][0]["duration_days"]=None
        out=generate_forecast(request(),FakeLibrary(),GatewayDouble(p))
        self.assertEqual(out["status"],"UNRESOLVED")
        self.assertIsNone(out["forecast"])

    def test_unknown_evidence_id_is_rejected(self):
        p=model_proposal()
        p["activities"][0]["source_ids"]=["E999"]
        with self.assertRaisesRegex(ValueError,"nonexistent evidence ID"):
            generate_forecast(request(),FakeLibrary(),GatewayDouble(p))

    def test_source_snapshot_mismatch_rejected(self):
        req=request()
        req["source_snapshot_id"]="MISMATCH"
        with self.assertRaisesRegex(ValueError,"snapshot mismatch"):
            generate_forecast(req,FakeLibrary(),GatewayDouble(model_proposal()))

    def test_trigger_without_date_does_not_fake_float(self):
        p=model_proposal()
        p["external_triggers"][0]["date"]=None
        out=generate_forecast(request(),FakeLibrary(),GatewayDouble(p))
        self.assertEqual(out["status"],"UNRESOLVED")


if __name__=="__main__":
    unittest.main()
