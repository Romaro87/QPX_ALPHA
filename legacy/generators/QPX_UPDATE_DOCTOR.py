from pathlib import Path
import textwrap

ROOT = Path("/storage/emulated/0/QPX_ALPHA")
TOOLS = ROOT / "tools"

doctor = textwrap.dedent("""
import importlib
import platform
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

CHECKS = [
    ("Configuration", "core.config"),
    ("Logger", "core.logger"),
    ("Health Service", "core.health"),
    ("Service Registry", "core.registry"),
    ("Module Registry", "core.module_registry"),
    ("Launcher", "app.launcher"),
    ("Dashboard", "dashboard"),
]

DIRECTORIES = [
    "data",
    "logs",
    "reports",
    "cache",
]


def check_import(module):
    try:
        importlib.import_module(module)
        return True
    except Exception:
        return False


def status(label, ok):
    print(f"{label:.<30}{'PASS' if ok else 'FAIL'}")
    return ok


def main():

    print("=" * 50)
    print("QPX_ALPHA Doctor")
    print("=" * 50)
    print()

    overall = True

    overall &= status(
        "Python Version",
        platform.python_version() >= "3.10"
    )

    overall &= status(
        "Project Structure",
        ROOT.exists()
    )

    print()

    for label, module in CHECKS:
        overall &= status(label, check_import(module))

    print()
    print("Directories")
    print()

    for directory in DIRECTORIES:
        overall &= status(
            directory.capitalize(),
            (ROOT / directory).exists()
        )

    print()

    overall &= status(
        "Git Repository",
        (ROOT / ".git").exists()
    )

    print()

    print("=" * 50)

    print(
        "Overall".ljust(30, "."),
        "HEALTHY" if overall else "UNHEALTHY"
    )


if __name__ == "__main__":
    main()
""").strip()

(TOOLS / "doctor.py").write_text(
    doctor + "\n",
    encoding="utf-8"
)

print("=" * 60)
print("Doctor v2 Created")
print("=" * 60)
print("Run:")
print("python -m tools.doctor")