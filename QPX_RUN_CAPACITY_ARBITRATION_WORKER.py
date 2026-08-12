#!/usr/bin/env python3
import argparse
import QPX_RUN_CAPACITY_ARBITRATION_SHADOW_MATRIX as matrix
def main():
 p=argparse.ArgumentParser();p.add_argument("policy",choices=matrix.POLICY_ORDER);p.add_argument("cap",choices=matrix.CAP_ORDER);a=p.parse_args()
 for period in matrix.PERIODS:matrix.run_arm(period,a.cap,a.policy)
 print(a.policy,a.cap)
if __name__=="__main__":main()
