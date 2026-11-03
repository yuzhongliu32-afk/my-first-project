"""Local HTTP gateway for Member B, optional to A's direct Python callable.

Run: python -m modules.member_b.http_api --port 8765
GET  /health
POST /v1/plan-risk       {"request": <A's B request>, "context": {...}}
POST /v1/change-impact   {"event": {...}, "planning": {...}, "risk": {...}}

Security: binds loopback by default; no credentials or external writes.
"""
import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from .adapter import run as run_b
from .change import analyse_change

MAX_BODY=5 * 1024 * 1024

class MemberBHTTPHandler(BaseHTTPRequestHandler):
    server_version = "HarbourlineMemberB/1.0"

    def log_message(self, fmt, *args):
        # Avoid printing input contents, which can contain source material.
        pass

    def _send(self, code, payload):
        data=json.dumps(payload,ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type","application/json; charset=utf-8")
        self.send_header("Cache-Control","no-store")
        self.send_header("Content-Length",str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path=="/health":
            self._send(200,{"service":"member-b","status":"ok","endpoints":["POST /v1/plan-risk","POST /v1/change-impact"]})
        else:
            self._send(404,{"error":"Unknown endpoint"})

    def do_POST(self):
        if self.path not in ("/v1/plan-risk","/v1/change-impact"):
            self._send(404,{"error":"Unknown endpoint"})
            return
        try:
            n=int(self.headers.get("Content-Length","-1"))
            if n<0 or n>MAX_BODY:
                self._send(413,{"error":"Content-Length missing or too large"})
                return
            payload=json.loads(self.rfile.read(n))
            if not isinstance(payload,dict):
                raise ValueError("JSON body must be an object")
            if self.path=="/v1/plan-risk":
                request=payload["request"]
                context=payload.get("context",{})
                if not isinstance(request,dict) or not isinstance(context,dict):
                    raise ValueError("request/context must be objects")
                result=run_b(request,context)
                self._send(200 if result.get("status")!="BLOCKED" else 422,result)
            else:
                result=analyse_change(payload["event"],payload["planning"],payload["risk"])
                self._send(200,result)
        except (KeyError,ValueError,TypeError,json.JSONDecodeError) as exc:
            self._send(400,{"error":type(exc).__name__,"message":str(exc)})


def main():
    parser=argparse.ArgumentParser(description="Serve Member B Planning/Risk locally")
    parser.add_argument("--port",type=int,default=8765)
    parser.add_argument("--host",default="127.0.0.1",help="Only localhost is safe without authentication")
    args=parser.parse_args()
    if args.host not in ("127.0.0.1","localhost","::1"):
        parser.error("Unauthenticated demo must bind to localhost; use an authenticated proxy for deployment")
    server=ThreadingHTTPServer((args.host,args.port),MemberBHTTPHandler)
    print(f"Member B HTTP ready at http://{args.host}:{args.port}/health")
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close()

if __name__=="__main__":
    main()
