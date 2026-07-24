#!/usr/bin/env python3
"""
=============================================================
QPX CONTEXT WRITER
Step 15.6 Part 1

Reads

    scanner.json
    architecture.json
    history.json
    recommendations.json
    dependency_analysis.json

Produces

    qpx_context.py

Purpose

Generate the master AI context file for GPT Projects.

=============================================================
"""

import os
import json
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


class ContextWriter:

    def __init__(self):

        self.generated = datetime.datetime.now().isoformat()

        self.scanner = self.load("scanner.json")

        self.architecture = self.load("architecture.json")

        self.history = self.load("history.json")

        self.recommendations = self.load(
            "recommendations.json"
        )

        self.dependencies = self.load(
            "dependency_analysis.json"
        )

    def load(self, filename):

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

    def write(self):

        with open(
            OUTPUT,
            "w",
            encoding="utf-8"
        ) as f:

            self.write_header(f)

            self.write_summary(f)

            #
            # Remaining sections
            # added in later parts.
            #

        print("=" * 60)
        print("QPX CONTEXT WRITER")
        print("=" * 60)
        print()
        print("Output")
        print(OUTPUT)
        print()
        print("STATUS: COMPLETE")

    def write_header(self, f):

        f.write('"""\n')

        f.write("=" * 60 + "\n")

        f.write("QPX ALPHA\n")

        f.write("MASTER AI CONTEXT\n")

        f.write("=" * 60 + "\n\n")

        f.write(
            "Generated: "
            + self.generated
            + "\n\n"
        )

        f.write(
            "Purpose\n"
        )

        f.write(
            "-------\n"
        )

        f.write(
            "This file provides the complete\n"
        )

        f.write(
            "AI context for QPX Alpha.\n\n"
        )

        f.write(
            "Upload this file into ChatGPT Projects.\n\n"
        )

        f.write(
            "Treat the information below\n"
        )

        f.write(
            "as the authoritative overview\n"
        )

        f.write(
            "of the project.\n\n"
        )

        f.write('"""\n\n')

    def write_summary(self, f):

        stats = self.scanner["statistics"]

        health = self.history["project_health"]

        f.write("PROJECT_SUMMARY = {\n")

        f.write(
            f'    "generated":"{self.generated}",\n'
        )

        f.write(
            f'    "python_modules":{stats["python"]},\n'
        )

        f.write(
            f'    "reports":{stats["reports"]},\n'
        )

        f.write(
            f'    "json_files":{stats["json"]},\n'
        )

        f.write(
            f'    "csv_files":{stats["csv"]},\n'
        )

        f.write(
            f'    "duplicate_modules":{len(self.scanner["duplicates"])},\n'
        )

        f.write(
            f'    "overall_health":"{health["overall"]}"\n'
        )

        f.write("}\n\n")


def main():

    ContextWriter().write()


if __name__ == "__main__":

    main()