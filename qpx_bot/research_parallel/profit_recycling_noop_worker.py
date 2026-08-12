"""Run one control or disabled Profit Recycling arm in a fresh interpreter."""
import argparse,json
from pathlib import Path
import QPX_RUN_CAPACITY_ARBITRATION_SHADOW_MATRIX as matrix
from qpx_bot.accelerators.profit_recycling import load_profit_recycling_config
def main():
 p=argparse.ArgumentParser();p.add_argument("--period",required=True);p.add_argument("--cap",required=True);p.add_argument("--arm",choices=("control","profit_recycling_disabled"),required=True);p.add_argument("--output-directory",required=True);a=p.parse_args();out=Path(a.output_directory).resolve();matrix.REPORT_PARENT=out/"underlying"
 if a.arm=="profit_recycling_disabled":load_profit_recycling_config(Path("qpx_bot/accelerators/configs/profit_recycling_v1_foundation.json"))
 source=matrix.run_arm(a.period,a.cap,"hash_control");record=dict(source);record["validation_arm"]=a.arm;path=out/"profit_recycling_noop.json";path.parent.mkdir(parents=True,exist_ok=True);tmp=path.with_suffix(".tmp");tmp.write_text(json.dumps(record,sort_keys=True,separators=(",",":")));tmp.replace(path);print(path)
if __name__=="__main__":main()
