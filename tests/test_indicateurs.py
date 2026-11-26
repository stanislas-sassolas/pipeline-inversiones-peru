"""Tests des règles de l'étape 2, sur de petits tableaux inventés dont on connaît la réponse.

Lancement, depuis le dossier du projet : python -m pytest
"""

import pandas as pd
import pytest

import indicateurs as ind


def projet(code, cout, modalite, pim=0, dev=0, funcion="TRANSPORTE", programa="TRANSPORTE URBANO", **autres):
    ligne = {
        "CODIGO_UNICO": code, "COSTO_ACTUALIZADO": cout, "DES_MODALIDAD": modalite,
        "PIM_ANIO_ACTUAL": pim, "DEV_ANIO_ACTUAL": dev, "FUNCION": funcion, "PROGRAMA": programa,
        "EXPEDIENTE_TECNICO": "SI", "AVANCE_FISICO": 50.0, "AVANCE_EJECUCION": 10.0,
        "NUM_HABITANTES_BENEF": 1000.0, "LATITUD": -12.0, "LONGITUD": -77.0,
        "NOMBRE_INVERSION": f"PROJET {code}", "DEPARTAMENTO": "LIMA", "SITUACION": "VIABLE",
        "DEVEN_ACUMUL_ANIO_ANT": 0.0, "ENTIDAD": f"ENTITE {code}", "NIVEL": "GN",
        "CTRL_CONCURR": 0.0, "ANIO_PROCESO": "2026", "SEC_EJEC": "1", "TIENE_F9": "NO", "ETAPA_F9": "",
    }
    return ligne | autres


# ---------------------------------------------------------------- modes de réalisation

def test_un_mode_simple():
    assert ind.modes_du_projet("ADMINISTRACIÓN INDIRECTA - POR CONTRATA") == ["Marché public (por contrata)"]


def test_plusieurs_modes_dans_l_ordre_de_priorite():
    libelle = "ADMINISTRACIÓN DIRECTA,ADMINISTRACIÓN INDIRECTA - ASOCIACIÓN PÚBLICA PRIVADA (APP)"
    assert ind.modes_du_projet(libelle) == ["APP", "Régie (administration directe)"]


def test_variantes_d_ecriture_reconnues():
    # Avec ou sans accents, et l'ancienne appellation « LEY 29230 » des travaux contre impôts.
    assert ind.modes_du_projet("ADMINISTRACION INDIRECTA - GOBIERNO A GOBIERNO") == ["Gouvernement à gouvernement (G2G)"]
    assert ind.modes_du_projet("ADMINISTRACIÓN INDIRECTA - ASOCIACIÓN PUBLICA PRIVADA (APP)") == ["APP"]
    assert ind.modes_du_projet("ADMINISTRACIÓN INDIRECTA - LEY 29230 (OBRAS POR IMPUESTOS)") == ["Travaux contre impôts (OxI)"]
    assert ind.modes_du_projet("ADMINISTRACIÓN INDIRECTA - NÚCLEO EJECUTOR") == ["Núcleo ejecutor (comité de bénéficiaires)"]


def test_administration_indirecte_n_est_pas_la_regie():
    # « INDIRECTA » contient « DIRECTA » : il ne faut pas compter une régie par erreur.
    assert "Régie (administration directe)" not in ind.modes_du_projet("ADMINISTRACIÓN INDIRECTA - POR CONTRATA")


def test_meme_mode_ecrit_deux_fois_compte_une_fois():
    libelle = "ADMINISTRACIÓN INDIRECTA - OBRAS POR IMPUESTOS,ADMINISTRACIÓN INDIRECTA - LEY 29230 (OBRAS POR IMPUESTOS)"
    assert ind.modes_du_projet(libelle) == ["Travaux contre impôts (OxI)"]


@pytest.mark.parametrize("vide", ["", "   ", "-", "-.-", None, float("nan")])
def test_mode_vide(vide):
    assert ind.modes_du_projet(vide) == [ind.NON_RENSEIGNE]


def test_libelle_inconnu():
    assert ind.modes_du_projet("QUELQUE CHOSE DE NOUVEAU") == [ind.AUTRE]


# ---------------------------------------------------------------- double comptage

def test_mode_principal_sans_double_comptage():
    """Avec le mode principal, chaque projet compte une seule fois : le total des lignes
    est égal au total général, même quand des projets ont plusieurs modes."""
    df = pd.DataFrame([
        projet("1", 500e6, "ADMINISTRACIÓN INDIRECTA - POR CONTRATA", pim=100, dev=50),
        projet("2", 300e6, "ADMINISTRACIÓN DIRECTA,ADMINISTRACIÓN INDIRECTA - POR CONTRATA", pim=100, dev=100),
        projet("3", 200e6, "ADMINISTRACIÓN INDIRECTA - POR CONTRATA,ADMINISTRACIÓN INDIRECTA - ASOCIACIÓN PÚBLICA PRIVADA (APP)"),
    ])
    df = ind.ajouter_secteur_et_modes(df)
    tableau = ind.tableau_par(df, "MODE_PRINCIPAL", taux=3.5, ordre=ind.ORDRE_MODES)
    lignes, total = tableau[tableau["MODE_PRINCIPAL"] != "TOTAL"], tableau[tableau["MODE_PRINCIPAL"] == "TOTAL"].iloc[0]

    assert lignes["nb_projets"].sum() == total["nb_projets"] == 3
    assert lignes["cout_total_Md_PEN"].sum() == pytest.approx(total["cout_total_Md_PEN"]) == pytest.approx(1.0)
    assert lignes["part_du_cout_%"].sum() == pytest.approx(100)
    # Le projet 3 est rangé en APP, pas en contrat public.
    assert lignes.set_index("MODE_PRINCIPAL").loc["APP", "nb_projets"] == 1


def test_vue_mentions_compte_les_projets_mixtes_deux_fois():
    df = pd.DataFrame([
        projet("1", 100e6, "ADMINISTRACIÓN INDIRECTA - POR CONTRATA"),
        projet("2", 100e6, "ADMINISTRACIÓN DIRECTA,ADMINISTRACIÓN INDIRECTA - POR CONTRATA"),
    ])
    mentions = ind.tableau_mentions(ind.ajouter_secteur_et_modes(df), taux=3.5).set_index("mode_mentionne")
    assert mentions.loc["Marché public (por contrata)", "nb_projets"] == 2
    assert mentions.loc["Régie (administration directe)", "nb_projets"] == 1
    assert mentions["nb_projets"].sum() == 3  # plus que 2 projets : c'est voulu, et documenté


# ---------------------------------------------------------------- taux d'exécution

def test_taux_execution_rapport_des_sommes():
    # Projet A : 90 dépensés sur 100. Projet B : 0 sur 900. Moyenne des taux = 45 %,
    # mais rapport des sommes = 90 / 1000 = 9 %. C'est le second qu'on veut.
    g = pd.DataFrame([projet("A", 200e6, "", pim=100, dev=90), projet("B", 200e6, "", pim=900, dev=0)])
    res = ind.indicateurs_groupe(g, taux=3.5, cout_total_general=400e6)
    assert res["taux_execution_annee_%"] == pytest.approx(9.0)


def test_taux_execution_ignore_les_projets_sans_pim():
    g = pd.DataFrame([projet("A", 200e6, "", pim=100, dev=50), projet("B", 200e6, "", pim=0, dev=0)])
    res = ind.indicateurs_groupe(g, taux=3.5, cout_total_general=400e6)
    assert res["nb_avec_PIM_annee"] == 1
    assert res["taux_execution_annee_%"] == pytest.approx(50.0)


def test_taux_execution_vide_si_aucun_pim():
    g = pd.DataFrame([projet("A", 200e6, "", pim=0, dev=0)])
    assert ind.indicateurs_groupe(g, taux=3.5, cout_total_general=200e6)["taux_execution_annee_%"] is None


def test_conversion_en_dollars():
    g = pd.DataFrame([projet("A", 3.5e9, "")])
    assert ind.indicateurs_groupe(g, taux=3.5, cout_total_general=3.5e9)["cout_total_Md_USD"] == pytest.approx(1.0)


# ---------------------------------------------------------------- secteurs

def test_secteur_programa_prioritaire_sur_funcion():
    regles = ind.lire_secteurs()
    # Les défenses contre les inondations sont classées en ORDEN PÚBLICO par le MEF,
    # mais on les range en prévention des risques grâce au PROGRAMA.
    assert ind.secteur_du_projet("ORDEN PÚBLICO Y SEGURIDAD", "GESTIÓN DE RIESGOS Y EMERGENCIAS", regles) == "Prévention des risques"
    assert ind.secteur_du_projet("ORDEN PÚBLICO Y SEGURIDAD", "ORDEN INTERNO", regles) == "Administration, justice et sécurité"
    assert ind.secteur_du_projet("SALUD Y SANEAMIENTO", "SANEAMIENTO", regles) == "Eau et assainissement"
    assert ind.secteur_du_projet("SALUD Y SANEAMIENTO", "SALUD INDIVIDUAL", regles) == "Santé"


def test_secteur_inconnu():
    assert ind.secteur_du_projet("FONCTION INVENTEE", "X", ind.lire_secteurs()) == "Non classé"


# ---------------------------------------------------------------- nettoyage

def test_nettoyage_des_valeurs_impossibles():
    df = pd.DataFrame([
        projet("1", 1, "", AVANCE_FISICO=250.0, NUM_HABITANTES_BENEF=815_000_000.0, LATITUD=0.0, LONGITUD=0.0),
        projet("2", 1, "", AVANCE_FISICO=100.0, AVANCE_EJECUCION=-3.0),
    ])
    propre, controles = ind.nettoyer(df)
    assert propre["AVANCE_FISICO"].isna().tolist() == [True, False]
    assert propre["AVANCE_EJECUCION"].isna().tolist() == [False, True]
    assert pd.isna(propre.loc[0, "NUM_HABITANTES_BENEF"])
    assert pd.isna(propre.loc[0, "LATITUD"]) and propre.loc[1, "LATITUD"] == -12.0
    assert controles.set_index("colonne").loc["AVANCE_FISICO", "valeurs_retirees"] == 1


def test_doublons_retires_mais_pas_les_codes_vides():
    df = pd.DataFrame([projet("7", 1, ""), projet("7", 1, ""), projet("", 1, ""), projet("", 1, "")])
    propre, nb = ind.retirer_doublons(df)
    assert nb == 1
    assert len(propre) == 3


def test_seuil_inclus():
    df = pd.DataFrame([projet("1", 100e6, ""), projet("2", 99_999_999, "")])
    assert ind.calculer(df, taux=3.5)["grands"]["CODIGO_UNICO"].tolist() == ["1"]


# ---------------------------------------------------------------- ajoutés après la vérification

def test_concurso_oferta_est_un_marche_public():
    assert ind.modes_du_projet("ADMINISTRACIÓN INDIRECTA - CONCURSO OFERTA") == ["Marché public (por contrata)"]


def test_mode_public_regroupe_le_g2g():
    df = ind.ajouter_secteur_et_modes(pd.DataFrame([
        projet("1", 100e6, "ADMINISTRACION INDIRECTA - GOBIERNO A GOBIERNO,ADMINISTRACIÓN INDIRECTA - POR CONTRATA"),
    ]))
    assert df.loc[0, "MODE_PRINCIPAL"] == "Gouvernement à gouvernement (G2G)"
    assert df.loc[0, "MODE_PUBLIC"] == ind.AUTRES_MONTAGES


def test_coordonnee_deja_vide_pas_comptee_comme_retiree():
    df = pd.DataFrame([projet("1", 1, "", LATITUD=float("nan"), LONGITUD=float("nan")),
                       projet("2", 1, "", LATITUD=0.0, LONGITUD=0.0)])
    _, controles = ind.nettoyer(df)
    assert controles.set_index("colonne").loc["LATITUD", "valeurs_retirees"] == 1


def test_codes_nan_pas_traites_comme_doublons():
    df = pd.DataFrame([projet(None, 1, ""), projet(None, 1, ""), projet("7", 1, "")])
    propre, nb = ind.retirer_doublons(df)
    assert nb == 0 and len(propre) == 3


def test_sans_budget_ni_depense():
    g = pd.DataFrame([projet("A", 1, ""), projet("B", 1, "", pim=10),
                      projet("C", 1, "", DEVEN_ACUMUL_ANIO_ANT=5.0)])
    assert ind.sans_budget_ni_depense(g).tolist() == [True, False, False]


def test_projets_a_verifier_saute_les_projets_deja_choisis():
    grands = ind.ajouter_secteur_et_modes(pd.DataFrame([
        projet("9", 900e6, "ADMINISTRACIÓN INDIRECTA - POR CONTRATA"),
        projet("2300242", 800e6, "ADMINISTRACIÓN INDIRECTA - ASOCIACIÓN PÚBLICA PRIVADA (APP)"),
        projet("5", 500e6, "ADMINISTRACIÓN INDIRECTA - ASOCIACIÓN PÚBLICA PRIVADA (APP)"),
        projet("4", 400e6, "ADMINISTRACIÓN INDIRECTA - OBRAS POR IMPUESTOS"),
        projet("3", 300e6, "ADMINISTRACIÓN DIRECTA,ADMINISTRACIÓN INDIRECTA - POR CONTRATA"),
    ]))
    tableau = ind.projets_a_verifier(grands)
    # Le métro est déjà retenu, donc l'APP choisie est la suivante (code 5).
    assert tableau["CODIGO_UNICO"].tolist() == ["9", "2300242", "5", "4", "3"]


class FausseReponse:
    def __init__(self, texte):
        self.texte = texte.encode("utf-8")

    def read(self):
        return self.texte

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_taux_change_json_suivi_de_html(monkeypatch, tmp_path):
    # Vraie forme de la réponse de la BCRP : le JSON, puis un message d'erreur PHP en HTML.
    reponse = ('{"config":{},"periods":[{"name":"Ene.2026","values":["3.3"]},'
               '{"name":"Feb.2026","values":["3.5"]},{"name":"Mar.2026","values":["n.d."]}]}'
               "<table><tr><td>getBrowser()</td></tr></table>")
    monkeypatch.setattr(ind, "TAUX_CACHE", tmp_path / "taux.json")
    monkeypatch.setattr(ind.urllib.request, "urlopen", lambda *a, **k: FausseReponse(reponse))
    info = ind.taux_change(2026)
    assert info["soles_par_dollar"] == pytest.approx(3.4)
    assert info["periode"] == "taux interbancaire, moyenne de janvier à février 2026"
    assert (tmp_path / "taux.json").exists()


def test_taux_change_reprend_le_cache_si_reponse_inutilisable(monkeypatch, tmp_path):
    cache = tmp_path / "taux.json"
    cache.write_text('{"serie": "PN01207PM", "annee": 2026, "soles_par_dollar": 3.4, "periode": "x"}', encoding="utf-8")
    monkeypatch.setattr(ind, "TAUX_CACHE", cache)
    monkeypatch.setattr(ind.urllib.request, "urlopen", lambda *a, **k: FausseReponse('{"periods": null}'))
    assert ind.taux_change(2026)["soles_par_dollar"] == 3.4


# ---------------------------------------------------------------- corrections faites à la main

def corrections(*lignes):
    return pd.DataFrame(lignes, columns=["CODIGO_UNICO", "MODE_CORRIGE", "NOTE", "SOURCE"])


def test_mode_corrige_remplace_le_mode_du_mef():
    df = pd.DataFrame([projet("1", 100e6, "-.-"), projet("2", 100e6, "-.-")])
    df = ind.ajouter_secteur_et_modes(df, corrections(("1", "APP", "concession", "https://exemple")))
    assert df["MODE_PRINCIPAL"].tolist() == ["APP", ind.NON_RENSEIGNE]
    assert df["MODE_CORRIGE_A_LA_MAIN"].tolist() == [True, False]


def test_note_sans_correction_de_mode():
    df = pd.DataFrame([projet("1", 100e6, "-.-")])
    df = ind.ajouter_secteur_et_modes(df, corrections(("1", "", "contrat résilié", "https://exemple")))
    assert df.loc[0, "MODE_PRINCIPAL"] == ind.NON_RENSEIGNE
    assert df.loc[0, "NOTE"] == "contrat résilié"


def test_mode_corrige_inconnu_refuse(monkeypatch, tmp_path):
    fichier = tmp_path / "corrections.csv"
    fichier.write_text("CODIGO_UNICO;MODE_CORRIGE;NOTE;SOURCE\n1;Concession;x;y\n", encoding="utf-8")
    monkeypatch.setattr(ind, "CORRECTIONS_CSV", fichier)
    with pytest.raises(ValueError):
        ind.lire_corrections()


def test_harmoniser_cout_ajoute_le_controle():
    df = pd.DataFrame([projet("1", 99e6, "", CTRL_CONCURR=1.5e6), projet("2", 99e6, "", CTRL_CONCURR=float("nan"))])
    harmonise, nb = ind.harmoniser_cout(df)
    assert harmonise["COSTO_ACTUALIZADO"].tolist() == [100.5e6, 99e6]
    assert (harmonise["CTRL_CONCURR"] == 0).all() and nb == 1


@pytest.mark.parametrize("contenu", [
    "CODIGO_UNICO;MODE_CORRIGE;NOTE;SOURCE\n1;;une note;\n",                        # source vide
    "CODIGO_UNICO;MODE_CORRIGE;NOTE;SOURCE\n1;;a;https://x\n1;APP;b;https://y\n",    # code en double
    "CODIGO_UNICO;MODE_CORRIGE;SOURCE\n1;;https://x\n",                              # colonne NOTE absente
])
def test_corrections_mal_formees_refusees(monkeypatch, tmp_path, contenu):
    fichier = tmp_path / "corrections.csv"
    fichier.write_text(contenu, encoding="utf-8")
    monkeypatch.setattr(ind, "CORRECTIONS_CSV", fichier)
    with pytest.raises(ValueError):
        ind.lire_corrections()


def test_coordonnees_inversees_remises_dans_l_ordre():
    df = pd.DataFrame([projet("1", 1, "", LATITUD=-76.97, LONGITUD=-12.15)])
    propre, controles = ind.nettoyer(df)
    assert (propre.loc[0, "LATITUD"], propre.loc[0, "LONGITUD"]) == (-12.15, -76.97)
    assert controles.set_index("colonne").loc["LATITUD/LONGITUD", "valeurs_retirees"] == 1
