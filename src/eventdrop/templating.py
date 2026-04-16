import json
from pathlib import Path

from fastapi.templating import Jinja2Templates
from markupsafe import Markup

BASE_DIR = Path(__file__).parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


def _tojson_filter(value, **kwargs):
    return Markup(json.dumps(value, **kwargs))


def _anonymize_email(email: str) -> str:
    """Anonymize the domain of an email address for public display.

    Keeps the local part intact, the first letter and TLD of the domain,
    and replaces the rest of the domain with 8 asterisks.
    Example: john.doe@example.com → john.doe@e********.com
    """
    try:
        local, domain = email.rsplit("@", 1)
        parts = domain.rsplit(".", 1)
        if len(parts) == 2:
            domain_name, tld = parts
            anon_domain = domain_name[0] + "********"
            return f"{local}@{anon_domain}.{tld}"
        return f"{local}@{domain[0]}********"
    except Exception:
        return email


templates.env.filters["tojson"] = _tojson_filter
templates.env.filters["anonymize_email"] = _anonymize_email
