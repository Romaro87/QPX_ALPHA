#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, os, re, signal, subprocess, sys, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent
SYMBOLS = ROOT/"qpx_bot"/"symbols.json"
PAPER = ROOT/"QPX_CANDIDATE_V1_PAPER.py"
LAUNCHER = ROOT/"QPX_START_CANDIDATE_V1.sh"
POLICY = ROOT/"qpx_bot"/"candidate_v1_policy.json"
REPORT = ROOT/"reports"/"qpx_candidate_v1_forward"/"latest_15m_paper_status.json"
ACCOUNT = ROOT/"qpx_bot"/"candidate_v1_runtime"/"paper_state.json"
BOT_LOG = ROOT/"logs"/"qpx_candidate_v1"/"forward_paper.log"
RUNTIME = ROOT/"qpx_gui_runtime"
PID_FILE = RUNTIME/"paper_launcher.pid"
SYM_RE = re.compile(r"^[A-Z0-9.^/_=-]{1,24}$")

HTML = """<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>QPX Control Center</title>
<style>:root{color-scheme:dark;--b:#0b0e14;--p:#131823;--l:#263042;--m:#8d9bb0;--g:#55d68b;--w:#f7c65f;--r:#ff6b72;--t:#eef3fb;--a:#77a7ff}*{box-sizing:border-box}body{margin:0;background:var(--b);color:var(--t);font-family:system-ui,sans-serif}main{max-width:980px;margin:auto;padding:18px}.top{display:flex;justify-content:space-between;gap:10px;flex-wrap:wrap}.sub,.tiny{color:var(--m);font-size:.82rem}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:12px;margin-top:14px}.card{background:var(--p);border:1px solid var(--l);border-radius:14px;padding:14px}.wide{grid-column:1/-1}.label{color:var(--m);font-size:.75rem;text-transform:uppercase;letter-spacing:.08em}.value{font-size:1.15rem;margin-top:5px}.good{color:var(--g)}.warn{color:var(--w)}button{border:0;border-radius:9px;padding:10px 12px;background:var(--a);font-weight:700;margin:4px 5px 4px 0}button.secondary{background:#273247;color:var(--t)}button.danger{background:#7e2f38;color:white}button:disabled{opacity:.45}input{width:100%;background:#0e131d;color:var(--t);border:1px solid var(--l);border-radius:9px;padding:10px;margin:4px 0 9px}pre{white-space:pre-wrap;word-break:break-word;background:#090c11;border:1px solid var(--l);padding:11px;border-radius:9px;max-height:340px;overflow:auto;font-size:.76rem}table{width:100%;border-collapse:collapse}td{padding:6px 0;border-bottom:1px solid var(--l)}td:first-child{color:var(--m)}.notice{border-left:4px solid var(--w);padding-left:9px;color:var(--m);margin:8px 0}</style></head><body><main>
<div class="top"><div><h2 style="margin:0">QPX Control Center</h2><div class="sub">Forward paper trading dashboard</div></div><div id="clock" class="sub"></div></div>
<div class="grid">
<div class="card"><div class="label">Paper bot</div><div id="bot" class="value">Loading…</div></div>
<div class="card"><div class="label">Market cycle</div><div id="cycle" class="value">—</div></div>
<div class="card"><div class="label">Total equity</div><div id="equity" class="value">—</div></div>
<div class="card"><div class="label">Open / pending</div><div id="pos" class="value">—</div></div>
<div class="card wide"><div class="label">Controls</div><button id="start" onclick="act('/api/bot/start')">Start paper bot</button><button id="stop" class="danger" onclick="act('/api/bot/stop')">Stop managed bot</button><button class="secondary" onclick="act('/api/cycle')">Run one cycle</button><button class="secondary" onclick="act('/api/self-test')">Run self-test</button><div id="action" class="tiny"></div></div>
<div class="card wide"><div class="label">Symbols — source of truth</div><div class="notice">Symbol changes are blocked while the paper launcher is running.</div><div class="tiny">Candidate symbols (comma separated)</div><input id="cand"><div class="tiny">Tradable symbols</div><input id="trad"><div class="tiny">Income symbol</div><input id="inc"><div class="tiny">Volatility symbol</div><input id="vol"><button onclick="save()">Save symbols</button><span id="saved" class="tiny"></span></div>
<div class="card wide"><div class="label">Paper account</div><table id="acct"></table></div>
<div class="card wide"><div class="label">Latest status</div><pre id="status">No status yet.</pre></div>
<div class="card wide"><div class="label">Recent bot log</div><pre id="log">No log yet.</pre></div>
<div class="card wide"><div class="label">Repository</div><div id="git" class="tiny">—</div></div>
</div><p class="tiny">Local device only: 127.0.0.1. This GUI does not enable live brokerage.</p></main>
<script>let init=false;const $=x=>document.getElementById(x);function money(v){return v==null?'—':'$'+Number(v).toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2})}async function req(p,o={}){let r=await fetch(p,o),j={};try{j=await r.json()}catch(e){}if(!r.ok)throw Error(j.error||('HTTP '+r.status));return j}function row(k,v){return `<tr><td>${k}</td><td>${v??'—'}</td></tr>`}async function refresh(){try{let d=await req('/api/dashboard'),b=d.bot||{},s=d.status||{},a=d.account||{},y=d.symbols||{};$('bot').textContent=b.running?(b.managed?'RUNNING · GUI managed':'RUNNING · external'):'STOPPED';$('bot').className='value '+(b.running?'good':'warn');$('start').disabled=!!b.running;$('stop').disabled=!(b.running&&b.managed);$('cycle').textContent=s.status||'No cycle report';$('equity').textContent=money(s.total_equity);$('pos').textContent=(s.open_positions??0)+' / '+(s.pending_entries??0);$('status').textContent=JSON.stringify(s,null,2);$('log').textContent=d.log_tail||'No log yet.';$('acct').innerHTML=[row('Account ID',a.account_id),row('Revision',a.revision),row('Swing cash',money(a.swing_cash)),row('Tax reserve',money(a.tax_reserve_cash)),row('Realized P&L',money(a.realized_pnl)),row('Income shares',a.income_shares),row('Distributions',money(a.dividends_received)),row('Open positions',Object.keys(a.positions||{}).join(', ')||'None'),row('Pending entries',Object.keys(a.pending||{}).join(', ')||'None')].join('');if(!init){$('cand').value=(y.candidate_symbols||[]).join(', ');$('trad').value=(y.tradable_symbols||[]).join(', ');$('inc').value=y.income_symbol||'';$('vol').value=y.volatility_symbol||'';init=true}$('git').textContent=(d.git||{}).summary||'Unavailable'}catch(e){$('action').textContent=e.message}}async function act(p){$('action').textContent='Working…';try{let d=await req(p,{method:'POST'});$('action').textContent=d.message||d.output||'Done'}catch(e){$('action').textContent='Error: '+e.message}await refresh()}function csv(id){return $(id).value.split(',').map(x=>x.trim()).filter(Boolean)}async function save(){$('saved').textContent='Saving…';let body={candidate_symbols:csv('cand'),tradable_symbols:csv('trad'),income_symbol:$('inc').value.trim(),volatility_symbol:$('vol').value.trim()};try{let d=await req('/api/symbols',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});$('saved').textContent=d.message||'Saved';init=false}catch(e){$('saved').textContent='Error: '+e.message}await refresh()}setInterval(()=>{$('clock').textContent=new Date().toLocaleString()},1000);refresh();setInterval(refresh,5000)</script></body></html>"""

def rjson(p):
    try: return json.loads(p.read_text(encoding="utf-8"))
    except Exception: return {}

def aj(p,x):
    p.parent.mkdir(parents=True,exist_ok=True); t=p.with_suffix(p.suffix+".tmp")
    t.write_text(json.dumps(x,indent=2)+"\n",encoding="utf-8"); t.replace(p)

def norm(v):
    s=str(v or "").strip().upper()
    if not SYM_RE.fullmatch(s): raise ValueError(f"Invalid symbol: {v!r}")
    return s

def norms(v):
    if not isinstance(v,list): raise ValueError("Symbol lists must be arrays.")
    out=[]
    for x in v:
        x=norm(x)
        if x not in out: out.append(x)
    if not out: raise ValueError("At least one symbol is required.")
    return out

def clean_symbols(x):
    c=norms(x.get("candidate_symbols")); t=norms(x.get("tradable_symbols"))
    if not set(t).issubset(c): raise ValueError("Every tradable symbol must also be a candidate.")
    return {"candidate_symbols":c,"tradable_symbols":t,"income_symbol":norm(x.get("income_symbol")),"volatility_symbol":norm(x.get("volatility_symbol"))}

def alive(pid):
    try: os.kill(pid,0); return True
    except Exception: return False

def managed_pid():
    try:
        p=int(PID_FILE.read_text().strip())
        if alive(p): return p
    except Exception: pass
    try: PID_FILE.unlink()
    except Exception: pass
    return None

def launcher_pids():
    out=[]; proc=Path("/proc")
    if not proc.exists(): return out
    for e in proc.iterdir():
        if not e.name.isdigit(): continue
        try: cmd=(e/"cmdline").read_bytes().replace(b"\0",b" ").decode(errors="ignore")
        except OSError: continue
        if LAUNCHER.name in cmd: out.append(int(e.name))
    return sorted(set(out))

def bstate():
    m=managed_pid(); p=launcher_pids()
    return {"running":bool(m or p),"managed":m is not None,"managed_pid":m,"pids":p}

def tail(p,n=80):
    try: return "\n".join(p.read_text(encoding="utf-8",errors="replace").splitlines()[-n:])
    except OSError: return ""

def cmd(args,timeout=180):
    p=subprocess.run(args,cwd=ROOT,capture_output=True,text=True,timeout=timeout,check=False)
    return p.returncode,((p.stdout or "")+("\n"+p.stderr if p.stderr else "")).strip()

def git_summary():
    try:
        a=subprocess.run(["git","log","-1","--oneline"],cwd=ROOT,capture_output=True,text=True,timeout=8).stdout.strip()
        b=subprocess.run(["git","status","--short","--untracked-files=no"],cwd=ROOT,capture_output=True,text=True,timeout=8).stdout.strip()
        return a+(" · tracked changes present" if b else " · tracked tree clean")
    except Exception as e: return "Unavailable: "+str(e)

def start_bot():
    if bstate()["running"]: raise RuntimeError("A paper launcher is already running.")
    rc,o=cmd([sys.executable,str(PAPER),"--self-test"],60)
    if rc: raise RuntimeError("Self-test failed; bot not started.\n"+o[-2000:])
    RUNTIME.mkdir(parents=True,exist_ok=True)
    p=subprocess.Popen(["bash",str(LAUNCHER)],cwd=ROOT,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
    PID_FILE.write_text(str(p.pid)+"\n"); time.sleep(.35)
    if not alive(p.pid): raise RuntimeError("Paper launcher exited immediately.")
    return {"message":f"Paper bot started (PID {p.pid})."}

def stop_bot():
    p=managed_pid()
    if p is None: raise RuntimeError("No GUI-managed paper launcher is running.")
    try: os.killpg(os.getpgid(p),signal.SIGTERM)
    except ProcessLookupError: pass
    time.sleep(.25)
    try: PID_FILE.unlink()
    except OSError: pass
    return {"message":"GUI-managed paper bot stopped."}

class H(BaseHTTPRequestHandler):
    def log_message(self,f,*a): sys.stdout.write("[QPX GUI] "+(f%a)+"\n")
    def js(self,x,code=200):
        b=json.dumps(x,indent=2).encode(); self.send_response(code); self.send_header("Content-Type","application/json"); self.send_header("Cache-Control","no-store"); self.send_header("Content-Length",str(len(b))); self.end_headers(); self.wfile.write(b)
    def body(self):
        n=int(self.headers.get("Content-Length","0") or 0)
        if n>65536: raise ValueError("Request too large.")
        x=json.loads(self.rfile.read(n).decode() if n else "{}")
        if not isinstance(x,dict): raise ValueError("JSON object required.")
        return x
    def do_GET(self):
        p=urlparse(self.path).path
        if p=="/":
            b=HTML.encode(); self.send_response(200); self.send_header("Content-Type","text/html; charset=utf-8"); self.send_header("Cache-Control","no-store"); self.send_header("Content-Length",str(len(b))); self.end_headers(); self.wfile.write(b); return
        if p=="/api/dashboard":
            self.js({"bot":bstate(),"symbols":rjson(SYMBOLS),"status":rjson(REPORT),"account":rjson(ACCOUNT),"log_tail":tail(BOT_LOG),"git":{"summary":git_summary()}}); return
        self.js({"error":"Not found."},404)
    def do_POST(self):
        p=urlparse(self.path).path
        try:
            if p=="/api/bot/start": self.js(start_bot()); return
            if p=="/api/bot/stop": self.js(stop_bot()); return
            if p=="/api/self-test":
                rc,o=cmd([sys.executable,str(PAPER),"--self-test"],60); self.js({"message":"Self-test passed." if not rc else "Self-test failed.","output":o,"returncode":rc},200 if not rc else 500); return
            if p=="/api/cycle":
                if bstate()["running"]: raise RuntimeError("Stop the continuous launcher before a manual cycle.")
                rc,o=cmd([sys.executable,str(PAPER)],180); self.js({"message":o[-4000:] or "Cycle finished.","returncode":rc},200 if not rc else 500); return
            if p=="/api/symbols":
                if bstate()["running"]: raise RuntimeError("Stop the paper launcher before changing symbols.")
                x=clean_symbols(self.body()); aj(SYMBOLS,x)
                rc,o=cmd([sys.executable,str(PAPER),"--self-test"],60)
                if rc: raise RuntimeError("Symbols saved, but self-test failed:\n"+o[-2000:])
                self.js({"message":"Symbols saved and self-test passed.","symbols":x}); return
            self.js({"error":"Not found."},404)
        except (ValueError,json.JSONDecodeError) as e: self.js({"error":str(e)},400)
        except subprocess.TimeoutExpired: self.js({"error":"Command timed out."},504)
        except Exception as e: self.js({"error":str(e)},409)

def check():
    miss=[str(p.relative_to(ROOT)) for p in (SYMBOLS,PAPER,LAUNCHER,POLICY) if not p.exists()]
    if miss:
        print("Missing:",", ".join(miss)); return 1
    try: x=clean_symbols(rjson(SYMBOLS))
    except Exception as e: print("Invalid symbols.json:",e); return 1
    print("QPX GUI check passed."); print("Symbols:",json.dumps(x)); print("Paper bot:","running" if bstate()["running"] else "stopped"); return 0

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--host",default="127.0.0.1"); ap.add_argument("--port",type=int,default=int(os.environ.get("QPX_GUI_PORT","8765"))); ap.add_argument("--check",action="store_true"); a=ap.parse_args()
    if a.check: return check()
    if a.host not in {"127.0.0.1","localhost"}: print("Refusing non-local bind.",file=sys.stderr); return 2
    if check(): return 1
    s=ThreadingHTTPServer((a.host,a.port),H); print("="*72); print("QPX CONTROL CENTER"); print("="*72); print(f"Open: http://127.0.0.1:{a.port}"); print("Local device only. CTRL+C stops the GUI."); print("="*72)
    try: s.serve_forever()
    except KeyboardInterrupt: print("\nQPX GUI stopped.")
    finally: s.server_close()
    return 0
if __name__=="__main__": raise SystemExit(main())
