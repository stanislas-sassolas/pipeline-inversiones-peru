"""Tests de l'étape 5 (fiche de deux pages) : mise en forme et règles des encadrés, sans Chrome ni réseau.

Lancement, depuis le dossier du projet : python -m pytest
"""

from datetime import date

import pandas as pd
import pytest

import fiche
from test_indicateurs import projet


# ---------------------------------------------------------------- mise en forme

def test_nombres_a_la_francaise():
    assert fiche.fr(1385, 0) == "1 385"
    assert fiche.fr(724.66) == "724,7"


@pytest.mark.parametrize("soles, attendu", [(1_765_358_059, "1 765"), (466_628, "0,5"), (0, "0")])
def test_montant_en_millions(soles, attendu):
    assert fiche.montant_M(soles) == attendu


def test_signe_calcule():
    assert fiche.signe(99.9) == "+100"
    assert fiche.signe(-14.0) == "−14"


@pytest.mark.parametrize("n, attendu", [(0, "0 projet"), (1, "1 projet"), (2, "2 projets")])
def test_accord_singulier_pluriel(n, attendu):
    assert fiche.compte(n, "projet", "projets") == attendu


def test_typographie_francaise_seulement_dans_le_corps():
    page = '<head><style>a { b: c; }</style></head><body><p>5 projets : 12 % « ok »</p></body>'
    resultat = fiche.typographie(page)
    assert "a { b: c; }" in resultat  # le CSS de l'en-tête n'est pas touché
    assert "5 projets : 12 % « ok »" in resultat


def test_echappement_html():
    assert fiche.e("A & B <C>") == "A &amp; B &lt;C&gt;"


def test_nom_court_ecrit_a_la_main():
    assert fiche.nom_court("2300242", "CREACION DE LA LINEA 3...", {"2300242": "Ligne 3 du métro de Lima"}) == \
        "Ligne 3 du métro de Lima"


def test_nom_court_automatique_coupe_avant_le_lieu():
    nom = "MEJORAMIENTO DEL SERVICIO DE SALUD DEL HOSPITAL REGIONAL, DISTRITO DE PIURA, PROVINCIA DE PIURA"
    assert fiche.nom_court("1", nom, {}) == "Mejoramiento del servicio de salud del hospital regional"


# ---------------------------------------------------------------- règles des tableaux et encadrés

def test_stade_et_colonne_et():
    viable = pd.Series({"SITUACION": "VIABLE", "EXPEDIENTE_TECNICO": "NO"})
    approuve = pd.Series({"SITUACION": "APROBADO", "EXPEDIENTE_TECNICO": "SI"})
    assert fiche.stade(viable) == "viable, ET non"
    assert (fiche.et(viable), fiche.et(approuve)) == ("non", "approuvé, ET oui")


def test_budget_ou_depense():
    assert fiche.budget_ou_depense(pd.Series(projet("1", 200e6, "", pim=0))) == "non"
    assert fiche.budget_ou_depense(pd.Series(projet("1", 200e6, "", pim=10))) == "oui"
    assert fiche.budget_ou_depense(pd.Series(projet("1", 200e6, "", DEVEN_ACUMUL_ANIO_ANT=5.0))) == "oui"


def test_projets_ferroviaires_sans_avenue_ni_voirie():
    grands = pd.DataFrame([
        projet("1", 30e9, "", DES_TIPOLOGIA="SISTEMA FERROVIARIO INTERURBANO", NOMBRE_INVERSION="TREN"),
        projet("2", 14e9, "", DES_TIPOLOGIA="SISTEMAS INTEGRADOS DE TRANSPORTE",
               NOMBRE_INVERSION="AMPLIACION EN LINEA 1 DEL METRO DE LIMA"),
        projet("3", 1e8, "", DES_TIPOLOGIA="", NOMBRE_INVERSION="CORREDOR VIAL AV. FERROCARRIL, HUANCAYO"),
        projet("4", 3e8, "", DES_TIPOLOGIA="VIAS URBANAS", NOMBRE_INVERSION="INTERCONEXION CON LA LINEA 1 DEL METRO DE LIMA"),
    ])
    assert fiche.projets_ferroviaires(grands)["CODIGO_UNICO"].tolist() == ["1", "2"]


def test_lecture_absente_puis_ecrite(monkeypatch, tmp_path):
    fichier = tmp_path / "lecture.txt"
    monkeypatch.setattr(fiche, "LECTURE", fichier)
    texte, vide = fiche.lecture()
    assert vide and "Brouillon" in texte
    fichier.write_text("Premier paragraphe.\n\nSecond & dernier.", encoding="utf-8")
    texte, vide = fiche.lecture()
    assert not vide
    assert texte == '<div class="lecture"><p>Premier paragraphe.</p><p>Second &amp; dernier.</p></div>'


def test_encadre_changements_ne_donne_que_des_totaux():
    signaux = pd.DataFrame({"signal": [fiche.ch.NOUVEAU, fiche.ch.SORTI, fiche.ch.PIM_BAISSE],
                            "CODIGO_UNICO": ["1", "2", "3"], "NOMBRE_INVERSION": ["A", "B", "PROJET SENSIBLE"]})
    bilan = {"variation nette du PIM de l'année (M soles, projets suivis)": -14.0,
             "variation nette du devengado de l'année (M soles, projets suivis)": 50.0}
    texte = fiche.encadre_changements(signaux, bilan, rupture=False, avant=10, apres=10)
    assert "PROJET SENSIBLE" not in texte  # aucune baisse de budget n'est nommée
    assert "désactivation" not in texte  # le motif d'une sortie n'est pas dans le fichier
    assert "−14 M S/" in texte and "1 entré dans le fichier" in texte


def test_encadre_urgences_separe_les_ioarr_du_mois():
    df = pd.DataFrame([
        projet("1", 1e6, "", pim=10e6, dev=5e6, IND_IOARR_EMERG="SI", FECHA_VIABILIDAD="2026-03-10 00:00:00",
               TIPO_INVERSION="INVERSIONES IOARR", SECTEUR_FICHE=""),
        projet("2", 1e6, "", pim=20e6, dev=0, IND_IOARR_EMERG="SI", FECHA_VIABILIDAD="2026-11-05 00:00:00",
               TIPO_INVERSION="INVERSIONES IOARR", SECTEUR_FICHE=""),
    ])
    texte = fiche.encadre_urgences(df, df.iloc[0:0], date(2026, 11, 25))
    assert "dont 20 M S/ pour des IOARR approuvées en novembre" in texte
    assert "les autres sont exécutées à 50 %" in texte
