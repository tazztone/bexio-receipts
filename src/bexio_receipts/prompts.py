"""System prompts for Vision-Language Models."""

import json

import structlog

from .config import Settings
from .models import AccountAssignment, RawVatRow, VisionExtraction

logger = structlog.get_logger(__name__)

VISION_PROMPT_DE = (
    "Schweizer Buchhalter. Extrahiere Belegdaten als JSON.\n\n"
    "KONTEN:\n{accounts}\n\n"
    "MWST-Standard: {default_vat}%\n\n"
    "REGELN:\n"
    "1. total_incl_vat: nur aus 'Ihr Betrag' / 'Total Rechnung inkl. MWST' — NICHT berechnen.\n"
    "2. vat_amount: nur aus 'Total Rechnung / MWST'-Spalte — NICHT berechnen.\n"
    "3. vat_rows: EINE Zeile pro MWST-Satz (2.6%, 8.1% etc.).\n"
    "4. account_assignments: EINE Zuweisung pro vat_row.\n"
    "5. EUR-Umrechnungszeilen ignorieren.\n"
    "6. payment_method aus 'Zahlungsart'-Feld.\n\n"
    "BEISPIEL:\n{schema}\n"
)

VISION_PROMPT_EN = (
    "Swiss bookkeeper. Extract receipt data as JSON.\n\n"
    "ACCOUNTS:\n{accounts}\n\n"
    "VAT default: {default_vat}%\n\n"
    "RULES:\n"
    "1. total_incl_vat: read only from 'Ihr Betrag' / 'Total inkl. MWST' — DO NOT compute.\n"
    "2. vat_amount: read only from 'Total Rechnung / MWST' column — DO NOT compute.\n"
    "3. vat_rows: ONE row per VAT rate found (2.6%, 8.1% etc.).\n"
    "4. account_assignments: ONE entry per vat_row.\n"
    "5. Ignore EUR conversion lines.\n"
    "6. payment_method from 'Zahlungsart' field.\n\n"
    "EXAMPLE:\n{schema}\n"
)

VISION_PROMPT_FR = (
    "Comptable suisse. Extraire les données du reçu en JSON.\n\n"
    "COMPTES:\n{accounts}\n\n"
    "TVA par défaut: {default_vat}%\n\n"
    "RÈGLES:\n"
    "1. total_incl_vat: lire uniquement depuis 'Ihr Betrag' / 'Total TTC' — NE PAS calculer.\n"
    "2. vat_amount: lire uniquement depuis la colonne 'TVA' ligne 'Total' — NE PAS calculer.\n"
    "3. vat_rows: UNE ligne par taux TVA (2.6%, 8.1% etc.).\n"
    "4. account_assignments: UNE entrée par vat_row.\n"
    "5. Ignorer les lignes de conversion EUR.\n"
    "6. payment_method depuis le champ 'Zahlungsart'.\n\n"
    "EXEMPLE:\n{schema}\n"
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
