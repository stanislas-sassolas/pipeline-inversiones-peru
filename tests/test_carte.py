"""Tests de l'étape 6 (carte), sans réseau : on vérifie les règles et le contenu du HTML produit.

Lancement, depuis le dossier du projet : python -m pytest
"""

import json
from datetime import date

import pandas as pd
import pytest

import carte
import indicateurs as ind
from test_indicateurs import projet

CONTRATA = "ADMINISTRACIÓN INDIRECTA - POR CONTRATA"
INSECABLE = " "


# ---------------------------------------------------------------- taille des cercles

def test_surface_proportionnelle_au_cout_au_dessus_du_minimum():
    # Au-dessus du minimum, un projet 4 fois plus cher a un rayon 2 fois plus grand : surface 4 fois plus grande.
    assert carte.rayon(20e9) == pytest.approx(2 * carte.rayon(5e9))
    assert carte.rayon(30e9) == carte.RAYON_REFERENCE


def test_rayon_minimum():
    assert carte.rayon(100e6) == carte.RAYON_MIN


# ---------------------------------------------------------------- positions

def fichier():
    """Un petit « fichier du MEF » : deux projets localisés dans le district 150101 (Lima), un dans la province 1502."""
    return pd.DataFrame([
        projet("a", 1e6, CONTRATA, UBIGEO="150101", DEPARTAMENTO="LIMA", LATITUD=-12.04, LONGITUD=-77.03),
        projet("b", 1e6, CONTRATA, UBIGEO="150101", DEPARTAMENTO="LIMA", LATITUD=-12.06, LONGITUD=-77.05),
        projet("c", 1e6, CONTRATA, UBIGEO="150201", DEPARTAMENTO="LIMA", LATITUD=-10.75, LONGITUD=-77.76),
    ])


def grands_projets():
    df = pd.DataFrame([
        projet("1", 500e6, CONTRATA, pim=10e6, UBIGEO="150101", DEPARTAMENTO="LIMA", PROVINCIA="LIMA",
               NOMBRE_INVERSION="HOSPITAL & CLINICA <A>", LATITUD=-12.03, LONGITUD=-77.02),
        projet("2", 400e6, CONTRATA, UBIGEO="150101", DEPARTAMENTO="LIMA", PROVINCIA="LIMA",
               LATITUD=float("nan"), LONGITUD=float("nan")),
        projet("3", 300e6, CONTRATA, UBIGEO="150200", DEPARTAMENTO="LIMA", PROVINCIA="BARRANCA",
               LATITUD=float("nan"), LONGITUD=float("nan")),
        projet("4", 200e6, CONTRATA, UBIGEO="990000", DEPARTAMENTO="-MUL.DEP-", PROVINCIA="- TODOS -",
               LATITUD=-12.05, LONGITUD=-77.03),
        projet("5", 150e6, CONTRATA, UBIGEO="150101", DEPARTAMENTO="LIMA", PROVINCIA="LIMA",
               LATITUD=-10.0, LONGITUD=-76.0),
        projet("6", 120e6, CONTRATA, pim=0, UBIGEO="150101", DEPARTAMENTO="LIMA", PROVINCIA="LIMA",
               FUNCION="FONCTION INCONNUE"),
    ])
    return ind.ajouter_secteur_et_modes(df)


def test_regles_de_position():
    positions = carte.positionner(grands_projets(), fichier()).set_index("CODIGO_UNICO")
    assert positions.loc["1", "POSITION"] == carte.DECLAREE
    assert positions.loc["2", "POSITION"] == carte.APPROCHEE_DISTRICT  # médiane des points a et b
    assert (positions.loc["2", "LAT_CARTE"], positions.loc["2", "LON_CARTE"]) == pytest.approx((-12.05, -77.04))
    assert positions.loc["3", "POSITION"] == carte.APPROCHEE_PROVINCE  # province 1502 : point c
    assert pd.isna(positions.loc["4", "POSITION"])  # plusieurs départements : pas de point, même s'il en a un
    assert positions.loc["5", "POSITION"] == carte.APPROCHEE_DISTRICT  # (-10, -76) : coordonnées bouche-trou


def test_lieu_precis():
    assert carte.lieu_precis("150101", "LIMA")
    assert not carte.lieu_precis("990000", "-MUL.DEP-")
    assert not carte.lieu_precis("", "LIMA")


# ---------------------------------------------------------------- page produite

def page_de_test(tmp_path):
    la_carte, grands = carte.dessiner(grands_projets(), fichier(), {}, date(2026, 11, 25), 2026)
    chemin = tmp_path / "carte.html"
    carte.ecrire(la_carte, chemin)
    return chemin.read_text(encoding="utf-8").replace(INSECABLE, " "), grands


def test_legende_compte_les_absents(tmp_path):
    texte, grands = page_de_test(tmp_path)
    assert "Absents de la carte : 1 projets" in texte  # le projet 4, multi-départements
    assert "non affilié à la DG Trésor" in texte


def test_cercle_creux_et_pointille(tmp_path):
    texte, _ = page_de_test(tmp_path)
    assert '"fillOpacity": 0.0' in texte  # projet 6 : ni budget ni dépense
    assert '"dashArray": "4 3"' in texte  # positions approchées


def test_secteur_non_classe_a_sa_case(tmp_path):
    texte, _ = page_de_test(tmp_path)
    # folium écrit les noms des cases dans le JavaScript avec les accents encodés, comme json.dumps.
    assert json.dumps("Non classé (1)")[1:-1] in texte


def test_deux_generations_identiques(tmp_path):
    premiere, _ = page_de_test(tmp_path)
    seconde, _ = page_de_test(tmp_path)
    assert premiere == seconde


def test_bulle_echappe_le_html_et_donne_le_lieu():
    grands = carte.positionner(grands_projets(), fichier())
    texte = carte.bulle(grands.iloc[0], {}, 2026)
    assert "&amp;" in texte and "<A>" not in texte
    assert "code MEF 1" in texte and "Lima / Lima" in texte


@pytest.mark.parametrize("soles, attendu", [(350e6, "350 M S/"), (1.7e9, "1,7 Md S/")])
def test_montant(soles, attendu):
    assert carte.montant(soles).replace(INSECABLE, " ") == attendu
