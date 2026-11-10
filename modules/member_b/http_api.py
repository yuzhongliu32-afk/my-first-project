"""Local-only B HTTP service. Explicit live mode calls OpenAI, rules uses fallback.

Not a public endpoint: binds loopback and does not provide authentication.
POST /v1/plan-risk {request: ..., context: ..., mode: "live"|"rules", model?: ...}
POST /v1/change-impact {event: ..., planning: ..., risk: ...}\nPOST /v1/schedule-forecast {request: ..., context: {planning?,risk?,cutoff?}, scenario?: ...}
"""
import argparse
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from .adapter import run, forecast
from .change import analyse_change

MAX_BODY=5*1024*1024

class MemberBHTTPHandler(BaseHTTPRequestHandler):
    server_version='HarbourlineMemberB/3.0'
    def log_message(self,format,*args):pass
    def send(self,code,payload):
        content=json.dumps(payload,ensure_ascii=False).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type','application/json; charset=utf-8')
        self.send_header('Cache-Control','no-store')
        self.send_header('Content-Length',str(len(content)))
        self.end_headers();self.wfile.write(content)
    def do_GET(self):
        if self.path=='/health':self.send(200,{'service':'member-b','status':'ok','modes':['rules','live']})
        else:self.send(404,{'error':'unknown path'})
    def do_POST(self):
        if self.path not in ('/v1/plan-risk','/v1/change-impact','/v1/schedule-forecast'):
            self.send(404,{'error':'unknown path'});return
        try:
            length=int(self.headers.get('Content-Length','-1'))
            if length<0 or length>MAX_BODY:self.send(413,{'error':'invalid body length'});return
            body=json.loads(self.rfile.read(length))
            if not isinstance(body,dict):raise ValueError('Body must be JSON object')
            if self.path=='/v1/change-impact':
                out=analyse_change(body['event'],body['planning'],body['risk'])
            elif self.path=='/v1/schedule-forecast':
                if not os.getenv('OPENAI_API_KEY') or not (body.get('model') or os.getenv('OPENAI_MODEL')):
                    self.send(503,{'error':'LIVE_MODEL_NOT_CONFIGURED','message':'Existing B OPENAI_API_KEY and OPENAI_MODEL required'})
                    return
                context=body.get('context',{}).copy()
                if body.get('model'):context['model']=body['model']
                if body.get('cutoff'):context['cutoff']=body['cutoff']
                out=forecast(body['request'],context,scenario=body.get('scenario'))
            else:
                context=body.get('context',{}).copy()
                context['mode']=body.get('mode','rules')
                if context['mode']=='live' and (not os.getenv('OPENAI_API_KEY') or not (body.get('model') or os.getenv('OPENAI_MODEL'))):
                    self.send(503,{'error':'LIVE_MODEL_NOT_CONFIGURED','message':'OPENAI_API_KEY and OPENAI_MODEL required; no fake result is returned'})
                    return
                if body.get('model'):context['model']=body['model']
                if body.get('cutoff'):context['cutoff']=body['cutoff']
                out=run(body['request'],context)
            self.send(200 if out.get('status')!='BLOCKED' else 422,out)
        except (KeyError,TypeError,ValueError,json.JSONDecodeError) as exc:
            self.send(400,{'error':type(exc).__name__,'message':str(exc)[:280]})
        except Exception as exc:
            self.send(502,{'error':'LIVE_AGENT_FAILED','type':type(exc).__name__,
              'message':'Generation or validation failed; no rules output was substituted.'})

def main():
    parser=argparse.ArgumentParser(description='Local Member B HTTP server')
    parser.add_argument('--host',default='127.0.0.1')
    parser.add_argument('--port',type=int,default=8765)
    args=parser.parse_args()
    if args.host not in ('127.0.0.1','localhost','::1'):
        parser.error('Do not expose an unauthenticated LLM endpoint to the internet')
    server=ThreadingHTTPServer((args.host,args.port),MemberBHTTPHandler)
    print(f'B HTTP: http://{args.host}:{args.port}/health')
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close()

if __name__=='__main__':main()
