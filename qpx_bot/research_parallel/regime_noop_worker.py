"""Run one control or disabled Regime Allocation arm in a fresh interpreter."""
import argparse,json
from pathlib import Path
import QPX_RUN_CAPACITY_ARBITRATION_SHADOW_MATRIX as matrix
from qpx_bot.accelerators.regime_allocation import load_regime_allocation_config
def main():
 p=argparse.ArgumentParser();p.add_argument("--period",required=True);p.add_argument("--cap",required=True);p.add_argument("--arm",choices=("control","regime_disabled"),required=True);p.add_argument("--output-directory",required=True);a=p.parse_args()
 output=Path(a.output_directory).resolve();matrix.REPORT_PARENT=output/"underlying"
 if a.arm=="regime_disabled": load_regime_allocation_config(Path("qpx_bot/accelerators/configs/regime_allocation_v1_foundation.json"))
 source=matrix.run_arm(a.period,a.cap,"hash_control");record=dict(source);record["validation_arm"]=a.arm
 path=output/"regime_noop.json";path.parent.mkdir(parents=True,exist_ok=True);tmp=path.with_suffix(".tmp");tmp.write_text(json.dumps(record,sort_keys=True,separators=(",",":")));tmp.replace(path);print(path)
if __name__=="__main__":main()
