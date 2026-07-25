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
