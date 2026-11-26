"""Tests de la note épurée (note.py) : mise en forme du texte, sans Chrome ni réseau.

Lancement, depuis le dossier du projet : python -m pytest
"""

import pandas as pd
import pytest

import note


@pytest.mark.parametrize("n, majuscule, attendu", [(5, False, "cinq"), (7, True, "Sept"), (11, False, "onze"), (1389, False, "1 389")])
def test_petits_nombres_en_lettres(n, majuscule, attendu):
    assert note.en_lettres(n, majuscule) == attendu


def test_dates_iso_pas_inversees():
    d = note.dates(pd.Series(["2024-07-22 00:00:00", "", None]))
    assert d.iloc[0] == pd.Timestamp(2024, 7, 22) and d.iloc[1:].isna().all()


def test_barres_100_ecrit_les_parts_dans_les_segments_larges():
    svg = note.barres_100([("Coût", "727 Md S/", [0.58, 0.40, 0.02])], [note.BLEU, note.GRIS, note.GRIS_CLAIR],
                          [("pas encore en travaux", note.BLEU), ("en travaux", note.ENCRE_DOUCE), ("", None)])
    assert "58 %" in svg and "40 %" in svg
    assert "2 %" not in svg  # segment trop étroit : pas d'étiquette
