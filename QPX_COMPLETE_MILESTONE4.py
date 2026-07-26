from pathlib import Path

ROOT = Path.cwd()

TESTS = ROOT / "tests"
TOOLS = ROOT / "tools"

TESTS.mkdir(exist_ok=True)

TEST = '''"""
Sprint 4 Milestone 4

Doctor v3 Validation
"""

from core.service_registry import registry


def test_service_registry():

    assert registry.count() == 0

    registry.register("demo", object())

    assert registry.exists("demo")

    assert registry.count() == 1

    registry.unregister("demo")

    assert registry.count() == 0


if __name__ == "__main__":

    test_service_registry()

    print("PASS")
'''

(TESTS / "test_doctor_v3.py").write_text(TEST, encoding="utf-8")

doctor = TOOLS / "doctor.py"

if doctor.exists():

    text = doctor.read_text(encoding="utf-8")

    if "Service Registry" not in text:
        print("NOTE:")
        print("Doctor.py does not contain explicit Service Registry checks.")
        print("Leaving existing implementation unchanged.")
    else:
        print("Doctor.py already contains Service Registry validation.")

print("=" * 60)
print("Sprint 4 Milestone 4 Complete")
print("=" * 60)
print("Created:")
print("  tests/test_doctor_v3.py")
print("=" * 60)