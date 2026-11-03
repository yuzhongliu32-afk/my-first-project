"""Tests for B's optional local HTTP interface; require no source pack."""
import http.client
import json
import threading
import unittest
from http.server import ThreadingHTTPServer
from modules.member_b.http_api import MemberBHTTPHandler

class MemberBHttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server=ThreadingHTTPServer(("127.0.0.1",0),MemberBHTTPHandler)
        cls.port=cls.server.server_address[1]
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown(); cls.server.server_close(); cls.thread.join(timeout=2)

    def call(self,method,path,body=None):
        connection=http.client.HTTPConnection("127.0.0.1",self.port,timeout=5)
        payload=None if body is None else json.dumps(body)
        connection.request(method,path,body=payload,headers={"Content-Type":"application/json"})
        resp=connection.getresponse()
        status=resp.status
        result=json.loads(resp.read())
        connection.close()
        return status,result

    def test_health(self):
        status,body=self.call("GET","/health")
        self.assertEqual(status,200)
        self.assertEqual(body["service"],"member-b")

    def test_missing_input_is_validation_error(self):
        status,body=self.call("POST","/v1/plan-risk",{})
        self.assertEqual(status,400)
        self.assertEqual(body["error"],"KeyError")

    def test_unknown_route(self):
        status,body=self.call("POST","/v1/invalid",{})
        self.assertEqual(status,404)

    def test_safe_change_impact_response(self):
        status,body=self.call("POST","/v1/change-impact",{
            "event":{"event_id":"TEST-UNKNOWN","change_type":"UNCLASSIFIED"},
            "planning":{"wbs_items":[],"milestones":[]},
            "risk":{"risks":[]}})
        self.assertEqual(status,200)
        self.assertFalse(body["approved"])

if __name__=="__main__": unittest.main()
