"""Tests de la note épurée (note.py) : mise en forme du texte, sans Chrome ni réseau.

Lancement, depuis le dossier du projet : python -m pytest
"""

import re

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
    svg = note.barres_100([("Coût", "727 Md S/", [0.58, 0.40, 0.02])], ["Pas encore en travaux", "En travaux", "En clôture"])
    assert "58 %" in svg and "40 %" in svg
    assert "2 %" not in svg  # segment trop étroit : pas d'étiquette


def test_barres_100_nomme_chaque_categorie_une_seule_fois():
    lignes = [("Coût", "727 Md S/", [0.58, 0.40, 0.02]), ("Budget", "20,9 Md S/", [0.09, 0.91, 0.0])]
    svg = note.barres_100(lignes, ["Pas encore en travaux", "En travaux", "En clôture"])
    assert svg.count("Pas encore en travaux") == 1 and svg.count(">En travaux<") == 1
    assert "9 %" in svg  # la part mise en avant est toujours écrite, même petite


def test_graphiques_suivent_la_palette():
    lignes = [("Coût", "727 Md S/", [0.58, 0.40, 0.02])]
    for nom, pal in note.PALETTES.items():
        svg = note.barres_100(lignes, ["a", "b", "c"], palette=nom)
        for cle in ("avant", "secondaire", "marginale", "texte_doux", "encre", "fond"):
            assert pal[cle] in svg, (nom, cle)
    autre = note.barres_100(lignes, ["a", "b", "c"], palette={"avant": "#123456"})
    assert "#123456" in autre and note.PALETTE["secondaire"] in autre  # dict partiel complété par la palette par défaut
    nomme = note.palette_de({"nom": "terracotta", "avant": "#123456"})
    assert nomme["avant"] == "#123456" and nomme["encre"] == note.PALETTES["terracotta"]["encre"]  # complété par sa palette


def test_palette_par_nom_sans_tenir_compte_de_la_casse():
    assert note.palette_de("Sarcelle") == note.PALETTES["sarcelle"]
    with pytest.raises(ValueError, match="bleu, sarcelle, terracotta"):
        note.palette_de("vert")


def test_barres_100_segment_invisible_et_part_hors_segment():
    # 0,16 % ferait 0,2 mm : pas de liseré gris à part, la largeur est rendue au segment précédent.
    svg = note.barres_100([("Budget", "20,9 Md S/", [0.093, 0.9054, 0.0016])], ["a", "b", "c"])
    assert f'fill="{note.PALETTE["marginale"]}"' not in svg
    # Une part trop petite pour tenir dans son segment s'écrit juste après, en encre (lisible sur la teinte claire).
    svg = note.barres_100([("Budget", "20,9 Md S/", [0.01, 0.97, 0.02])], ["a", "b", "c"])
    texte = re.search(r'<text[^>]*fill="([^"]+)"[^>]*>1\s%</text>', svg)
    assert texte and texte.group(1) == note.PALETTE["encre"]


def v_synthetique():
    """Un petit jeu de données pour le graphique 2 : la vague culmine en 2024, mais la colonne la plus haute est 2013."""
    annees = list(range(2010, 2027))
    pre = {2016: 5, 2020: 20, 2023: 30, 2024: 60, 2025: 50, 2026: 40}
    autres = {2013: 90, 2016: 20, 2020: 30, 2023: 10, 2024: 10, 2025: 5, 2026: 2}
    par_an = pd.DataFrame({"autres": [autres.get(a, 1) for a in annees], "pre": [pre.get(a, 0) for a in annees]},
                          index=annees, dtype=float)
    return {"par_an": par_an, "n_par_an": pd.Series(10, index=annees), "annee": 2026,
            "annee_dernier": pd.Timestamp(2026, 11, 24)}


def test_graphique_2_suit_la_palette_et_annote_le_pic_de_la_vague():
    v = v_synthetique()
    assert note.annee_pic(v) == 2024  # le pic de la vague, pas celui du total (2013)
    for nom, pal in note.PALETTES.items():
        svg = note.colonnes_par_annee(v, palette=nom)
        for cle in ("avant", "secondaire", "filet", "texte_doux", "encre", "fond"):
            assert pal[cle] in svg, (nom, cle)
        assert re.search(r">2024\s:", svg) and not re.search(r">2013\s:", svg)


def test_feuille_de_style_sans_couleur_en_dur():
    css = (note.DOSSIER / "style.css").read_text(encoding="utf-8")
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)  # les commentaires ne comptent pas
    fonctions = re.findall(r"#[0-9a-fA-F]{3,8}\b|\b(?:rgba?|hsla?|hwb|lab|lch|oklab|oklch|color-mix)\s*\(", css)
    nommees = re.findall(r"(?:color|background|border[a-z-]*|fill|stroke|outline)\s*:[^;}]*?\b(white|black|gr[ae]y|silver|"
                         r"red|blue|green|navy|teal|beige|ivory|whitesmoke)\b", css)
    assert not fonctions and not nommees, (fonctions, nommees)
    variables = note.variables_css("sarcelle")
    for cle in ("avant", "secondaire", "marginale", "texte_doux", "filet", "encre", "fond"):
        assert f"--{cle.replace('_', '-')}: {note.PALETTES['sarcelle'][cle]};" in variables
        if cle not in ("secondaire", "marginale"):  # ces deux-là ne servent qu'aux graphiques
            assert f"var(--{cle.replace('_', '-')})" in css
