"""Tests de l'étape 3 (ce qui a bougé), sur deux petites archives inventées.

Lancement, depuis le dossier du projet : python -m pytest
"""

from datetime import date

import pandas as pd
import pytest

import changements as ch
from test_indicateurs import projet

CONTRATA = "ADMINISTRACIÓN INDIRECTA - POR CONTRATA"
DIRECTA = "ADMINISTRACIÓN DIRECTA"


def comparer(avant, apres):
    return ch.comparer(ch.preparer(pd.DataFrame(avant)), ch.preparer(pd.DataFrame(apres)))


def signaux_de(avant, apres):
    """Compare deux listes de projets et renvoie {(code, signal): ligne}."""
    signaux, _ = comparer(avant, apres)
    return {(ligne.CODIGO_UNICO, ligne.signal): ligne for ligne in signaux.itertuples()}


# ---------------------------------------------------------------- choix des archives

def test_choix_par_defaut_au_moins_7_jours():
    dates = [date(2026, 11, d) for d in (13, 14, 19, 20, 23)]
    assert ch.choisir_dates(dates) == (date(2026, 11, 14), date(2026, 11, 23))


def test_choix_sans_archive_assez_vieille_prend_la_plus_ancienne():
    dates = [date(2026, 11, d) for d in (19, 20, 23)]
    assert ch.choisir_dates(dates) == (date(2026, 11, 19), date(2026, 11, 23))


def test_choix_d_une_seule_date():
    dates = [date(2026, 11, d) for d in (13, 14, 23)]
    assert ch.choisir_dates(dates, date(2026, 11, 13)) == (date(2026, 11, 13), date(2026, 11, 23))


@pytest.mark.parametrize("dates", [[], [date(2026, 11, 13)]])
def test_moins_de_deux_archives_refuse(dates):
    with pytest.raises(ValueError):
        ch.choisir_dates(dates)


def test_dates_dans_le_mauvais_ordre_refusees():
    with pytest.raises(ValueError):
        ch.choisir_dates([date(2026, 11, 13), date(2026, 11, 23)], date(2026, 11, 23), date(2026, 11, 13))


# ---------------------------------------------------------------- ruptures de format

def test_rupture_de_format_reperee():
    avant = pd.DataFrame({"A": [1.0, 2.0, 0.0, 4.0], "B": ["x", "y", "z", ""], "C": [1.0, 1.0, 1.0, 1.0]})
    apres = pd.DataFrame({"A": [1.0, 2.0, 0.0, 4.0], "B": ["", "", "", ""], "C": [0.0, 0.0, 0.0, 0.0]})
    ruptures = ch.ruptures_de_format(avant, apres).set_index("colonne")
    assert list(ruptures.index) == ["B", "C"]
    assert ruptures.loc["B", "ecart_points"] == -75.0


# ---------------------------------------------------------------- entrées et sorties du périmètre

def test_nouveau_et_sorti():
    s = signaux_de(avant=[projet("1", 200e6, CONTRATA), projet("2", 300e6, CONTRATA)],
                   apres=[projet("1", 200e6, CONTRATA), projet("3", 400e6, CONTRATA)])
    assert ("3", ch.NOUVEAU) in s
    assert ("2", ch.SORTI) in s
    assert len(s) == 2  # le projet 1 n'a pas bougé


def test_profil_de_sortie():
    s = signaux_de(avant=[projet("1", 200e6, CONTRATA),
                          projet("2", 200e6, CONTRATA, TIENE_F9="SI", ETAPA_F9="Cierre", DEVEN_ACUMUL_ANIO_ANT=1e8),
                          projet("3", 200e6, CONTRATA, DEVEN_ACUMUL_ANIO_ANT=1e8)],
                   apres=[projet("8", 5e6, CONTRATA)])  # un petit projet, hors périmètre
    assert s[("1", ch.SORTI)].remarque.startswith("sans budget ni dépense")
    assert s[("2", ch.SORTI)].remarque.startswith("clôture")
    assert s[("3", ch.SORTI)].remarque == "motif inconnu"


def test_seuil_franchi_dans_les_deux_sens():
    s = signaux_de(avant=[projet("1", 90e6, CONTRATA), projet("2", 110e6, CONTRATA)],
                   apres=[projet("1", 105e6, CONTRATA), projet("2", 95e6, CONTRATA)])
    assert ("1", ch.AU_DESSUS) in s
    assert ("2", ch.EN_DESSOUS) in s


def test_seuil_frole_non_signale_mais_compte():
    s, bilan = comparer(avant=[projet("1", 99e6, CONTRATA)], apres=[projet("1", 101e6, CONTRATA)])
    assert s.empty
    assert bilan["franchissements du seuil non signalés (coût qui bouge de moins de 5 %)"] == 1


def test_controle_concomitant_ajoute_au_cout():
    """Avant le 20/11/2026, le MEF donnait le contrôle à part ; ensuite, il l'inclut dans le coût.
    Un projet à 99 M + 1,5 M de contrôle qui passe à 100,5 M sans contrôle n'a pas bougé."""
    s = signaux_de(avant=[projet("1", 99e6, CONTRATA, CTRL_CONCURR=1.5e6)],
                   apres=[projet("1", 100.5e6, CONTRATA, CTRL_CONCURR=0.0)])
    assert s == {}


def test_petits_projets_ignores():
    s = signaux_de(avant=[projet("1", 5e6, CONTRATA, SITUACION="APROBADO")],
                   apres=[projet("1", 5e6, CONTRATA, SITUACION="VIABLE")])
    assert s == {}


def test_projet_sans_code_ignore():
    s = signaux_de(avant=[projet("", 500e6, CONTRATA)], apres=[projet("", 600e6, CONTRATA)])
    assert s == {}


# ---------------------------------------------------------------- signaux sur les projets suivis

def test_situation_et_expediente():
    s = signaux_de(avant=[projet("1", 200e6, CONTRATA, SITUACION="EN FORMULACION", EXPEDIENTE_TECNICO="NO")],
                   apres=[projet("1", 200e6, CONTRATA, SITUACION="VIABLE", EXPEDIENTE_TECNICO="SI")])
    assert s[("1", ch.SITUATION)].apres == "VIABLE"
    assert s[("1", ch.EXPEDIENTE)].avant == "NO"


def test_texte_vide_des_deux_cotes_n_est_pas_un_changement():
    s = signaux_de(avant=[projet("1", 200e6, CONTRATA, SITUACION=None)],
                   apres=[projet("1", 200e6, CONTRATA, SITUACION=None)])
    assert s == {}


def test_avancement_seuil_de_10_points():
    s = signaux_de(
        avant=[projet("1", 200e6, CONTRATA, AVANCE_FISICO=50.0), projet("2", 200e6, CONTRATA, AVANCE_FISICO=50.0),
               projet("3", 200e6, CONTRATA, AVANCE_FISICO=float("nan")),
               projet("4", 200e6, CONTRATA, AVANCE_FISICO=50.0)],
        apres=[projet("1", 200e6, CONTRATA, AVANCE_FISICO=60.0), projet("2", 200e6, CONTRATA, AVANCE_FISICO=59.9),
               projet("3", 200e6, CONTRATA, AVANCE_FISICO=80.0),
               projet("4", 200e6, CONTRATA, AVANCE_FISICO=250.0)])  # valeur impossible, vidée
    resultat = tuple((code, ch.AVANCEMENT) in s for code in "1234")
    assert resultat == (True, False, False, False)
    assert s[("1", ch.AVANCEMENT)].ecart_points == pytest.approx(10.0)


def test_pim_seuil_et_transfert_dans_la_meme_unite():
    s = signaux_de(
        avant=[projet("1", 200e6, CONTRATA, pim=10e6), projet("2", 200e6, CONTRATA, pim=30e6),
               projet("3", 200e6, CONTRATA, pim=10e6)],
        apres=[projet("1", 200e6, CONTRATA, pim=17e6), projet("2", 200e6, CONTRATA, pim=23e6),
               projet("3", 200e6, CONTRATA, pim=14.9e6)])  # +4,9 M : sous le seuil de 5 M
    assert s[("1", ch.PIM_HAUSSE)].ecart_M_soles == pytest.approx(7.0)
    assert s[("2", ch.PIM_BAISSE)].ecart_M_soles == pytest.approx(-7.0)
    assert ("3", ch.PIM_HAUSSE) not in s
    assert "même unité exécutrice" in s[("1", ch.PIM_HAUSSE)].remarque


def test_transfert_cherche_dans_tout_le_fichier_et_unite_differente():
    # La contrepartie (code 9) est un petit projet, hors du périmètre des grands projets.
    s = signaux_de(
        avant=[projet("1", 200e6, CONTRATA, pim=10e6), projet("9", 5e6, CONTRATA, pim=8e6, SEC_EJEC="2")],
        apres=[projet("1", 200e6, CONTRATA, pim=16e6), projet("9", 5e6, CONTRATA, pim=2e6, SEC_EJEC="2")])
    assert s[("1", ch.PIM_HAUSSE)].remarque.startswith("9 : ")
    assert "autre unité exécutrice" in s[("1", ch.PIM_HAUSSE)].remarque


def test_annees_budgetaires_differentes_pas_de_pim():
    s, bilan = comparer(avant=[projet("1", 200e6, CONTRATA, pim=80e6, ANIO_PROCESO="2026")],
                        apres=[projet("1", 200e6, CONTRATA, pim=0, ANIO_PROCESO="2027")])
    assert s.empty
    assert "non comparable" in bilan["variation nette du PIM de l'année (M soles, projets suivis)"]


def test_cout_variation_relative():
    s = signaux_de(avant=[projet("1", 200e6, CONTRATA), projet("2", 200e6, CONTRATA)],
                   apres=[projet("1", 220e6, CONTRATA), projet("2", 219e6, CONTRATA)])
    assert ((("1", ch.COUT_HAUSSE) in s), (("2", ch.COUT_HAUSSE) in s)) == (True, False)
    assert s[("1", ch.COUT_HAUSSE)].ecart_M_soles == pytest.approx(20.0)


def test_cout_nul_avant_pas_de_variation_infinie():
    s = signaux_de(avant=[projet("1", 0.0, CONTRATA)], apres=[projet("1", 150e6, CONTRATA)])
    assert set(signal for _, signal in s) == {ch.AU_DESSUS}  # pas de « coût +10 % » avec une variation infinie


def test_modes_dans_un_autre_ordre_ne_comptent_pas():
    s = signaux_de(avant=[projet("1", 200e6, f"{CONTRATA},{DIRECTA}")],
                   apres=[projet("1", 200e6, f"{DIRECTA},{CONTRATA}")])
    assert s == {}


def test_mode_ajoute_compte():
    s = signaux_de(avant=[projet("1", 200e6, CONTRATA)], apres=[projet("1", 200e6, f"{DIRECTA},{CONTRATA}")])
    assert s[("1", ch.MODES)].apres == "Marché public (por contrata) + Régie (administration directe)"


def test_plusieurs_signaux_pour_un_meme_projet():
    s = signaux_de(avant=[projet("1", 90e6, CONTRATA)], apres=[projet("1", 150e6, CONTRATA)])
    assert {signal for _, signal in s} == {ch.AU_DESSUS, ch.COUT_HAUSSE}


def test_bilan():
    _, bilan = comparer(avant=[projet("1", 200e6, CONTRATA, pim=10e6, dev=2e6), projet("2", 300e6, CONTRATA)],
                        apres=[projet("1", 200e6, CONTRATA, pim=10e6, dev=5e6)])
    assert bilan["variation nette du devengado de l'année (M soles, projets suivis)"] == pytest.approx(3.0)
    assert bilan["grands projets (100 M ou plus) dans l'ancienne archive"] == 2
    assert bilan["grands projets dans la récente"] == 1
    assert bilan["projets distincts avec au moins un signal"] == 1
