from pathlib import Path
import textwrap
import shutil

ROOT = Path("/storage/emulated/0/QPX_ALPHA")
TESTS = ROOT / "tests"

TESTS.mkdir(parents=True, exist_ok=True)

(TESTS / "__init__.py").write_text(
    '"""QPX_ALPHA Test Package"""\n',
    encoding="utf-8"
)

readme = textwrap.dedent("""
# QPX_ALPHA Test Suite

Every core service should have a corresponding test.

Naming convention:

test_<module>.py

Examples:

test_config.py

test_logger.py

test_event_bus.py

Future:

test_health.py

test_launcher.py
""").strip()

(TESTS / "README.md").write_text(readme + "\n", encoding="utf-8")

runner = textwrap.dedent("""
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).parent

tests = sorted(ROOT.glob("test_*.py"))

print("=" * 60)
print("Running QPX_ALPHA Test Suite")
print("=" * 60)

passed = 0
failed = 0

for test in tests:
    print(f"\\nRunning {test.name}")

    result = subprocess.run(
        [sys.executable, str(test)]
    )

    if result.returncode == 0:
        print("PASS")
        passed += 1
    else:
        print("FAIL")
        failed += 1

print("\\n" + "=" * 60)
print(f"Passed : {passed}")
print(f"Failed : {failed}")
print("=" * 60)

sys.exit(1 if failed else 0)
""").strip()

(TESTS / "run_all_tests.py").write_text(
    runner + "\n",
    encoding="utf-8"
)

# Move existing tests if present
for name in ("test_logging.py", "test_event_bus.py"):
    src = ROOT / name
    dst = TESTS / name
    if src.exists() and not dst.exists():
        shutil.move(str(src), str(dst))
        print(f"Moved {name} -> tests/")

print("=" * 60)
print("Test Framework Created")
print("=" * 60)
print("Run:")
print("python tests/run_all_tests.py")