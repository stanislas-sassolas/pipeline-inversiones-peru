"""Tests de l'étape 5 (fiche de deux pages) : mise en forme et règles des encadrés, sans Chrome ni réseau.

Lancement, depuis le dossier du projet : python -m pytest
"""

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

def test_stade_d_apres_les_phases_du_mef():
    base = {"ETAPA_F8": "", "ETAPA_F9": "", "AVANCE_FISICO": float("nan")}
    assert fiche.stade(pd.Series(base)) == fiche.AVANT
    assert fiche.stade(pd.Series(base | {"ETAPA_F8": "Expediente técnico (B)"})) == fiche.ETUDES
    assert fiche.stade(pd.Series(base | {"ETAPA_F8": "Aprobación de consistencia (A)"})) == fiche.ETUDES
    assert fiche.stade(pd.Series(base | {"ETAPA_F8": "Ejecución física (C)"})) == fiche.TRAVAUX
    # Un rapport de fin des travaux passe avant la phase d'exécution déclarée...
    assert fiche.stade(pd.Series(base | {"ETAPA_F8": "Ejecución física (C)",
                                          "ETAPA_F9": "Pendiente de liquidación"})) == fiche.CLOTURE
    # ... mais pas s'il dit que les travaux ne sont pas finis.
    assert fiche.stade(pd.Series(base | {"ETAPA_F8": "Ejecución física (C)",
                                          "ETAPA_F9": "Pendiente de Culminación de ejecución de Metas fisicas"})) == fiche.TRAVAUX


def test_colonne_des_phases_vide_arrete_le_script():
    # Cas réel : fichiers des 20 et 23/11/2026, ETAPA_F8 vide partout.
    vide = pd.DataFrame({"ETAPA_F8": ["", "", "Ejecución física (C)"]})
    with pytest.raises(SystemExit):
        fiche.verifier_phases(vide)
    fiche.verifier_phases(pd.DataFrame({"ETAPA_F8": ["", "Ejecución física (C)", "Expediente técnico (B)"]}))


def test_tous_les_modes_publics_ont_une_explication():
    for mode in fiche.ind.ORDRE_MODES_PUBLICS:
        assert mode in fiche.MODES


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
    assert texte == '<p>Premier paragraphe.</p><p>Second &amp; dernier.</p>'


# ---------------------------------------------------------------- note niveau « cabinet » : chiffres, titres, contrôles

@pytest.mark.parametrize("part, attendu", [(0.581, "58\u00a0%"), (0.002, "0,2\u00a0%"), (0.0, "0\u00a0%"), (1.0, "100\u00a0%")])
def test_pourcentage_jamais_zero_pour_une_petite_part(part, attendu):
    assert fiche.pc(part) == attendu


@pytest.mark.parametrize("soles, attendu", [(726.5e9, "727"), (20.85e9, "20,9"), (99.96e9, "100,0")])
def test_milliards_entiers_au_dela_de_100(soles, attendu):
    assert fiche.md(soles) == attendu


def test_dates_au_format_iso_pas_inversees():
    # 2027-03-05 doit rester le 5 mars, pas le 3 mai (piège de dayfirst=True).
    g = pd.DataFrame({"FEC_INI_EJEC_FISICA": ["2027-03-05 00:00:00", "", None]})
    d = fiche.dates_debut(g)
    assert d.iloc[0] == pd.Timestamp(2027, 3, 5) and d.iloc[1:].isna().all()


def petits_grands_projets():
    """Six projets inventés, un par cas utile : stades, modes, niveaux, dates."""
    lignes = [
        projet("1", 30e9, "", MODE_PUBLIC="Marché public (por contrata)", ETAPA_F8="Aprobación de consistencia (A)",
               FEC_INI_EJEC_FISICA="2027-06-01 00:00:00", SECTEUR_FICHE="Transports et télécoms", NIVEL="GN"),
        projet("2", 20e9, "", MODE_PUBLIC="APP", ETAPA_F8="", FEC_INI_EJEC_FISICA="", SECTEUR_FICHE="Transports et télécoms",
               NIVEL="GN"),
        projet("3", 10e9, "", pim=2e9, dev=1e9, MODE_PUBLIC="APP", ETAPA_F8="Ejecución física (C)",
               FEC_INI_EJEC_FISICA="2020-01-01 00:00:00", SECTEUR_FICHE="Eau et assainissement", NIVEL="GR"),
        projet("4", 5e9, "", pim=1e9, dev=5e8, MODE_PUBLIC="Marché public (por contrata)", ETAPA_F8="Ejecución física (C)",
               FEC_INI_EJEC_FISICA="2021-01-01 00:00:00", SECTEUR_FICHE="Santé", NIVEL="GL"),
        projet("5", 1e9, "", MODE_PUBLIC="Marché public (por contrata)", ETAPA_F8="Expediente técnico (B)",
               FEC_INI_EJEC_FISICA="2028-02-01 00:00:00", SECTEUR_FICHE="Santé", NIVEL="GR"),
        projet("6", 2e8, "", MODE_PUBLIC="Régie (administration directe)", ETAPA_F8="Ejecución física (C)",
               ETAPA_F9="Pendiente de liquidación", FEC_INI_EJEC_FISICA="2019-01-01 00:00:00",
               SECTEUR_FICHE="Santé", NIVEL="GL"),
    ]
    return fiche.preparer(pd.DataFrame(lignes))


def test_stades_et_parts_s_additionnent():
    g = petits_grands_projets()
    s = fiche.chiffres_par_stade(g)
    assert s["n"].tolist() == [1, 2, 2, 1]
    assert s["pc"].sum() == pytest.approx(1) and s["pp"].sum() == pytest.approx(1)
    assert g["PRE"].tolist() == [True, True, False, False, True, False]


def test_calendrier_des_projets_en_etudes():
    from datetime import date
    g = petits_grands_projets()
    t, etudes, fenetre, passees = fiche.calendrier(g, date(2026, 11, 25))
    assert len(etudes) == 2 and t["n"].sum() == 2
    assert sorted(fenetre["CODIGO_UNICO"]) == ["1", "5"]  # début déclaré en 2027 et 2028
    assert passees.empty


def test_titres_recalcules_a_partir_des_donnees():
    from datetime import date
    g = petits_grands_projets()
    _, etudes, fenetre, _ = fiche.calendrier(g, date(2026, 11, 25))
    v = {"annee": 2026, "g": g, "stades": fiche.chiffres_par_stade(g), "secteurs": fiche.croisement(g, "SECTEUR_FICHE"),
         "modes": fiche.croisement(g, "MODE_PUBLIC"), "niveaux": fiche.niveaux(g), "taille": fiche.classes_de_taille(g),
         "n_etudes": len(etudes), "fenetre": fenetre, "t1": g[g["PRE"]].head(10), "t2": g[g["STADE"] == fiche.TRAVAUX]}
    t = fiche.titres(v)
    total = g["COSTO_ACTUALIZADO"].sum()
    assert f"{fiche.md(total)} Md S/" in t["h1"]
    assert t["g2"].startswith("Transports et télécoms : ")
    assert "2027 ou 2028" in t["g4"] and "2 projets en études détaillées" in t["g4"]
    assert "dont 1 en PPP" in t["t1"]
    assert t["g3"].startswith("Marché public : ") and "PPP" in t["g3"]


def test_controle_refuse_les_noms_bruts_et_les_jugements():
    page = "<html><head></head><body><p>Région : DEPARTAMENTO DE LIMA</p></body></html>"
    with pytest.raises(SystemExit, match="nom brut"):
        fiche.controler(page, {})
    with pytest.raises(SystemExit, match="jugement"):
        fiche.controler("<head></head><body>ok</body>", {"g1": "Un retard inquiétant"})
    fiche.controler("<head></head><body>Pipeline de données, Pérou</body>", {"g1": "Les transports font 55 % du coût"})


def test_typographie_ne_touche_pas_aux_attributs_svg():
    page = '<head></head><body><svg><path d="M1,5.6 L2,4.4"/><text>727 Md S/ : 58 %</text></svg></body>'
    resultat = fiche.typographie(page)
    assert 'd="M1,5.6 L2,4.4"' in resultat  # le tracé reste valide
    assert "727 Md S/ : 58 %" in resultat


@pytest.mark.parametrize("soles, attendu", [(1.765e9, "1 765"), (4.7e5, "&lt;1"), (0, "0"), (float("nan"), "n.d.")])
def test_millions_entiers_dans_les_tableaux(soles, attendu):
    assert fiche.millions_entiers(soles) == attendu


def test_controle_refuse_une_valeur_non_calculee():
    with pytest.raises(SystemExit, match="nan"):
        fiche.controler("<head></head><body>coût : nan %</body>", {})
