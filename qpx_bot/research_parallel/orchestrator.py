"""Deterministic, resumable subprocess orchestration for independent QPX research."""
from __future__ import annotations
import hashlib,json,os,subprocess,sys,tempfile
from concurrent.futures import ThreadPoolExecutor,as_completed
from dataclasses import asdict,dataclass,field
from datetime import datetime,timezone
from pathlib import Path
from typing import Any

def canonical_bytes(value:Any)->bytes:return json.dumps(value,sort_keys=True,separators=(",",":"),allow_nan=False).encode()
def canonical_hash(value:Any)->str:return hashlib.sha256(canonical_bytes(value)).hexdigest()
def default_workers()->int:return max(1,min(4,os.cpu_count() or 1))
def atomic_json(path:Path,value:Any)->None:
 path.parent.mkdir(parents=True,exist_ok=True);handle=tempfile.NamedTemporaryFile("wb",dir=path.parent,delete=False);temporary=Path(handle.name)
 try:
  with handle:handle.write(canonical_bytes(value));handle.flush();os.fsync(handle.fileno())
  os.replace(temporary,path)
 finally:
  if temporary.exists():temporary.unlink()

@dataclass(frozen=True,slots=True)
class ResearchJob:
 experiment:str;worker_module:str;worker_args:tuple[str,...];period:str;cap_identity:str;accelerator_identity:str;expected_dataset_fingerprint:str;expected_configuration_fingerprint:str|None;output_directory:str;result_artifact:str;required_gates:tuple[tuple[str,str],...]=()
 def __post_init__(self):
  if not all((self.experiment.strip(),self.worker_module.strip(),self.period.strip(),self.cap_identity.strip(),self.accelerator_identity.strip())):raise ValueError("Job identities are required.")
  if not self.expected_dataset_fingerprint or len(self.expected_dataset_fingerprint)!=64:raise ValueError("Expected dataset fingerprint is required.")
  if self.expected_configuration_fingerprint is not None and len(self.expected_configuration_fingerprint)!=64:raise ValueError("Expected configuration fingerprint is invalid.")
  output=Path(self.output_directory);result=Path(self.result_artifact)
  if not output.is_absolute() or not result.is_absolute() or output not in result.parents:raise ValueError("Result artifact must be inside an absolute unique output directory.")
 @property
 def identity_payload(self):return {"experiment":self.experiment,"worker_module":self.worker_module,"worker_args":self.worker_args,"period":self.period,"cap_identity":self.cap_identity,"accelerator_identity":self.accelerator_identity,"expected_dataset_fingerprint":self.expected_dataset_fingerprint,"expected_configuration_fingerprint":self.expected_configuration_fingerprint,"output_directory":self.output_directory,"result_artifact":self.result_artifact,"required_gates":self.required_gates}
 @property
 def job_id(self):return canonical_hash(self.identity_payload)
 @property
 def command(self):return (sys.executable,"-m",self.worker_module,*self.worker_args,"--output-directory",self.output_directory)

@dataclass(slots=True)
class JobRecord:
 job_id:str;definition:dict[str,Any];status:str="PENDING";attempt_count:int=0;start_timestamp:str|None=None;end_timestamp:str|None=None;exit_code:int|None=None;result_artifact:str|None=None;result_checksum:str|None=None;error:str|None=None;worker_pid:int|None=None

class ParallelResearchError(RuntimeError):pass

class ParallelResearchRunner:
 def __init__(self,jobs,manifest_path:Path,*,workers:int|None=None,cwd:Path|None=None):
  self.jobs=tuple(jobs);self.manifest_path=manifest_path.resolve();self.workers=default_workers() if workers is None else workers;self.cwd=(cwd or Path.cwd()).resolve()
  if type(self.workers) is not int or self.workers<1:raise ValueError("Worker count must be a positive integer.")
  ids=[x.job_id for x in self.jobs];outputs=[x.output_directory for x in self.jobs]
  if len(ids)!=len(set(ids)):raise ValueError("Duplicate job definitions are forbidden.")
  if len(outputs)!=len(set(outputs)):raise ValueError("Shared output directories are forbidden.")
  artifacts=[x.result_artifact for x in self.jobs]
  if len(artifacts)!=len(set(artifacts)):raise ValueError("Shared result artifacts are forbidden.")
  self.records=self._load_records()
 def _load_records(self):
  saved={}
  if self.manifest_path.exists():
   payload=json.loads(self.manifest_path.read_text());saved={x["job_id"]:JobRecord(**x) for x in payload.get("jobs",[])}
  records={}
  for job in self.jobs:
   prior=saved.get(job.job_id);records[job.job_id]=prior if prior and canonical_bytes(prior.definition)==canonical_bytes(job.identity_payload) else JobRecord(job.job_id,job.identity_payload)
  return records
 def _save(self):
  atomic_json(self.manifest_path,{"schema_version":1,"workers":self.workers,"jobs":[asdict(self.records[x.job_id]) for x in sorted(self.jobs,key=lambda j:j.job_id)]})
 def _validate(self,job):
  path=Path(job.result_artifact)
  try:payload=json.loads(path.read_text())
  except (OSError,json.JSONDecodeError) as error:raise ParallelResearchError(f"Result artifact missing/corrupt: {path}") from error
  if payload.get("dataset_fingerprint")!=job.expected_dataset_fingerprint:raise ParallelResearchError("Dataset fingerprint mismatch.")
  if job.expected_configuration_fingerprint is not None and payload.get("configuration_fingerprint")!=job.expected_configuration_fingerprint:raise ParallelResearchError("Configuration fingerprint mismatch.")
  gates=payload.get("causal_gates",{})
  for key,value in job.required_gates:
   if gates.get(key)!=value:raise ParallelResearchError(f"Causal gate mismatch: {key}")
  return payload,canonical_hash(payload)
 def _resume_valid(self,job):
  record=self.records[job.job_id]
  if record.status!="COMPLETE":return False
  try:_,checksum=self._validate(job)
  except ParallelResearchError:return False
  return checksum==record.result_checksum
 def _execute(self,job):
  record=self.records[job.job_id];record.status="RUNNING";record.attempt_count+=1;record.start_timestamp=datetime.now(timezone.utc).isoformat();record.end_timestamp=None;record.exit_code=None;record.error=None;self._save()
  process=subprocess.Popen(job.command,cwd=self.cwd,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True);record.worker_pid=process.pid;self._save();stdout,stderr=process.communicate();record.exit_code=process.returncode;record.end_timestamp=datetime.now(timezone.utc).isoformat()
  if process.returncode!=0:record.status="FAILED";record.error=(stderr or stdout)[-4000:] or f"Worker exited {process.returncode}";self._save();return
  try:_,checksum=self._validate(job)
  except ParallelResearchError as error:record.status="FAILED";record.error=str(error);self._save();return
  record.status="COMPLETE";record.result_artifact=job.result_artifact;record.result_checksum=checksum;record.error=None;self._save()
 def run(self):
  pending=[job for job in self.jobs if not self._resume_valid(job)]
  for job in pending:
   record=self.records[job.job_id]
   if record.status=="COMPLETE":record.status="CORRUPT";record.error="Previously complete artifact failed validation."
  self._save()
  with ThreadPoolExecutor(max_workers=self.workers) as pool:
   futures={pool.submit(self._execute,job):job for job in pending}
   for future in as_completed(futures):future.result()
  self._save();return self.aggregate()
 def aggregate(self):
  failures=[self.records[x.job_id] for x in self.jobs if self.records[x.job_id].status!="COMPLETE"]
  if failures:raise ParallelResearchError("Incomplete/failed jobs: "+", ".join(f"{x.job_id}:{x.status}" for x in failures))
  ordered=sorted(self.jobs,key=lambda x:(x.experiment,x.period,x.cap_identity,x.accelerator_identity,x.job_id));results=[]
  for job in ordered:
   payload,checksum=self._validate(job);results.append({"job_id":job.job_id,"result_checksum":checksum,"result":payload})
  aggregate={"schema_version":1,"jobs":results,"aggregate_checksum":canonical_hash(results)};return aggregate
