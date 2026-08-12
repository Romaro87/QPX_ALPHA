import argparse
from pathlib import Path
import QPX_RUN_REGIME_ALLOCATION_MATRIX as matrix
def main():
 p=argparse.ArgumentParser();p.add_argument("--period",required=True);p.add_argument("--cap",required=True);p.add_argument("--policy",required=True);p.add_argument("--output-directory",required=True);a=p.parse_args();out=Path(a.output_directory).resolve();matrix.REPORT_PARENT=out/"reports";record=matrix.run_arm(a.period,a.cap,a.policy);expected=out/"reports"/a.period/f"{a.policy}_{a.cap}"/"regime_allocation.json";target=out/"regime_allocation.json";target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(expected.read_bytes());print(target)
if __name__=="__main__":main()
