"""Lightweight deterministic subprocess fixture; never imported by production."""
import argparse,json,os,time
from pathlib import Path
from qpx_bot.research_parallel.orchestrator import atomic_json
def main():
 p=argparse.ArgumentParser();p.add_argument("--name",required=True);p.add_argument("--dataset",required=True);p.add_argument("--config");p.add_argument("--value",type=int,default=1);p.add_argument("--delay",type=float,default=0);p.add_argument("--fail",action="store_true");p.add_argument("--output-directory",required=True);a=p.parse_args();time.sleep(a.delay)
 if a.fail:raise RuntimeError("fixture failure")
 path=Path(a.output_directory);path.mkdir(parents=True,exist_ok=True);atomic_json(path/"result.json",{"name":a.name,"dataset_fingerprint":a.dataset,"configuration_fingerprint":a.config,"causal_gates":{"OVERALL":"PASS"},"value":a.value,"pid":os.getpid()})
if __name__=="__main__":main()
