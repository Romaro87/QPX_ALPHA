"""
============================================================
QPX CONTEXT COMPILER
Version 1.0
============================================================

Reads all intelligence output and compiles a complete
AI-ready project snapshot.

Outputs

qpx_context.py
QPX_AI_BOOTSTRAP.md
PROJECT_SUMMARY.md
manifest.json
README_CONTEXT.md
"""

import json
import os
import zipfile
from datetime import datetime

ROOT = "/storage/emulated/0/QPX_ALPHA"

OUTPUT = os.path.join(
    ROOT,
    "QPX_INTELLIGENCE",
    "output"
)


class ContextCompiler:

    def __init__(self):

        self.context = {}

        self.generated = datetime.now().isoformat()

    def load_json(self, filename):

        path = os.path.join(OUTPUT, filename)

        if not os.path.exists(path):
            return {}

        try:

            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)

        except Exception as e:

            return {"error": str(e)}

    def load(self):

        self.context["architecture"] = self.load_json(
            "architecture.json"
        )

        self.context["dependency"] = self.load_json(
            "dependency_analysis.json"
        )

        self.context["history"] = self.load_json(
            "history.json"
        )

        self.context["recommendations"] = self.load_json(
            "recommendations.json"
        )

        self.context["metrics"] = self.load_json(
            "metrics.json"
        )

        self.context["project_graph"] = self.load_json(
            "project_graph.json"
        )

    def determine_health(self):

        metrics = self.context.get("metrics", {})

        modules = metrics.get("modules", 0)

        if modules >= 100:
            return "Excellent"

        if modules >= 50:
            return "Good"

        if modules >= 20:
            return "Developing"

        return "Early"

    def write_context(self):

        path = os.path.join(
            OUTPUT,
            "qpx_context.py"
        )

        arch = self.context.get("architecture", {})
        dep = self.context.get("dependency", {})
        metrics = self.context.get("metrics", {})

        with open(path, "w", encoding="utf-8") as f:

            f.write("# AUTO GENERATED\n")
            f.write("# DO NOT EDIT\n\n")

            f.write("PROJECT_NAME = 'QPX Alpha'\n")
            f.write("VERSION = '1.0'\n")
            f.write(f"GENERATED = '{self.generated}'\n")
            f.write(f"HEALTH = '{self.determine_health()}'\n\n")

            f.write("METRICS = ")
            f.write(repr(metrics))
            f.write("\n\n")

            f.write("ARCHITECTURE = ")
            f.write(repr(arch.get("summary", {})))
            f.write("\n\n")

            f.write("DEPENDENCY = ")
            f.write(repr(dep.get("summary", {})))
            f.write("\n")

    def write_bootstrap(self):

        path = os.path.join(
            OUTPUT,
            "QPX_AI_BOOTSTRAP.md"
        )

        arch = self.context.get("architecture", {})
        dep = self.context.get("dependency", {})
        metrics = self.context.get("metrics", {})

        with open(path, "w", encoding="utf-8") as f:

            f.write("# QPX AI BOOTSTRAP\n\n")

            f.write("## Project\n\n")

            f.write("QPX Alpha\n\n")

            f.write(f"Generated: {self.generated}\n\n")

            f.write(f"Health: **{self.determine_health()}**\n\n")

            f.write("## Metrics\n\n")

            for k, v in metrics.items():
                f.write(f"- {k}: {v}\n")

            f.write("\n")

            if arch:

                f.write("## Architecture\n\n")

                for k, v in arch.get("summary", {}).items():
                    f.write(f"- {k}: {v}\n")

                f.write("\n")

            if dep:

                f.write("## Dependencies\n\n")

                for k, v in dep.get("summary", {}).items():
                    f.write(f"- {k}: {v}\n")

                f.write("\n")

            f.write("## Next Recommended Tasks\n\n")

            f.write("- Replace placeholder modules\n")
            f.write("- Expand dependency graph\n")
            f.write("- Build AI memory database\n")
            f.write("- Add snapshot history\n")
            f.write("- Add Git integration\n")

    def write_manifest(self):

        path = os.path.join(
            OUTPUT,
            "manifest.json"
        )

        manifest = {

            "project": "QPX Alpha",

            "generated": self.generated,

            "health": self.determine_health(),

            "files": [

                "architecture.json",

                "dependency_analysis.json",

                "history.json",

                "recommendations.json",

                "metrics.json",

                "project_graph.json",

                "qpx_context.py",

                "QPX_AI_BOOTSTRAP.md",

                "PROJECT_SUMMARY.md",

                "README_CONTEXT.md"

            ]

        }

        with open(path, "w", encoding="utf-8") as f:

            json.dump(
                manifest,
                f,
                indent=4
            )

    def write_readme(self):

        path = os.path.join(
            OUTPUT,
            "README_CONTEXT.md"
        )

        with open(path, "w", encoding="utf-8") as f:

            f.write("# QPX Context Package\n\n")

            f.write(
                "This folder contains an AI-ready snapshot "
                "of the current QPX Alpha project.\n\n"
            )

            f.write(
                "Upload the entire exported package into "
                "future AI sessions for immediate context.\n"
            )

    def export_zip(self):

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

                full = os.path.join(
                    OUTPUT,
                    file
                )

                if os.path.isfile(full):

                    z.write(
                        full,
                        arcname=file
                    )

        return zip_path

    def run(self):

        self.load()

        self.write_context()

        self.write_bootstrap()

        self.write_manifest()

        self.write_readme()

        return self.export_zip()


def main():

    compiler = ContextCompiler()

    zip_file = compiler.run()

    print("=" * 60)
    print("QPX CONTEXT COMPILER")
    print("=" * 60)
    print()
    print("STATUS : COMPLETE")
    print()
    print(zip_file)


if __name__ == "__main__":
    main()