#!/usr/bin/env python3
import argparse,json
from pathlib import Path
import QPX_RUN_CAPACITY_ARBITRATION_SHADOW_MATRIX as controls
import QPX_RUN_REGIME_ALLOCATION_MATRIX as matrix
from qpx_bot.accelerators.regime_allocation import load_regime_allocation_config
from qpx_bot.research_parallel import ResearchJob
def main():
 p=argparse.ArgumentParser();p.add_argument("output_root",type=Path);p.add_argument("manifest",type=Path);a=p.parse_args();serial=json.loads(controls.SUMMARY_PATH.read_text());jobs=[]
 for period in matrix.PERIODS:
  for cap in matrix.CAP_ORDER:
   source=serial["matrix"][period][cap]["hash_control"]
   for policy in matrix.POLICIES:
    cfg=load_regime_allocation_config(Path("qpx_bot/accelerators/configs")/matrix.FILES[policy]);out=(a.output_root/period/f"{policy}_{cap}").resolve();job=ResearchJob("regime_allocation_v1", "qpx_bot.research_parallel.regime_worker",("--period",period,"--cap",cap,"--policy",policy),period,f"cap_{cap}",policy,source["dataset_fingerprint"],cfg.fingerprint,str(out),str(out/"regime_allocation.json"),tuple(sorted(source["causal_gates"].items())));jobs.append(job.identity_payload|{"job_id":job.job_id})
 a.manifest.parent.mkdir(parents=True,exist_ok=True);a.manifest.write_text(json.dumps({"schema_version":1,"jobs":jobs},sort_keys=True,separators=(",",":")))
if __name__=="__main__":main()
