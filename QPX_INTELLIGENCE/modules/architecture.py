"""
============================================================
QPX Architecture Analyzer
Version: 1.0
============================================================

Scans every Python file using AST and builds a structural
description of the project.

Outputs:
    architecture.json
"""

import ast
import os
import json

ROOT = "/storage/emulated/0/QPX_ALPHA"


class ArchitectureAnalyzer:

    def __init__(self):
        self.results = {
            "files": [],
            "summary": {
                "python_files": 0,
                "classes": 0,
                "functions": 0,
                "imports": 0,
                "entry_points": 0
            }
        }

    def analyze(self):

        for root, _, files in os.walk(ROOT):

            if ".git" in root:
                continue

            if "QPX_INTELLIGENCE/output" in root:
                continue

            for file in files:

                if not file.endswith(".py"):
                    continue

                full = os.path.join(root, file)

                rel = os.path.relpath(full, ROOT)

                self.results["summary"]["python_files"] += 1

                self.results["files"].append(
                    self.scan_file(full, rel)
                )

        return self.results

    def scan_file(self, path, rel):

        data = {
            "path": rel,
            "classes": [],
            "functions": [],
            "imports": [],
            "entry_point": False
        }

        try:

            with open(path, "r", encoding="utf-8") as f:
                tree = ast.parse(f.read())

            for node in ast.walk(tree):

                if isinstance(node, ast.ClassDef):

                    data["classes"].append(node.name)

                    self.results["summary"]["classes"] += 1

                elif isinstance(node, ast.FunctionDef):

                    data["functions"].append(node.name)

                    self.results["summary"]["functions"] += 1

                elif isinstance(node, ast.Import):

                    for name in node.names:

                        data["imports"].append(name.name)

                        self.results["summary"]["imports"] += 1

                elif isinstance(node, ast.ImportFrom):

                    if node.module:

                        data["imports"].append(node.module)

                        self.results["summary"]["imports"] += 1

            with open(path, "r", encoding="utf-8") as f:

                text = f.read()

                if '__name__ == "__main__"' in text:

                    data["entry_point"] = True

                    self.results["summary"]["entry_points"] += 1

        except Exception as e:

            data["error"] = str(e)

        return data


def save(output_folder):

    analyzer = ArchitectureAnalyzer()

    results = analyzer.analyze()

    outfile = os.path.join(
        output_folder,
        "architecture.json"
    )

    with open(outfile, "w", encoding="utf-8") as f:

        json.dump(results, f, indent=4)

    return results


if __name__ == "__main__":

    output = os.path.join(
        ROOT,
        "QPX_INTELLIGENCE",
        "output"
    )

    os.makedirs(output, exist_ok=True)

    data = save(output)

    print("=" * 60)
    print("QPX ARCHITECTURE ANALYZER")
    print("=" * 60)

    print("Python Files :", data["summary"]["python_files"])
    print("Classes      :", data["summary"]["classes"])
    print("Functions    :", data["summary"]["functions"])
    print("Imports      :", data["summary"]["imports"])
    print("Entry Points :", data["summary"]["entry_points"])

    print()
    print("Output")
    print(os.path.join(output, "architecture.json"))