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
    "WICHTIG: Lies 'total_incl_vat' aus dem Feld 'Ihr Betrag' oder 'Total Rechnung inkl. MWST'. "
    "BERECHNE es NICHT. Lies 'vat_amount' aus der Spalte 'MWST' der Zeile 'Total Rechnung'. "
    "IGNORIERE alle Zeilen mit EUR/Kurs-Umrechnungen.\n"
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
    "IMPORTANT: Read 'total_incl_vat' from the 'Your Amount' or 'Total Invoice incl. VAT' field. "
    "DO NOT compute it. Read 'vat_amount' from the 'VAT' column of the 'Total Invoice' line. "
    "IGNORE all lines with EUR/Exchange rate conversions.\n"
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
    "IMPORTANT: Lisez 'total_incl_vat' dans le champ 'Votre montant' ou 'Total facture TTC'. "
    "NE le calculez PAS. Lisez 'vat_amount' dans la colonne 'TVA' de la ligne 'Total facture'. "
    "IGNOREZ toutes les lignes avec des conversions EUR/Taux de change.\n"
)

_TEMPLATES: dict[str, str] = {
    "de": VISION_PROMPT_DE,
    "en": VISION_PROMPT_EN,
    "fr": VISION_PROMPT_FR,
}

# Type-safe example: if VisionExtraction changes, this adapts or breaks at import time.
_PROMPT_EXAMPLE = VisionExtraction(
    merchant_name="Prodega Markt",
    transaction_date="2026-01-31",
    total_incl_vat=214.20,
    currency="CHF",
    payment_method="Bar",
    subtotal_excl_vat=207.15,
    vat_rate_pct=8.1,
    vat_amount=7.06,
    vat_rows=[
        RawVatRow(rate=2.6, net_amount=176.70, vat_amount=4.59, total_amount=181.29),
        RawVatRow(rate=8.1, net_amount=30.45, vat_amount=2.47, total_amount=32.92),
    ],
    account_assignments=[
        AccountAssignment(
            vat_rate=2.6,
            account_id="4200",
            account_name="Einkauf Handelsware",
            confidence="high",
            reasoning="Lebensmittel 2.6%",
        ),
        AccountAssignment(
            vat_rate=8.1,
            account_id="4201",
            account_name="Einkauf Handelsware Non-Food",
            confidence="high",
            reasoning="Nearfood/Non-food 8.1%",
        ),
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
