#!/usr/bin/env python3
import argparse,json
from pathlib import Path
import QPX_RUN_CAPACITY_ARBITRATION_SHADOW_MATRIX as matrix
from qpx_bot.accelerators.profit_recycling import load_profit_recycling_config
from qpx_bot.research_parallel import ResearchJob
CASES=(("full_2024_2026","25"),("p1_2024","40"),("p2_2025","60"),("p3_2026","90"),("e2_through_2025","25"),("full_2024_2026","90"))
def main():
 p=argparse.ArgumentParser();p.add_argument("output_root",type=Path);p.add_argument("manifest",type=Path);a=p.parse_args();cfg=load_profit_recycling_config(Path("qpx_bot/accelerators/configs/profit_recycling_v1_foundation.json"));serial=json.loads(matrix.SUMMARY_PATH.read_text());jobs=[]
 for period,cap in CASES:
  source=serial["matrix"][period][cap]["hash_control"]
  for arm in ("control","profit_recycling_disabled"):
   out=(a.output_root/period/f"{cap}_{arm}").resolve();job=ResearchJob("profit_recycling_v1_noop","qpx_bot.research_parallel.profit_recycling_noop_worker",("--period",period,"--cap",cap,"--arm",arm),period,f"cap_{cap}",arm,source["dataset_fingerprint"],source["configuration_fingerprint"],str(out),str(out/"profit_recycling_noop.json"),tuple(sorted(source["causal_gates"].items())));jobs.append(job.identity_payload|{"job_id":job.job_id})
 a.manifest.parent.mkdir(parents=True,exist_ok=True);a.manifest.write_text(json.dumps({"schema_version":1,"disabled_configuration_fingerprint":cfg.fingerprint,"jobs":jobs},sort_keys=True,separators=(",",":")))
if __name__=="__main__":main()
