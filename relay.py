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
def state(p):
 if not p.exists(): return {"schemaVersion":1,"events":{}}
 s=readj(p)
 if set(s)!={"schemaVersion","events"} or s.get("schemaVersion")!=1 or not isinstance(s["events"],dict): raise RelayError("invalid state structure")
 for eid,r in s["events"].items():
  if not isinstance(r,dict) or set(r)!={"dedupeKey","event","status","attempts","acknowledgement"} or r["status"] not in ("pending","acknowledged") or type(r["attempts"]) is not int or r["attempts"]<0 or not isinstance(r["event"],dict) or r["event"].get("eventId")!=eid or not isinstance(r["dedupeKey"],str): raise RelayError("invalid event state record")
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
 c=config(cp);s=state(sp);k,e=observe(c,fp);eid=e["eventId"]
 if eid in s["events"]:
  if s["events"][eid]["dedupeKey"]!=k:raise RelayError("event identity conflict")
 else:s["events"][eid]={"dedupeKey":k,"event":e,"status":"pending","attempts":0,"acknowledgement":None};save(sp,s)
 return eid,deliver(c,sp,s,eid)
def retry(cp,sp):
 c=config(cp);s=state(sp);return [(eid,deliver(c,sp,s,eid)) for eid,r in list(s["events"].items()) if r["status"]=="pending"]
def status(sp):
 s=state(sp);o={"events":len(s["events"]),"pending":0,"acknowledged":0}
 for r in s["events"].values():o[r["status"]]+=1
 return o
def main():
 p=argparse.ArgumentParser();p.add_argument("--config",type=Path,required=True);p.add_argument("--state",type=Path,required=True);sub=p.add_subparsers(dest="cmd",required=True);q=sub.add_parser("process");q.add_argument("fixture",type=Path);sub.add_parser("retry");sub.add_parser("status");a=p.parse_args()
 try:
  if a.cmd=="process":
   eid,r=process(a.config,a.state,a.fixture);print(json.dumps({"eventId":eid,"result":r},sort_keys=True));return 0 if r!="pending" else 2
  if a.cmd=="retry":
   out=retry(a.config,a.state);print(json.dumps([{"eventId":i,"result":r} for i,r in out],sort_keys=True));return 0 if all(r=="delivered" for _,r in out) else (2 if out else 0)
  print(json.dumps(status(a.state),sort_keys=True));return 0
 except RelayError as e: print("relay error: "+str(e),file=__import__("sys").stderr);return 1
if __name__=="__main__":raise SystemExit(main())
