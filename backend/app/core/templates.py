from pathlib import Path
from typing import Any, Final

from jinja2 import Environment, FileSystemLoader, select_autoescape


class TemplatesHelper:
    def __init__(self):
        self._templates_dir = Path(__file__).resolve().parent.parent / "templates"
        self._template_env = Environment(
            loader=FileSystemLoader(self._templates_dir),
            autoescape=select_autoescape(["html", "xml"]),  # Escape user input against XSS
        )

    def render_template(self, template_name: str, **context: Any) -> str:
        template = self._template_env.get_template(template_name)
        return template.render(**context)


templates_helper: Final[TemplatesHelper] = TemplatesHelper()
