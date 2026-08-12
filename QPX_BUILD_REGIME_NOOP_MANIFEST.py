#!/usr/bin/env python3
"""Build the fixed representative Regime Allocation disabled-validation manifest."""
import argparse,json
from pathlib import Path
from qpx_bot.accelerators.regime_allocation import load_regime_allocation_config
from qpx_bot.research_parallel import ResearchJob
import QPX_RUN_CAPACITY_ARBITRATION_SHADOW_MATRIX as matrix
CASES=(("full_2024_2026","25"),("p1_2024","40"),("p2_2025","60"),("p3_2026","90"),("e2_through_2025","25"),("full_2024_2026","90"))
def main():
 p=argparse.ArgumentParser();p.add_argument("output_root",type=Path);p.add_argument("manifest",type=Path);a=p.parse_args();cfg=load_regime_allocation_config(Path("qpx_bot/accelerators/configs/regime_allocation_v1_foundation.json"));serial=json.loads(matrix.SUMMARY_PATH.read_text());jobs=[]
 for period,cap in CASES:
  source=serial["matrix"][period][cap]["hash_control"]
  for arm in ("control","regime_disabled"):
   out=(a.output_root/period/f"{cap}_{arm}").resolve();job=ResearchJob(experiment_name="regime_allocation_v1_noop",worker_module="qpx_bot.research_parallel.regime_noop_worker",period=period,config_identity=f"cap_{cap}",accelerator_identity=arm,expected_dataset_fingerprint=source["dataset_fingerprint"],expected_configuration_fingerprint=source["configuration_fingerprint"],output_directory=str(out),result_artifact=str(out/"regime_noop.json"),worker_args=("--period",period,"--cap",cap,"--arm",arm),required_gates=tuple(sorted(source["causal_gates"].items())))
   jobs.append(job.definition|{"job_id":job.job_id})
 a.manifest.parent.mkdir(parents=True,exist_ok=True);a.manifest.write_text(json.dumps({"schema_version":1,"disabled_configuration_fingerprint":cfg.fingerprint,"jobs":jobs},sort_keys=True,separators=(",",":")))
if __name__=="__main__":main()
