"""
Template Engine

Loads reusable templates from tools/templates.
"""

from pathlib import Path


class TemplateEngine:

    def __init__(self):
        self.template_dir = (
            Path(__file__).parent / "templates"
        )

    def load(self, template_name):

        path = self.template_dir / template_name

        if not path.exists():
            raise FileNotFoundError(template_name)

        return path.read_text(encoding="utf-8")

    def render(self, template_name, **kwargs):

        text = self.load(template_name)

        for key, value in kwargs.items():
            text = text.replace("{{" + key + "}}", str(value))

        return text
