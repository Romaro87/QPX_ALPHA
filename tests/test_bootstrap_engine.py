import shutil
from pathlib import Path

from tools.bootstrap_engine import BootstrapEngine

project = Path("SampleProject")

if project.exists():
    shutil.rmtree(project)

engine = BootstrapEngine()

engine.bootstrap("SampleProject")

assert project.exists()
assert (project / "app").exists()
assert (project / "core").exists()
assert (project / "tests").exists()
assert (project / "README.md").exists()

shutil.rmtree(project)

print("Bootstrap Engine PASS")
