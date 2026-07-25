"""
QPX_CREATE_BUILDER_FRAMEWORK.py

Sprint 5
Milestone 1

Creates the permanent builder framework used by every future
QPX builder script.
"""

from pathlib import Path


ROOT = Path(__file__).parent


def write_file(relative_path: str, contents: str):
    path = ROOT / relative_path

    path.parent.mkdir(parents=True, exist_ok=True)

    path.write_text(
        contents.strip() + "\n",
        encoding="utf-8"
    )

    print(f"Created: {relative_path}")


print("=" * 60)
print("QPX_ALPHA Builder Framework")
print("=" * 60)

write_file(
    "tools/builder_engine.py",
'''
"""
Reusable Builder Engine
"""

from pathlib import Path


class BuilderEngine:

    def __init__(self):
        self.root = Path.cwd()

    def write(self, relative_path, contents):

        path = self.root / relative_path

        path.parent.mkdir(
            parents=True,
            exist_ok=True
        )

        path.write_text(
            contents.strip() + "\\n",
            encoding="utf-8"
        )

        print(f"Created {relative_path}")

    def exists(self, relative_path):

        return (self.root / relative_path).exists()
'''
)

write_file(
    "tests/test_builder_engine.py",
'''
from tools.builder_engine import BuilderEngine


engine = BuilderEngine()

assert engine is not None

print("Builder Engine PASS")
'''
)

print()
print("=" * 60)
print("SPRINT 5 MILESTONE 1 COMPLETE")
print("=" * 60)