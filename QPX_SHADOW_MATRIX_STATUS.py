#!/usr/bin/env python3
"""Read-only bounded status for the Clean-V2 subordinate Shadow Matrix."""
from __future__ import annotations
import argparse, json
from pathlib import Path
from qpx_bot.shadow_matrix.checkpoint import restore_checkpoint
from qpx_bot.shadow_matrix.registry import load_registry

def main() -> int:
    p = argparse.ArgumentParser(); p.add_argument("--runtime-dir", type=Path, default=Path("runtime/qpx_pr50_iex_forward_research_paper_clean_v2")); a=p.parse_args()
    state_path=a.runtime_dir/"iex_research_paper_state.json"
    if not state_path.exists(): print(json.dumps({"status":"NO_RUNTIME_STATE","matrix_enabled":False},sort_keys=True)); return 0
    state=json.loads(state_path.read_text()); raw=state.get("shadow_matrix_checkpoint")
    if not raw: print(json.dumps({"status":"NOT_INITIALIZED","matrix_enabled":False,"state_revision":state.get("revision")},sort_keys=True)); return 0
    engine=restore_checkpoint(json.dumps(raw,sort_keys=True,separators=(",",":")),load_registry())
    print(json.dumps({"status":"ACTIVE","matrix_enabled":True,"active_shadow_count":len(engine.dispatch_order),"expected_shadow_count":45,"latest_event_sequence":engine.last_sequence,"latest_event_timestamp":engine.last_timestamp.isoformat() if engine.last_timestamp else None,"healthy_shadows":sum(s not in engine.quarantines for s in engine.dispatch_order),"quarantined_shadows":sorted(engine.quarantines),"automatic_promotion":False,"registry_fingerprint":engine.registry.fingerprint,"state_revision":state.get("revision")},sort_keys=True))
    return 0
if __name__ == "__main__": raise SystemExit(main())
