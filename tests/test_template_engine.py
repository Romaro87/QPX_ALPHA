from tools.template_engine import TemplateEngine

engine = TemplateEngine()

text = engine.render(
    "module.tpl",
    NAME="Example"
)

assert "Example" in text

print("Template Engine PASS")
