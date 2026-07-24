#!/usr/bin/env python3
"""
=============================================================
QPX COMPILER UPGRADER
Part 1

Purpose
-------
Safely upgrades QPX_CONTEXT_COMPILER.py

Current Upgrade

    Part 2

Future

    Part 3
    Part 4
    Part 5

=============================================================
"""

import os
import shutil
import datetime
import py_compile

ROOT = "/storage/emulated/0/QPX_ALPHA"

COMPILER = os.path.join(
    ROOT,
    "QPX_CONTEXT_COMPILER.py"
)

BACKUP_DIR = os.path.join(
    ROOT,
    "QPX_CONTEXT",
    "compiler_backups"
)

REPORT = os.path.join(
    ROOT,
    "QPX_CONTEXT",
    "compiler_upgrade_report.txt"
)


class CompilerUpgrader:

    VERSION = "1.0"

    def __init__(self):

        os.makedirs(
            BACKUP_DIR,
            exist_ok=True
        )

    #######################################################

    def backup(self):

        stamp = datetime.datetime.now().strftime(

            "%Y%m%d_%H%M%S"

        )

        dst = os.path.join(

            BACKUP_DIR,

            f"QPX_CONTEXT_COMPILER_{stamp}.py"

        )

        shutil.copy2(

            COMPILER,

            dst

        )

        return dst

    #######################################################

    def load(self):

        with open(

            COMPILER,

            "r",

            encoding="utf-8"

        ) as f:

            return f.read()

    #######################################################

    def save(self, text):

        with open(

            COMPILER,

            "w",

            encoding="utf-8"

        ) as f:

            f.write(text)

    #######################################################

    def syntax_check(self):

        try:

            py_compile.compile(

                COMPILER,

                doraise=True

            )

            return True

        except Exception as e:

            print(e)

            return False

    #######################################################

    def detect_version(self, text):

        if "ContextCompiler" in text:

            return "1.x"

        return "Unknown"

    #######################################################

    def report(

        self,

        backup,

        version,

        syntax

    ):

        with open(

            REPORT,

            "w",

            encoding="utf-8"

        ) as f:

            f.write(

                "QPX COMPILER UPGRADER\n"

            )

            f.write(

                "=" * 50 + "\n\n"

            )

            f.write(

                f"Backup : {backup}\n"

            )

            f.write(

                f"Version : {version}\n"

            )

            f.write(

                f"Syntax : {syntax}\n"

            )

    #######################################################

    def run(self):

        print("=" * 60)

        print("QPX COMPILER UPGRADER")

        print("=" * 60)

        backup = self.backup()

        text = self.load()

        version = self.detect_version(text)

        syntax = self.syntax_check()

        self.report(

            backup,

            version,

            syntax

        )

        print()

        print("Backup")

        print(backup)

        print()

        print("Compiler Version")

        print(version)

        print()

        print("Syntax")

        print(syntax)

        print()

        print("STATUS: READY")


def main():

    CompilerUpgrader().run()


if __name__ == "__main__":

    main()