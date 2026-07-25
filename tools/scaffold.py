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
