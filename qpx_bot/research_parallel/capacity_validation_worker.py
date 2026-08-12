"""Run one existing Capacity Arbitration arm in an isolated validation root."""
import argparse
from pathlib import Path
import QPX_RUN_CAPACITY_ARBITRATION_SHADOW_MATRIX as matrix
def main():
 p=argparse.ArgumentParser();p.add_argument("--period",choices=matrix.PERIODS,required=True);p.add_argument("--cap",choices=matrix.CAP_ORDER,required=True);p.add_argument("--policy",choices=matrix.POLICY_ORDER,required=True);p.add_argument("--output-directory",required=True);a=p.parse_args();output=Path(a.output_directory).resolve();matrix.REPORT_PARENT=output.parent.parent;record=matrix.run_arm(a.period,a.cap,a.policy);expected=output/"capacity_arbitration.json"
 if not expected.exists():raise RuntimeError(f"Validation artifact path differs: {expected}")
 print(expected)
if __name__=="__main__":main()
