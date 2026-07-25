from pathlib import Path
import textwrap

ROOT = Path("/storage/emulated/0/QPX_ALPHA")

APP = ROOT / "app"
APP.mkdir(exist_ok=True)

launcher = textwrap.dedent("""
from core.config import settings
from core.health import health
from core.logger import get_logger
from core.registry import registry

logger = get_logger(__name__)


def initialize():

    registry.register("config", settings)
    registry.register("health", health)

    print("=" * 50)
    print(f"{settings.PROJECT_NAME} v{settings.VERSION}")
    print("=" * 50)

    print()

    print("Initializing platform...")

    print()

    results = health.run()

    for service in registry.list_services():
        print(f"Registered: {service}")

    print()

    print("Health Check")

    print("-" * 30)

    for item, status in results.items():
        print(f"{item:<25} {'PASS' if status else 'FAIL'}")

    print()

    if health.healthy():
        print("Platform Status: HEALTHY")
    else:
        print("Platform Status: UNHEALTHY")


def menu():

    while True:

        print()

        print("Main Menu")

        print("-----------------------")

        print("1. Dashboard")

        print("2. Market Data")

        print("3. Portfolio")

        print("4. Strategy Center")

        print("5. Analytics")

        print("6. AI Assistant")

        print("7. Settings")

        print("0. Exit")

        choice = input("> ").strip()

        if choice == "0":
            print("Goodbye.")
            break

        print("Feature not implemented yet.")


def main():

    initialize()

    print()

    menu()


if __name__ == "__main__":
    main()
""").strip()

(APP / "launcher.py").write_text(
    launcher + "\n",
    encoding="utf-8"
)

test = textwrap.dedent("""
from app.launcher import initialize

initialize()

print()

print("Launcher initialization completed.")
""").strip()

(ROOT / "tests" / "test_launcher.py").write_text(
    test + "\n",
    encoding="utf-8"
)

print("=" * 60)
print("Launcher Created")
print("=" * 60)
print("Run:")
print("python -m app.launcher")