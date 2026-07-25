#!/usr/bin/env python3

"""
============================================================
QPX CONTEXT EXPORTER
Version : 1.0
Author  : QPX Intelligence
============================================================

Master launcher for the QPX Intelligence System.

Pipeline

Project Scanner
↓

Architecture Analyzer
↓

Dependency Analyzer
↓

History Analyzer
↓

Recommendation Engine
↓

Context Compiler
↓

ZIP Export

"""

import os
import json
import datetime
import traceback
import zipfile

ROOT = "/storage/emulated/0/QPX_ALPHA"

INTELLIGENCE = os.path.join(ROOT, "QPX_INTELLIGENCE")

MODULES = os.path.join(INTELLIGENCE, "modules")
CACHE = os.path.join(INTELLIGENCE, "cache")
OUTPUT = os.path.join(INTELLIGENCE, "output")
LOGS = os.path.join(INTELLIGENCE, "logs")
TEMPLATES = os.path.join(INTELLIGENCE, "templates")


def ensure_structure():
    """Create required folders."""

    folders = [
        INTELLIGENCE,
        MODULES,
        CACHE,
        OUTPUT,
        LOGS,
        TEMPLATES,
    ]

    for folder in folders:
        os.makedirs(folder, exist_ok=True)


def log(message):
    stamp = datetime.datetime.now().isoformat(timespec="seconds")
    print(stamp, message)


def new_context():
    """Shared project context used by every module."""

    return {
        "project": {
            "name": "QPX Alpha",
            "version": "1.0",
            "generated": datetime.datetime.now().isoformat()
        },

        "files": [],

        "architecture": {},

        "dependencies": {},

        "history": {},

        "recommendations": [],

        "metrics": {}
    }


class BaseModule:

    name = "Unnamed Module"

    def run(self, context):
        log(self.name)
        return context


class ProjectScanner(BaseModule):

    name = "Scanning Project"

    def run(self, context):

        super().run(context)

        py = 0
        jsons = 0
        csvs = 0
        markdown = 0

        for root, _, files in os.walk(ROOT):

            if ".git" in root:
                continue

            for file in files:

                full = os.path.join(root, file)

                rel = os.path.relpath(full, ROOT)

                size = os.path.getsize(full)

                context["files"].append({
                    "path": rel,
                    "size": size
                })

                ext = file.lower()

                if ext.endswith(".py"):
                    py += 1

                elif ext.endswith(".json"):
                    jsons += 1

                elif ext.endswith(".csv"):
                    csvs += 1

                elif ext.endswith(".md"):
                    markdown += 1

        context["metrics"] = {
            "python_files": py,
            "json_files": jsons,
            "csv_files": csvs,
            "markdown_files": markdown,
            "total_files": len(context["files"])
        }

        return context


class PlaceholderModule(BaseModule):

    def __init__(self, name):
        self.name = name


def write_json(name, data):

    path = os.path.join(OUTPUT, name)

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)


def write_summary(context):

    path = os.path.join(
        OUTPUT,
        "PROJECT_SUMMARY.md"
    )

    m = context["metrics"]

    with open(path, "w", encoding="utf-8") as f:

        f.write("# QPX Project Summary\n\n")

        f.write(
            f"Generated: {context['project']['generated']}\n\n"
        )

        f.write(
            f"Python Files: {m['python_files']}\n"
        )

        f.write(
            f"JSON Files: {m['json_files']}\n"
        )

        f.write(
            f"CSV Files: {m['csv_files']}\n"
        )

        f.write(
            f"Markdown Files: {m['markdown_files']}\n"
        )

        f.write(
            f"Total Files: {m['total_files']}\n"
        )


def create_zip():

    zip_path = os.path.join(
        ROOT,
        "QPX_CONTEXT_EXPORT.zip"
    )

    with zipfile.ZipFile(
        zip_path,
        "w",
        zipfile.ZIP_DEFLATED
    ) as z:

        for file in os.listdir(OUTPUT):

            full = os.path.join(OUTPUT, file)

            z.write(
                full,
                arcname=file
            )

    return zip_path


def main():

    print()

    print("=" * 60)
    print("QPX CONTEXT EXPORTER")
    print("=" * 60)

    ensure_structure()

    context = new_context()

    modules = [

        ProjectScanner(),

        PlaceholderModule(
            "Architecture Analyzer"
        ),

        PlaceholderModule(
            "Dependency Analyzer"
        ),

        PlaceholderModule(
            "History Analyzer"
        ),

        PlaceholderModule(
            "Recommendation Engine"
        )

    ]

    try:

        for module in modules:

            context = module.run(context)

        write_json(
            "manifest.json",
            context
        )

        write_summary(
            context
        )

        zip_path = create_zip()

        print()
        print("=" * 60)
        print("EXPORT COMPLETE")
        print("=" * 60)
        print(zip_path)

    except Exception:

        traceback.print_exc()


if __name__ == "__main__":
    main()