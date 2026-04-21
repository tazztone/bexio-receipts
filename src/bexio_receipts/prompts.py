"""System prompts for Vision-Language Models."""

import json

from .config import Settings

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


def build_vision_system_prompt(settings: Settings) -> str:
    """Generate the system prompt for vision extraction based on settings."""
    # Generate a clean example schema from the Pydantic model
    # _schema_dict = VisionExtraction.model_json_schema()

    # Create a simplified example for the model
    example = {
        "merchant_name": "Migros",
        "transaction_date": "2026-04-21",
        "total_incl_vat": 12.50,
        "currency": "CHF",
        "vat_rows": [
            {
                "rate": 2.6,
                "net_amount": 10.00,
                "vat_amount": 0.26,
                "total_amount": 10.26,
            }
        ],
        "account_assignments": [
            {
                "vat_rate": 2.6,
                "account_id": "4200",
                "account_name": "Einkauf Handelsware",
                "confidence": "high",
                "reasoning": "Lebensmittel",
            }
        ],
    }

    accounts_context = "\n".join([
        f"- {acc_id}: {desc}" for acc_id, desc in settings.bexio_accounts.items()
    ])

    lang = settings.vision_prompt_language.lower()
    template = VISION_PROMPT_DE if lang == "de" else VISION_PROMPT_EN

    return template.format(
        schema=json.dumps(example, indent=2),
        accounts=accounts_context,
        default_vat=settings.default_vat_rate,
    )
