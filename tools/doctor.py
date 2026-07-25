from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def exists(path):
    return (ROOT / path).exists()


def check(title, condition):
    status = "PASS" if condition else "FAIL"
    print(f"{title:<30}{status}")
    return condition


def count(pattern):
    return len(list(ROOT.glob(pattern)))


def repository_clean():
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        return len(result.stdout.strip()) == 0
    except Exception:
        return False


def check_adr_sequence():
    adr_dir = ROOT / "docs" / "adr"

    if not adr_dir.exists():
        return False

    files = sorted(adr_dir.glob("ADR-*.md"))

    numbers = []

    for f in files:
        try:
            numbers.append(int(f.stem.split("-")[1]))
        except Exception:
            pass

    if not numbers:
        return False

    expected = list(range(min(numbers), max(numbers) + 1))

    return numbers == expected


def doctor():

    print("=" * 60)
    print("QPX_ALPHA DOCTOR v3")
    print("=" * 60)

    checks = []

    checks.append(check("Python", sys.version_info.major >= 3))

    checks.append(check("Git Repository", exists(".git")))

    checks.append(check("Git Ignore", exists(".gitignore")))

    checks.append(check("README", exists("README.md") or exists("readme.md")))

    checks.append(check("Constitution", exists("docs/CONSTITUTION.md")))

    checks.append(check("Architecture", exists("docs/ARCHITECTURE.md")))

    checks.append(check("Roadmap", exists("docs/ROADMAP.md")))

    checks.append(check("Project Charter", exists("docs/PROJECT_CHARTER.md")))

    checks.append(check("Changelog", exists("docs/CHANGELOG.md")))

    checks.append(check("ADR Sequence", check_adr_sequence()))

    checks.append(check("Module Registry", exists("core/module_registry.py")))

    checks.append(check("Service Registry", exists("core/service_registry.py")))

    checks.append(check("Templates", exists("tools/templates")))

    print()

    print("Statistics")
    print("-" * 60)

    print(f"Modules       : {count('core/*.py')}")
    print(f"Tests         : {count('tests/test_*.py')}")
    print(f"Templates     : {count('tools/templates/*')}")
    print(f"Documents     : {count('docs/**/*.md')}")
    print(f"Legacy Files  : {count('legacy/**/*')}")

    print()

    clean = repository_clean()

    print("Repository")
    print("-" * 60)

    print("Status        :", "CLEAN" if clean else "DIRTY")

    print()

    overall = all(checks) and clean

    print("=" * 60)

    print("OVERALL :", "EXCELLENT" if overall else "ATTENTION REQUIRED")

    print("=" * 60)


if __name__ == "__main__":
    doctor()