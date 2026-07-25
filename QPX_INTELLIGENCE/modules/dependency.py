"""
============================================================
QPX DEPENDENCY ANALYZER
Version 2.0
============================================================

Builds a dependency graph of the project.

Outputs

dependency_analysis.json
project_graph.json
metrics.json
"""

import ast
import json
import os
from collections import defaultdict

ROOT = "/storage/emulated/0/QPX_ALPHA"
OUTPUT = os.path.join(ROOT, "QPX_INTELLIGENCE", "output")


class DependencyAnalyzer:

    def __init__(self):

        self.graph = defaultdict(list)

        self.import_count = defaultdict(int)

        self.python_modules = {}

        self.orphans = []

        self.circular = []

        self.metrics = {}

    def discover_modules(self):

        for root, _, files in os.walk(ROOT):

            if ".git" in root:
                continue

            if "QPX_INTELLIGENCE/output" in root:
                continue

            for file in files:

                if file.endswith(".py"):

                    full = os.path.join(root, file)

                    rel = os.path.relpath(full, ROOT)

                    module = os.path.splitext(file)[0]

                    self.python_modules[module] = rel

    def scan(self):

        self.discover_modules()

        for module, rel in self.python_modules.items():

            full = os.path.join(ROOT, rel)

            imports = self.scan_file(full)

            self.graph[module] = imports

            for item in imports:

                self.import_count[item] += 1

        self.find_orphans()

        self.find_circular()

        self.build_metrics()

    def scan_file(self, path):

        imports = []

        try:

            with open(path, "r", encoding="utf-8") as f:

                tree = ast.parse(f.read())

            for node in ast.walk(tree):

                if isinstance(node, ast.Import):

                    for name in node.names:

                        imports.append(name.name.split(".")[0])

                elif isinstance(node, ast.ImportFrom):

                    if node.module:

                        imports.append(node.module.split(".")[0])

        except Exception:

            pass

        return sorted(set(imports))

    def find_orphans(self):

        for module in self.python_modules:

            if self.import_count[module] == 0:

                self.orphans.append(module)

    def find_circular(self):

        for module in self.graph:

            for dep in self.graph[module]:

                if dep in self.graph:

                    if module in self.graph[dep]:

                        pair = sorted([module, dep])

                        if pair not in self.circular:

                            self.circular.append(pair)

    def build_metrics(self):

        total_edges = sum(len(v) for v in self.graph.values())

        connected = sorted(

            self.import_count.items(),

            key=lambda x: x[1],

            reverse=True

        )[:20]

        self.metrics = {

            "modules": len(self.python_modules),

            "dependencies": total_edges,

            "orphans": len(self.orphans),

            "circular_dependencies": len(self.circular),

            "most_connected": connected

        }

    def save(self):

        os.makedirs(OUTPUT, exist_ok=True)

        dependency_report = {

            "summary": self.metrics,

            "orphans": sorted(self.orphans),

            "circular_dependencies": self.circular

        }

        graph = {

            "nodes": []

        }

        for module in sorted(self.graph):

            graph["nodes"].append({

                "module": module,

                "imports": self.graph[module]

            })

        with open(

            os.path.join(OUTPUT, "dependency_analysis.json"),

            "w",

            encoding="utf-8"

        ) as f:

            json.dump(dependency_report, f, indent=4)

        with open(

            os.path.join(OUTPUT, "project_graph.json"),

            "w",

            encoding="utf-8"

        ) as f:

            json.dump(graph, f, indent=4)

        with open(

            os.path.join(OUTPUT, "metrics.json"),

            "w",

            encoding="utf-8"

        ) as f:

            json.dump(self.metrics, f, indent=4)

        return dependency_report


def main():

    analyzer = DependencyAnalyzer()

    analyzer.scan()

    report = analyzer.save()

    print("=" * 60)
    print("QPX DEPENDENCY ANALYZER")
    print("=" * 60)

    print()

    print("Modules               :", report["summary"]["modules"])
    print("Dependencies          :", report["summary"]["dependencies"])
    print("Possible Orphans      :", report["summary"]["orphans"])
    print("Circular Dependencies :", report["summary"]["circular_dependencies"])

    print()

    print("Most Connected Modules")

    for module, count in report["summary"]["most_connected"][:10]:

        print(f"{module:<30} {count}")

    print()

    print("Output")

    print(os.path.join(OUTPUT, "dependency_analysis.json"))

    print(os.path.join(OUTPUT, "project_graph.json"))

    print(os.path.join(OUTPUT, "metrics.json"))


if __name__ == "__main__":
    main()