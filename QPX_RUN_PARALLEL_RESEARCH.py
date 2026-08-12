#!/usr/bin/env python3
"""Run a deterministic QPX research job manifest with isolated subprocesses."""
import argparse,json
from pathlib import Path
from qpx_bot.research_parallel import ParallelResearchRunner,ResearchJob,default_workers
from qpx_bot.research_parallel.orchestrator import atomic_json
def main():
 p=argparse.ArgumentParser();p.add_argument("manifest",type=Path);p.add_argument("--workers",type=int,default=default_workers());p.add_argument("--aggregate",type=Path);a=p.parse_args();raw=json.loads(a.manifest.read_text());jobs=[]
 for item in raw["jobs"]:
  definition={k:v for k,v in item.items() if k!="job_id"};definition["worker_args"]=tuple(definition["worker_args"]);definition["required_gates"]=tuple(tuple(g) for g in definition.get("required_gates",()));job=ResearchJob(**definition)
  if item.get("job_id",job.job_id)!=job.job_id:raise ValueError("Manifest job_id differs from deterministic definition.")
  jobs.append(job)
 aggregate=a.aggregate or a.manifest.with_name(a.manifest.stem+"_aggregate.json");result=ParallelResearchRunner(jobs,a.manifest.with_name(a.manifest.stem+"_status.json"),workers=a.workers).run();atomic_json(aggregate,result);print(aggregate)
if __name__=="__main__":main()
