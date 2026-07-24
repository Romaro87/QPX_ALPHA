#!/usr/bin/env python3
"""
============================================================
QPX CONTEXT COMPILER
Version 1.0
============================================================

Purpose
-------
Compile all QPX project intelligence into a single
Python context file for ChatGPT Projects.

Inputs

    scanner.json
    architecture.json
    history.json
    recommendations.json
    dependency_analysis.json

Outputs

    qpx_context.py

============================================================
"""

import os
import json
import pprint
import datetime

ROOT = "/storage/emulated/0/QPX_ALPHA"

CONTEXT = os.path.join(
    ROOT,
    "QPX_CONTEXT"
)

OUTPUT = os.path.join(
    ROOT,
    "qpx_context.py"
)


class ContextCompiler:

    VERSION = "1.0"

    def __init__(self):

        self.generated = (
            datetime.datetime.now().isoformat()
        )

        self.database = {}

    ##########################################################

    def load_json(self, filename):

        path = os.path.join(
            CONTEXT,
            filename
        )

        with open(
            path,
            "r",
            encoding="utf-8"
        ) as f:

            return json.load(f)

    ##########################################################

    def load_everything(self):

        print("Loading databases...")

        self.database["scanner"] = \
            self.load_json("scanner.json")

        self.database["architecture"] = \
            self.load_json("architecture.json")

        self.database["history"] = \
            self.load_json("history.json")

        self.database["recommendations"] = \
            self.load_json("recommendations.json")

        self.database["dependencies"] = \
            self.load_json(
                "dependency_analysis.json"
            )

    ##########################################################

    def validate(self):

        required = [

            "scanner",

            "architecture",

            "history",

            "recommendations",

            "dependencies"

        ]

        missing = [

            r for r in required

            if r not in self.database

        ]

        if missing:

            raise RuntimeError(

                "Missing databases: "

                + ", ".join(missing)

            )

    ##########################################################

    def build_metadata(self):

        scanner = self.database["scanner"]

        stats = scanner["statistics"]

        return {

            "project":

                "QPX Alpha",

            "compiler_version":

                self.VERSION,

            "generated":

                self.generated,

            "python_modules":

                stats["python"],

            "json_files":

                stats["json"],

            "reports":

                stats["reports"],

            "csv_files":

                stats["csv"],

            "duplicates":

                len(

                    scanner["duplicates"]

                )

        }

    ##########################################################

    def build_context(self):

        """
        Future Parts
        ------------

        statistics

        architecture

        history

        dependencies

        recommendations

        bootstrap

        """

        return {

            "metadata":

                self.build_metadata()

        }

    ##########################################################

    def save(self, context):

        with open(

            OUTPUT,

            "w",

            encoding="utf-8"

        ) as f:

            f.write('"""\n')

            f.write(

                "QPX Alpha AI Context\n\n"

            )

            f.write(

                "Generated automatically.\n"

            )

            f.write('"""\n\n')

            f.write(

                "QPX_CONTEXT = "

            )

            f.write(

                pprint.pformat(

                    context,

                    indent=4,

                    width=100,

                    sort_dicts=False

                )

            )

            f.write("\n")

    ##########################################################

    def run(self):

        print("=" * 60)

        print("QPX CONTEXT COMPILER")

        print("=" * 60)

        self.load_everything()

        self.validate()

        context = self.build_context()

        self.save(context)

        print()

        print("Output")

        print(OUTPUT)

        print()

        print("STATUS: COMPLETE")


def main():

    ContextCompiler().run()


if __name__ == "__main__":

    main()