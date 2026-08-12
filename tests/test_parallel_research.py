from __future__ import annotations
import json,tempfile,unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch
from qpx_bot.research_parallel import *
from qpx_bot.research_parallel.orchestrator import JobRecord,canonical_hash
D="a"*64;C="b"*64
class ParallelResearchTests(unittest.TestCase):
 def setUp(self):self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
 def tearDown(self):self.temp.cleanup()
 def job(self,name,**changes):
  out=self.root/name;p=dict(experiment="fixture",worker_module="tests.parallel_fixture_worker",worker_args=("--name",name,"--dataset",D,"--config",C,"--value",str(len(name))),period="p1",cap_identity=name,accelerator_identity="fixture",expected_dataset_fingerprint=D,expected_configuration_fingerprint=C,output_directory=str(out),result_artifact=str(out/"result.json"),required_gates=(("OVERALL","PASS"),));p.update(changes);return ResearchJob(**p)
 def runner(self,jobs,workers=2):return ParallelResearchRunner(jobs,self.root/f"manifest-{workers}.json",workers=workers,cwd=Path.cwd())
 def test_deterministic_job_ids_and_unique_outputs(self):
  a=self.job("a");self.assertEqual(a.job_id,self.job("a").job_id);self.assertNotEqual(a.job_id,self.job("b").job_id);self.assertNotEqual(a.output_directory,self.job("b").output_directory)
 def test_duplicate_jobs_and_shared_paths_rejected(self):
  a=self.job("a")
  with self.assertRaisesRegex(ValueError,"Duplicate"):self.runner((a,a))
  with self.assertRaisesRegex(ValueError,"Shared output"):self.runner((a,replace(self.job("b"),output_directory=a.output_directory,result_artifact=a.output_directory+"/other.json")))
 def test_invalid_worker_count_rejected(self):
  for n in (0,-1,1.5):
   with self.assertRaises(ValueError):self.runner((self.job("a"),),n)
 def test_process_isolation_and_parallel_workers(self):
  result=self.runner(tuple(self.job(x) for x in ("a","b","c","d")),4).run();pids={x["result"]["pid"] for x in result["jobs"]};self.assertEqual(len(pids),4);self.assertNotIn(__import__("os").getpid(),pids)
 def test_workers_one_and_many_semantically_equivalent(self):
  jobs1=tuple(self.job(x) for x in ("a","b","c"));one=self.runner(jobs1,1).run();root2=self.root/"many";root2.mkdir();jobs2=tuple(replace(x,output_directory=str(root2/Path(x.output_directory).name),result_artifact=str(root2/Path(x.output_directory).name/"result.json")) for x in jobs1);many=ParallelResearchRunner(jobs2,self.root/"many.json",workers=3).run();strip=lambda a:[{k:v for k,v in x["result"].items() if k!="pid"} for x in a["jobs"]];self.assertEqual(strip(one),strip(many))
 def test_aggregation_deterministic_independent_of_completion_order(self):
  jobs=(self.job("slow",worker_args=("--name","slow","--dataset",D,"--config",C,"--delay",".2")),self.job("fast"));a=self.runner(jobs,2).run();self.assertEqual([x["result"]["name"] for x in a["jobs"]],["fast","slow"]);self.assertEqual(a["aggregate_checksum"],canonical_hash(a["jobs"]))
 def test_completed_job_resumes_without_rerun(self):
  job=self.job("a");first=self.runner((job,),1);first.run();attempt=first.records[job.job_id].attempt_count;second=self.runner((job,),1);second.run();self.assertEqual(second.records[job.job_id].attempt_count,attempt)
 def test_interrupted_and_corrupt_jobs_rerun(self):
  job=self.job("a");runner=self.runner((job,),1);runner.records[job.job_id]=JobRecord(job.job_id,job.identity_payload,status="RUNNING",attempt_count=1);runner._save();runner=self.runner((job,),1);runner.run();self.assertEqual(runner.records[job.job_id].attempt_count,2);Path(job.result_artifact).write_text("{");runner=self.runner((job,),1);runner.run();self.assertEqual(runner.records[job.job_id].attempt_count,3)
 def test_failed_worker_does_not_stop_healthy_and_is_surfaced(self):
  good=self.job("good");bad=self.job("bad",worker_args=("--name","bad","--dataset",D,"--config",C,"--fail"));runner=self.runner((good,bad),2)
  with self.assertRaisesRegex(ParallelResearchError,"FAILED"):runner.run()
  self.assertEqual(runner.records[good.job_id].status,"COMPLETE");self.assertEqual(runner.records[bad.job_id].status,"FAILED")
 def test_fingerprint_and_gate_mismatch_fail_closed(self):
  for name,job in (("fingerprint",self.job("x",expected_configuration_fingerprint="c"*64)),("gate",self.job("y",required_gates=(("OVERALL","NO"),)))):
   runner=self.runner((job,),1)
   with self.assertRaises(ParallelResearchError):runner.run()
   self.assertEqual(runner.records[job.job_id].status,"FAILED")
 def test_cli_manifest_accepts_explicit_ids_and_runs_all_jobs(self):
  import subprocess,sys
  jobs=(self.job("cli_a"),self.job("cli_b"));manifest=self.root/"cli.json";manifest.write_text(json.dumps({"jobs":[x.identity_payload|{"job_id":x.job_id} for x in jobs]}));result=subprocess.run([sys.executable,"QPX_RUN_PARALLEL_RESEARCH.py",str(manifest),"--workers","2"],cwd=Path.cwd(),capture_output=True,text=True);self.assertEqual(result.returncode,0,result.stderr);aggregate=json.loads((self.root/"cli_aggregate.json").read_text());self.assertEqual(len(aggregate["jobs"]),2)
 def test_default_workers_is_conservative(self):
  with patch("os.cpu_count",return_value=64):self.assertEqual(__import__("qpx_bot.research_parallel.orchestrator",fromlist=["default_workers"]).default_workers(),4)
  with patch("os.cpu_count",return_value=None):self.assertEqual(__import__("qpx_bot.research_parallel.orchestrator",fromlist=["default_workers"]).default_workers(),1)
if __name__=="__main__":unittest.main()
