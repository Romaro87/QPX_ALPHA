#!/usr/bin/env python3
"""Run one disjoint hard-cap worker for the Pyramiding V1 matrix."""
import argparse
import QPX_RUN_PYRAMIDING_SHADOW_MATRIX as matrix

def main():
 parser=argparse.ArgumentParser();parser.add_argument("cap",choices=matrix.CAP_ORDER);args=parser.parse_args()
 for period in matrix.PERIODS:
  for treatment in ("pyramid","dynamic_pyramid"):
   result=matrix.REPORT_PARENT/period/f"{treatment}_{args.cap}"/"pyramiding.json"
   if not result.exists():matrix.run_arm(period,args.cap,treatment)
 print(args.cap)
if __name__=="__main__":main()
