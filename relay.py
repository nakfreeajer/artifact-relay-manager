import argparse, hashlib, json, os, re, tempfile, urllib.error, urllib.request
from datetime import datetime, timezone
from pathlib import Path
MAX_BYTES=1048576
EVENTS={"PROMPT_READY","RESULT_READY","HANDOVER_READY","SYSTEM_SNAPSHOT_READY","ARTIFACT_CHANGED","PROJECT_IDENTITY_CHANGED"}
ACKS={"RECEIVED","QUEUED","REJECTED","DUPLICATE"}
class RelayError(Exception): pass
def readj(p):
 try: v=json.loads(p.read_text(encoding="utf-8"))
 except (OSError,UnicodeError,json.JSONDecodeError) as e: raise RelayError(f"invalid JSON file: {p}") from e
 if not isinstance(v,dict): raise RelayError("expected JSON object")
 return v
def save(p,v):
 p.parent.mkdir(parents=True,exist_ok=True); fd,t=tempfile.mkstemp(dir=p.parent,prefix="."+p.name+".")
 try:
  with os.fdopen(fd,"w",encoding="utf-8",newline="\n") as f: f.write(json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(",",":"))+"\n"); f.flush(); os.fsync(f.fileno())
  os.replace(t,p)
 except Exception:
  try: os.unlink(t)
  except OSError: pass
  raise
def config(p):
 c=readj(p)
 if set(c)!={"schemaVersion","projectId","repository","fixtureRoot","watcherEndpoint"} or c.get("schemaVersion")!=1: raise RelayError("invalid config structure")
 if not isinstance(c["projectId"],str) or not re.fullmatch(r"[A-Za-z0-9._-]+",c["projectId"]): raise RelayError("invalid projectId")
 if not isinstance(c["repository"],str) or not re.fullmatch(r"[^/\\s]+/[^/\\s]+",c["repository"]): raise RelayError("invalid repository")
 if not isinstance(c["fixtureRoot"],str): raise RelayError("invalid fixtureRoot")
 r=Path(c["fixtureRoot"]); c["_root"]=(p.parent/r).resolve() if not r.is_absolute() else r.resolve()
 if not isinstance(c["watcherEndpoint"],str) or not re.fullmatch(r"http://(?:127\.0\.0\.1|localhost):\d+(?:/[^\s]*)?",c["watcherEndpoint"]): raise RelayError("Watcher must use loopback HTTP")
 return c
def validate_record(eid,r,project_id=None):
 if not isinstance(r,dict) or set(r)!={"dedupeKey","event","status","attempts","acknowledgement"} or r.get("status") not in ("pending","acknowledged") or type(r.get("attempts")) is not int or r["attempts"]<0 or not isinstance(r.get("event"),dict) or not isinstance(r.get("dedupeKey"),str): raise RelayError("invalid event state record")
 e=r["event"]
 required={"schemaVersion","eventId","projectId","eventType","taskId","artifact","provider","observedAt"}
 if set(e)!=required or e.get("schemaVersion")!=1 or not isinstance(e.get("eventId"),str) or not isinstance(e.get("projectId"),str) or e.get("eventType") not in EVENTS or (e.get("taskId") is not None and not isinstance(e.get("taskId"),str)): raise RelayError("invalid normalized event")
 a=e.get("artifact"); p=e.get("provider")
 if not isinstance(a,dict) or set(a)!={"artifactId","sha256","byteLength"} or not isinstance(a.get("artifactId"),str) or not a["artifactId"] or not isinstance(a.get("sha256"),str) or not re.fullmatch(r"[0-9a-fA-F]{64}",a["sha256"]) or type(a.get("byteLength")) is not int or a["byteLength"]<0: raise RelayError("invalid normalized artifact")
 if not isinstance(p,dict) or set(p)!={"kind","version"} or p.get("kind")!="google-drive" or not isinstance(p.get("version"),str) or not p["version"]: raise RelayError("invalid normalized provider")
 if not isinstance(e.get("observedAt"),str): raise RelayError("invalid normalized timestamp")
 try: observed=datetime.fromisoformat(e["observedAt"].replace("Z","+00:00"))
 except ValueError as exc: raise RelayError("invalid normalized timestamp") from exc
 if observed.tzinfo is None: raise RelayError("normalized timestamp must include timezone")
 try: key=json.loads(r["dedupeKey"])
 except json.JSONDecodeError as exc: raise RelayError("invalid dedupe identity") from exc
 if not isinstance(key,list) or len(key)!=4 or not all(isinstance(x,str) and x for x in key): raise RelayError("invalid dedupe identity")
 if key!=[e["projectId"],a["artifactId"],p["version"],e["eventType"]]: raise RelayError("event/dedupe identity mismatch")
 expected="relay-"+hashlib.sha256(r["dedupeKey"].encode("utf-8")).hexdigest()
 if eid!=expected or e["eventId"]!=expected: raise RelayError("event id/dedupe identity mismatch")
 if project_id is not None and e["projectId"]!=project_id: raise RelayError("persisted event belongs to another project")
 if r["status"]=="acknowledged" and (not isinstance(r["acknowledgement"],str) or r["acknowledgement"] not in ACKS): raise RelayError("invalid persisted acknowledgement")
 if r["status"]=="pending" and r["acknowledgement"] is not None: raise RelayError("pending event has acknowledgement")

def state(p,project_id=None):
 if not p.exists(): return {"schemaVersion":1,"events":{}}
 s=readj(p)
 if set(s)!={"schemaVersion","events"} or s.get("schemaVersion")!=1 or not isinstance(s["events"],dict): raise RelayError("invalid state structure")
 for eid,r in s["events"].items(): validate_record(eid,r,project_id)
 return s
def observe(c,fp):
 f=readj(fp)
 if set(f)!={"providerItemId","providerVersion","eventType","taskId","artifactPath"}: raise RelayError("invalid fixture fields")
 if not all(isinstance(f[k],str) and f[k] for k in ("providerItemId","providerVersion")) or f["eventType"] not in EVENTS or (f["taskId"] is not None and not isinstance(f["taskId"],str)): raise RelayError("invalid observation values")
 i=readj(c["_root"]/".relay-project.json")
 if set(i)!={"schemaVersion","projectId","repository"} or i!={"schemaVersion":1,"projectId":c["projectId"],"repository":c["repository"]}: raise RelayError("project/repository identity mismatch")
 if not isinstance(f["artifactPath"],str) or not f["artifactPath"]: raise RelayError("invalid artifact path")
 a=(c["_root"]/f["artifactPath"]).resolve()
 try:a.relative_to(c["_root"])
 except ValueError as e: raise RelayError("artifact outside fixture root") from e
 if not a.is_file(): raise RelayError("artifact missing")
 with a.open("rb") as x: b=x.read(MAX_BYTES+1)
 if len(b)>MAX_BYTES: raise RelayError("artifact exceeds size limit")
 k=json.dumps([c["projectId"],f["providerItemId"],f["providerVersion"],f["eventType"]],ensure_ascii=False,separators=(",",":")); eid="relay-"+hashlib.sha256(k.encode()).hexdigest()
 e={"schemaVersion":1,"eventId":eid,"projectId":c["projectId"],"eventType":f["eventType"],"taskId":f["taskId"],"artifact":{"artifactId":f["providerItemId"],"sha256":hashlib.sha256(b).hexdigest(),"byteLength":len(b)},"provider":{"kind":"google-drive","version":f["providerVersion"]},"observedAt":datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00","Z")}
 return k,e
def deliver(c,sp,s,eid):
 r=s["events"][eid]
 if r["status"]=="acknowledged": return "deduplicated"
 r["attempts"]+=1; save(sp,s)
 q=urllib.request.Request(c["watcherEndpoint"],data=(json.dumps(r["event"],ensure_ascii=False,sort_keys=True)+"\n").encode(),headers={"Content-Type":"application/json","Idempotency-Key":eid},method="POST")
 try:
  with urllib.request.urlopen(q,timeout=2) as x:
   if not 200<=x.status<300:return "pending"
   ack=json.loads(x.read(65536).decode())
 except (OSError,urllib.error.URLError,UnicodeError,json.JSONDecodeError,TimeoutError): return "pending"
 if not isinstance(ack,dict) or set(ack)!={"disposition"} or ack["disposition"] not in ACKS:return "pending"
 r["status"]="acknowledged";r["acknowledgement"]=ack["disposition"];save(sp,s);return "delivered"
def process(cp,sp,fp):
 c=config(cp);s=state(sp,c["projectId"]);k,e=observe(c,fp);eid=e["eventId"]
 if eid in s["events"]:
  if s["events"][eid]["dedupeKey"]!=k:raise RelayError("event identity conflict")
 else:s["events"][eid]={"dedupeKey":k,"event":e,"status":"pending","attempts":0,"acknowledgement":None};save(sp,s)
 return eid,deliver(c,sp,s,eid)
def retry(cp,sp):
 c=config(cp);s=state(sp,c["projectId"]);return [(eid,deliver(c,sp,s,eid)) for eid,r in list(s["events"].items()) if r["status"]=="pending"]
def status(sp):
 s=state(sp);o={"events":len(s["events"]),"pending":0,"acknowledged":0}
 for r in s["events"].values():o[r["status"]]+=1
 return o
def main():
 p=argparse.ArgumentParser();p.add_argument("--config",type=Path,required=True);p.add_argument("--state",type=Path);sub=p.add_subparsers(dest="cmd",required=True);q=sub.add_parser("process");q.add_argument("fixture",type=Path);sub.add_parser("retry");sub.add_parser("status");drive=sub.add_parser("poll-drive");drive.add_argument("--api-base-url",help="test-only HTTP loopback Drive API base URL");qualify=sub.add_parser("qualify-drive");qualify.add_argument("--qualification-file-id",required=True);qualify.add_argument("--api-base-url",help="test-only HTTP loopback Drive API base URL");a=p.parse_args()
 try:
  if a.cmd != "qualify-drive" and a.state is None: raise RelayError("--state is required for this command")
  if a.cmd=="process":
   eid,r=process(a.config,a.state,a.fixture);print(json.dumps({"eventId":eid,"result":r},sort_keys=True));return 0 if r!="pending" else 2
  if a.cmd=="retry":
   out=retry(a.config,a.state);print(json.dumps([{"eventId":i,"result":r} for i,r in out],sort_keys=True));return 0 if all(r=="delivered" for _,r in out) else (2 if out else 0)
  if a.cmd=="poll-drive":
   import drive_adapter
   out=drive_adapter.poll_drive(a.config,a.state,api_base_url=a.api_base_url);print(json.dumps(out,sort_keys=True));return 0
  if a.cmd=="qualify-drive":
   import drive_adapter, drive_auth
   token=drive_auth.get_access_token()
   out=drive_adapter.qualify_drive(a.config,a.qualification_file_id,token,api_base_url=a.api_base_url);print(json.dumps(out,sort_keys=True));return 0
  print(json.dumps(status(a.state),sort_keys=True));return 0
 except RelayError as e: print("relay error: "+str(e),file=__import__("sys").stderr);return 1
if __name__=="__main__":raise SystemExit(main())
