from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]


def snake(name):
    out = ""

    for c in name:
        if c.isupper() and out:
            out += "_"

        out += c.lower()

    return out


def render(template, **kwargs):

    text = template.read_text()

    for k, v in kwargs.items():
        text = text.replace("{" + k + "}", v)

    return text


def write(path, text):

    if path.exists():
        print("Exists:", path)
        return

    path.parent.mkdir(parents=True, exist_ok=True)

    path.write_text(text)

    print("Created:", path)


def create_module(name):

    module = snake(name)

    tpl = ROOT / "tools/templates/module.tpl"

    test = ROOT / "tools/templates/test.tpl"

    readme = ROOT / "tools/templates/readme.tpl"

    write(
        ROOT / f"core/{module}.py",
        render(tpl, class_name=name),
    )

    write(
        ROOT / f"tests/test_{module}.py",
        render(
            test,
            class_name=name,
            module_name=module,
        ),
    )

    write(
        ROOT / f"docs/modules/{module.upper()}.md",
        render(
            readme,
            class_name=name,
        ),
    )


def main():

    if len(sys.argv) < 3:
        print("Usage:")
        print("python -m tools.scaffold module ModuleName")
        return

    command = sys.argv[1]

    name = sys.argv[2]

    if command == "module":
        create_module(name)
    else:
        print("Unknown command")


if __name__ == "__main__":
    main()