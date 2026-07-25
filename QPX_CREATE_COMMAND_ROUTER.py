"""
QPX_CREATE_COMMAND_ROUTER.py

Sprint 5
Milestone 4

Creates the Command Router and upgrades the scaffold.
"""

from pathlib import Path

ROOT = Path(__file__).parent


def write(relative_path, contents):
    path = ROOT / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(contents.strip() + "\n", encoding="utf-8")
    print(f"Created: {relative_path}")


print("=" * 60)
print("QPX_ALPHA Command Router")
print("=" * 60)

# ---------------------------------------------------
# Command Router
# ---------------------------------------------------

write(
    "tools/command_router.py",
'''
"""
Command Router

Routes scaffold commands to registered handlers.
"""


class CommandRouter:

    def __init__(self):
        self._commands = {}

    def register(self, name, handler):
        self._commands[name] = handler

    def execute(self, name, *args):

        if name not in self._commands:
            raise ValueError(f"Unknown command: {name}")

        return self._commands[name](*args)

    def commands(self):
        return sorted(self._commands.keys())

    def count(self):
        return len(self._commands)


router = CommandRouter()
'''
)

# ---------------------------------------------------
# Scaffold Upgrade
# ---------------------------------------------------

write(
    "tools/scaffold.py",
'''
"""
QPX_ALPHA Scaffold Tool
"""

import sys

from tools.command_router import router
from tools.generator_engine import GeneratorEngine

generator = GeneratorEngine()


router.register(
    "module",
    lambda name: generator.generate_module(name)
)

router.register(
    "service",
    lambda name: generator.generate_service(name)
)

router.register(
    "package",
    lambda name: generator.generate_package(name)
)

router.register(
    "test",
    lambda name: generator.generate_test(name)
)

router.register(
    "readme",
    lambda name: generator.generate_readme(name)
)

router.register(
    "config",
    lambda name: generator.generate_config(name)
)

router.register(
    "plugin",
    lambda name: generator.generate_plugin(name)
)

router.register(
    "adr",
    lambda name: generator.generate_adr(name)
)


def usage():

    print("=" * 60)
    print("QPX_ALPHA Scaffold")
    print("=" * 60)
    print()

    print("Available Commands:")

    for command in router.commands():
        print(" ", command)

    print()


def main():

    if len(sys.argv) < 3:
        usage()
        return

    command = sys.argv[1]
    argument = sys.argv[2]

    router.execute(command, argument)

    print("Generation complete.")


if __name__ == "__main__":
    main()
'''
)

# ---------------------------------------------------
# Test
# ---------------------------------------------------

write(
    "tests/test_command_router.py",
'''
from tools.command_router import CommandRouter

router = CommandRouter()

router.register(
    "hello",
    lambda: "world"
)

assert router.count() == 1
assert router.execute("hello") == "world"

print("Command Router PASS")
'''
)

print()
print("=" * 60)
print("SPRINT 5 MILESTONE 4 COMPLETE")
print("=" * 60)
print("Created:")
print("  tools/command_router.py")
print("  tools/scaffold.py")
print("  tests/test_command_router.py")
print("=" * 60)