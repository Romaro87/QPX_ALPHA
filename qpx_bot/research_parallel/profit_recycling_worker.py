import argparse
from pathlib import Path
import QPX_RUN_PROFIT_RECYCLING_RESEARCH as research
def main():
 p=argparse.ArgumentParser();p.add_argument("--period",required=True);p.add_argument("--cap",required=True);p.add_argument("--config",required=True);p.add_argument("--output-directory",required=True);a=p.parse_args();research.run_arm(a.period,a.cap,a.config,Path(a.output_directory));print(Path(a.output_directory)/"profit_recycling.json")
if __name__=="__main__":main()
