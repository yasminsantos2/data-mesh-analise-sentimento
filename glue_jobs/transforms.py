"""Pure-Python business rules shared by the Glue jobs.

Kept free of PySpark imports so the rules can be unit-tested without a Spark
runtime. The Glue scripts wrap these functions as Spark UDFs.
"""
from __future__ import annotations

import re
from typing import Optional


def to_snake_case(name: str) -> str:
    """Normalize an arbitrary column header to snake_case.

    "Review Text" -> "review_text", "Recommended IND" -> "recommended_ind".
    """
    s = name.strip().lower()
    s = re.sub(r"[^0-9a-z]+", "_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    return s


def _to_int(value) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def age_band(age) -> Optional[str]:
    """Map an age to its band.

    18-29 -> Jovem, 30-44 -> Adulto, 45-59 -> Madura, 60+ -> Sênior.
    Ages below 18 or unparseable return None (excluded from aggregation).
    """
    a = _to_int(age)
    if a is None:
        return None
    if 18 <= a <= 29:
        return "Jovem"
    if 30 <= a <= 44:
        return "Adulto"
    if 45 <= a <= 59:
        return "Madura"
    if a >= 60:
        return "Sênior"
    return None


def sentiment(rating, recommended_ind) -> str:
    """Classify sentiment.

    rating >= 4 AND recommended_ind == 1 -> Positivo
    rating == 3                          -> Neutro
    everything else                      -> Negativo
    """
    r = _to_int(rating)
    rec = _to_int(recommended_ind)
    if r is not None and r >= 4 and rec == 1:
        return "Positivo"
    if r == 3:
        return "Neutro"
    return "Negativo"
