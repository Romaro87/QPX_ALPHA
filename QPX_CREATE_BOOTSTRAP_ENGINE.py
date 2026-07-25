"""
QPX_CREATE_BOOTSTRAP_ENGINE.py

Sprint 5
Milestone 5

Creates the Bootstrap Engine.
"""

from pathlib import Path

ROOT = Path(__file__).parent


def write(relative_path, contents):
    path = ROOT / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(contents.strip() + "\n", encoding="utf-8")
    print(f"Created: {relative_path}")


print("=" * 60)
print("QPX_ALPHA Bootstrap Engine")
print("=" * 60)


write(
    "tools/bootstrap_engine.py",
'''
"""
Bootstrap Engine

Creates a complete project skeleton using the
existing Generator Engine.
"""

from pathlib import Path

from tools.generator_engine import GeneratorEngine


class BootstrapEngine:

    def __init__(self):
        self.generator = GeneratorEngine()

    def bootstrap(self, project_name):

        root = Path(project_name)

        directories = [
            "app",
            "core",
            "config",
            "data",
            "docs",
            "docs/adr",
            "tests",
            "tools",
            "logs",
            "reports",
            "cache"
        ]

        for directory in directories:
            (root / directory).mkdir(
                parents=True,
                exist_ok=True
            )

        (root / "README.md").write_text(
            f"# {project_name}\\n",
            encoding="utf-8"
        )

        (root / ".gitignore").write_text(
            "__pycache__/\\n*.pyc\\n",
            encoding="utf-8"
        )

        return root
'''
)

write(
    "tests/test_bootstrap_engine.py",
'''
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
'''
)

print()
print("=" * 60)
print("SPRINT 5 COMPLETE")
print("=" * 60)
print("Created:")
print("  tools/bootstrap_engine.py")
print("  tests/test_bootstrap_engine.py")
print("=" * 60)