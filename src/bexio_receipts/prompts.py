"""System prompts for Vision-Language Models."""

import json

import structlog

from .config import Settings
from .models import AccountAssignment, RawVatRow, VisionExtraction

logger = structlog.get_logger(__name__)

VISION_PROMPT_DE = (
    "Du bist ein Experte für die Schweizer Buchhaltung. Deine Aufgabe ist es, strukturierte Daten aus Belegen zu extrahieren.\n"
    "Gib AUSSCHLIESSLICH ein gültiges JSON-Objekt zurück. Schreibe KEINE Erklärungen, KEINE Markdown-Blöcke und KEINE Gedanken.\n"
    "Beginne deine Antwort mit '{{' und beende sie mit '}}'.\n\n"
    "ERFORDERLICHES SCHEMA:\n"
    "{schema}\n\n"
    "VERFÜGBARE KONTEN:\n"
    "{accounts}\n\n"
    "MWST: Der Standard-Satz ist {default_vat}%.\n"
)

VISION_PROMPT_EN = (
    "You are a strict JSON data extraction bot specializing in Swiss bookkeeping. "
    "You MUST output ONLY a valid JSON object. NEVER output markdown blocks, NEVER output explanations, NEVER output thoughts. "
    "Start your response with '{{' and end with '}}'.\n\n"
    "REQUIRED SCHEMA:\n"
    "{schema}\n\n"
    "AVAILABLE ACCOUNTS:\n"
    "{accounts}\n\n"
    "VAT: Default is {default_vat}%.\n"
)

VISION_PROMPT_FR = (
    "Tu es un expert en comptabilité suisse. Ta tâche est d'extraire des données structurées des reçus.\n"
    "Retourne UNIQUEMENT un objet JSON valide. N'écris AUCUNE explication, AUCUN bloc Markdown et AUCUNE réflexion.\n"
    "Commence ta réponse par '{{' et termine-la par '}}'.\n\n"
    "SCHÉMA REQUIS:\n"
    "{schema}\n\n"
    "COMPTES DISPONIBLES:\n"
    "{accounts}\n\n"
    "TVA: Le taux par défaut est de {default_vat}%.\n"
)

_TEMPLATES: dict[str, str] = {
    "de": VISION_PROMPT_DE,
    "en": VISION_PROMPT_EN,
    "fr": VISION_PROMPT_FR,
}

# Type-safe example: if VisionExtraction changes, this adapts or breaks at import time.
_PROMPT_EXAMPLE = VisionExtraction(
    merchant_name="Migros",
    transaction_date="2026-01-15",
    total_incl_vat=99.99,
    currency="CHF",
    subtotal_excl_vat=92.50,
    vat_rate_pct=8.1,
    vat_amount=7.49,
    vat_rows=[
        RawVatRow(rate=8.1, net_amount=92.50, vat_amount=7.49, total_amount=99.99)
    ],
    account_assignments=[
        AccountAssignment(
            vat_rate=8.1,
            account_id="4200",
            account_name="Einkauf Handelsware",
            confidence="high",
            reasoning="Lebensmittel",
        )
    ],
)


def build_vision_system_prompt(settings: Settings) -> str:
    """Generate the system prompt for vision extraction based on settings."""
    # Use the type-safe example and strip legacy None fields
    example = _PROMPT_EXAMPLE.model_dump(exclude_none=True)

    accounts_context = "\n".join([
        f"- {acc_id}: {desc}" for acc_id, desc in settings.bexio_accounts.items()
    ])

    lang = settings.vision_prompt_language.lower()
    template = _TEMPLATES.get(lang)
    if template is None:
        logger.warning("unknown_prompt_language", lang=lang, fallback="en")
        template = VISION_PROMPT_EN

    return template.format(
        schema=json.dumps(example, indent=2),
        accounts=accounts_context,
        default_vat=settings.default_vat_rate,
    )
