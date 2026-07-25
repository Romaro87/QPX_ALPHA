from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
TESTS = ROOT / "tests"

print("=" * 60)
print("Running QPX_ALPHA Test Suite")
print("=" * 60)

passed = 0
failed = 0

for test in sorted(TESTS.glob("test_*.py")):
    module = f"tests.{test.stem}"

    print(f"\nRunning {module}")

    result = subprocess.run(
        [sys.executable, "-m", module],
        cwd=ROOT
    )

    if result.returncode == 0:
        print("PASS")
        passed += 1
    else:
        print("FAIL")
        failed += 1

print("\n" + "=" * 60)
print(f"Passed : {passed}")
print(f"Failed : {failed}")
print("=" * 60)

sys.exit(1 if failed else 0)