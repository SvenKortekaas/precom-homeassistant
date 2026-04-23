"""Gedeelde hulpfuncties voor de Pre-Com integratie."""
from __future__ import annotations

import re


def _clean_description(s: str) -> str:
    """Verwijder whitespace-ruis uit een capcode-omschrijving."""
    return re.sub(r"\s+", " ", s.strip())
