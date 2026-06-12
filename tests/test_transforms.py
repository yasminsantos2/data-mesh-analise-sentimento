"""Unit tests for the Glue business rules (no Spark required).

Validates the sentiment rule with 10 manual samples and the age_band mapping
across all four categories plus edge cases.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "glue_jobs"))

from transforms import age_band, sentiment, to_snake_case  # noqa: E402


# 10 amostras manuais cobrindo todos os ramos da regra de sentimento.
SENTIMENT_SAMPLES = [
    # (rating, recommended_ind, esperado)
    (5, 1, "Positivo"),
    (4, 1, "Positivo"),
    (5, 0, "Negativo"),   # rating alto mas nao recomendado -> demais
    (4, 0, "Negativo"),   # rating alto mas nao recomendado -> demais
    (3, 1, "Neutro"),
    (3, 0, "Neutro"),
    (2, 1, "Negativo"),
    (1, 0, "Negativo"),
    (2, 0, "Negativo"),
    (1, 1, "Negativo"),
]


@pytest.mark.parametrize("rating,rec,expected", SENTIMENT_SAMPLES)
def test_sentiment_rule(rating, rec, expected):
    assert sentiment(rating, rec) == expected


def test_sentiment_handles_strings():
    assert sentiment("5", "1") == "Positivo"
    assert sentiment("3", "0") == "Neutro"
    assert sentiment(None, None) == "Negativo"


AGE_BAND_SAMPLES = [
    (18, "Jovem"),
    (25, "Jovem"),
    (29, "Jovem"),
    (30, "Adulto"),
    (44, "Adulto"),
    (45, "Madura"),
    (59, "Madura"),
    (60, "Sênior"),
    (85, "Sênior"),
    (17, None),    # abaixo da faixa
    (None, None),  # nulo
    ("abc", None), # nao parseavel
]


@pytest.mark.parametrize("age,expected", AGE_BAND_SAMPLES)
def test_age_band(age, expected):
    assert age_band(age) == expected


def test_age_band_four_categories():
    bands = {age_band(a) for a in (20, 35, 50, 70)}
    assert bands == {"Jovem", "Adulto", "Madura", "Sênior"}


@pytest.mark.parametrize("raw,expected", [
    ("Review Text", "review_text"),
    ("Recommended IND", "recommended_ind"),
    ("Department Name", "department_name"),
    ("Clothing ID", "clothing_id"),
    ("  Age  ", "age"),
])
def test_to_snake_case(raw, expected):
    assert to_snake_case(raw) == expected
