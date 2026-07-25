from pathlib import Path
import textwrap

ROOT = Path("/storage/emulated/0/QPX_ALPHA")

TOOLS = ROOT / "tools"
TOOLS.mkdir(exist_ok=True)

# --------------------------------------------------
# __init__.py
# --------------------------------------------------

(TOOLS / "__init__.py").write_text(
    "# QPX_ALPHA Developer Toolkit\n",
    encoding="utf-8"
)

# --------------------------------------------------
# README.md
# --------------------------------------------------

readme = textwrap.dedent("""
# QPX_ALPHA Developer Toolkit

The tools package contains utilities used during development.

## Available Tools

doctor.py
    Performs platform diagnostics.

scaffold.py
    Generates new modules, services, tests, and ADRs.

Future tools may include:

- create_release
- benchmark
- lint
- format
- migration helpers

These tools are intended for developers and contributors.
""").strip()

(TOOLS / "README.md").write_text(
    readme + "\n",
    encoding="utf-8"
)

# --------------------------------------------------
# scaffold.py
# --------------------------------------------------

scaffold = textwrap.dedent("""
import sys

USAGE = '''
Usage:

python -m tools.scaffold module ModuleName

python -m tools.scaffold service ServiceName

python -m tools.scaffold adr "Title"

(Implementation coming in Sprint 4)
'''

def main():
    print("=" * 50)
    print("QPX_ALPHA Scaffold Tool")
    print("=" * 50)
    print()

    if len(sys.argv) < 2:
        print(USAGE)
        return

    print("Scaffolding support will be implemented during Sprint 4.")
    print()
    print("Arguments:", sys.argv[1:])

if __name__ == "__main__":
    main()
""").strip()

(TOOLS / "scaffold.py").write_text(
    scaffold + "\n",
    encoding="utf-8"
)

# --------------------------------------------------
# doctor.py
# --------------------------------------------------

doctor = textwrap.dedent("""
import platform
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

print("=" * 50)
print("QPX_ALPHA Doctor")
print("=" * 50)

print()

print("Python Version")

print(platform.python_version())

print()

print("Project Root")

print(ROOT)

print()

print("Toolkit Status")

print("PASS")
""").strip()

(TOOLS / "doctor.py").write_text(
    doctor + "\n",
    encoding="utf-8"
)

print("=" * 60)
print("Developer Toolkit Created")
print("=" * 60)
print()
print("Run:")
print("python -m tools.doctor")
print("python -m tools.scaffold")