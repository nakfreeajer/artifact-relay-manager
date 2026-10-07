import hashlib, http.server, json, subprocess, sys, tempfile, threading, unittest
from pathlib import Path
import relay

class Sink(http.server.BaseHTTPRequestHandler):
 seen=[]
 def do_POST(self):
  body=self.rfile.read(int(self.headers["Content-Length"])); self.seen.append((json.loads(body),self.headers.get("Idempotency-Key")))
  self.send_response(200);self.send_header("Content-Type","application/json");self.end_headers();self.wfile.write(b'{"disposition":"RECEIVED"}')
 def log_message(self,*a): pass

class RelayTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.d=Path(self.tmp.name);self.root=self.d/"fixture";self.root.mkdir()
  (self.root/".relay-project.json").write_text(json.dumps({"schemaVersion":1,"projectId":"p1","repository":"org/repo"}))
  (self.root/"body.bin").write_bytes(b"caf\xc3\xa9\r\n")
  self.server=http.server.ThreadingHTTPServer(("127.0.0.1",0),Sink);Sink.seen=[];self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
  self.cp=self.d/"config.json";self.sp=self.d/"state.json";self.fp=self.d/"fixture.json"
  self.config={"schemaVersion":1,"projectId":"p1","repository":"org/repo","fixtureRoot":str(self.root),"watcherEndpoint":f"http://127.0.0.1:{self.server.server_port}/"}
  self.write_config();self.fixture()
 def tearDown(self): self.server.shutdown();self.server.server_close();self.tmp.cleanup()
 def write_config(self): self.cp.write_text(json.dumps(self.config))
 def fixture(self): self.fp.write_text(json.dumps({"providerItemId":"file-1","providerVersion":"v1","eventType":"PROMPT_READY","taskId":"t1","artifactPath":"body.bin"}))
 def run_event(self): return relay.process(self.cp,self.sp,self.fp)
 def test_happy_ack_and_duplicate(self):
  eid,r=self.run_event();self.assertEqual(r,"delivered");self.assertEqual(Sink.seen[0][0]["artifact"]["byteLength"],7);self.assertEqual(Sink.seen[0][0]["artifact"]["sha256"],hashlib.sha256(b"caf\xc3\xa9\r\n").hexdigest())
  self.assertEqual(self.run_event(),(eid,"deduplicated"));self.assertEqual(len(Sink.seen),1)
 def test_project_mismatch(self):
  self.config["projectId"]="wrong";self.write_config()
  with self.assertRaises(relay.RelayError):self.run_event()
  self.assertFalse(Sink.seen)
 def test_repository_mismatch(self):
  self.config["repository"]="other/repo";self.write_config()
  with self.assertRaises(relay.RelayError):self.run_event()
  self.assertFalse(Sink.seen)
 def test_exact_bytes_line_endings(self):
  (self.root/"body.bin").write_bytes("na�ve\n".encode());eid,_=self.run_event();rec=relay.state(self.sp)["events"][eid]["event"]
  self.assertEqual(rec["artifact"]["sha256"],hashlib.sha256("na�ve\n".encode()).hexdigest())
  self.assertNotEqual(rec["artifact"]["sha256"],hashlib.sha256("na�ve\r\n".encode()).hexdigest())
 def test_unavailable_then_fresh_retry_same_id(self):
  self.server.shutdown();eid,result=self.run_event();self.assertEqual(result,"pending");self.assertEqual(relay.status(self.sp)["pending"],1)
  self.server= http.server.ThreadingHTTPServer(("127.0.0.1",self.config_port if False else 0),Sink)
  self.config["watcherEndpoint"]=f"http://127.0.0.1:{self.server.server_port}/";self.write_config()
  th=threading.Thread(target=self.server.serve_forever,daemon=True);th.start()
  got=relay.retry(self.cp,self.sp);self.assertEqual(got,[(eid,"delivered")]);self.assertEqual(Sink.seen[-1][0]["eventId"],eid)
 def test_ack_dedup_after_reload(self):
  eid,_=self.run_event();self.assertEqual(relay.process(self.cp,self.sp,self.fp),(eid,"deduplicated"));self.assertEqual(len(Sink.seen),1)
 def test_corrupt_config_and_state_fail_closed(self):
  self.cp.write_text("{")
  with self.assertRaises(relay.RelayError):self.run_event()
  self.write_config();self.sp.write_text("{")
  with self.assertRaises(relay.RelayError):self.run_event()
  self.assertFalse(Sink.seen)
 def test_log_does_not_expose_body(self):
  self.assertNotIn("caf�",repr(self.run_event()))
 def test_cli_invocation(self):
  result=subprocess.run([sys.executable,str(Path(relay.__file__)),"--config",str(self.cp),"--state",str(self.sp),"process",str(self.fp)],capture_output=True,text=True)
  self.assertEqual(result.returncode,0);self.assertNotIn("caf�",result.stdout+result.stderr)

if __name__=="__main__":unittest.main()
