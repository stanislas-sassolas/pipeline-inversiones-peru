"""Étape 2 : calculer les indicateurs des grands projets à partir de la dernière archive.

Ce que fait le script, dans l'ordre :
1. Lit la dernière archive Parquet, retire les lignes en double (même CODIGO_UNICO) et ajoute au coût le
   contrôle concomitant (CTRL_CONCURR, voir harmoniser_cout).
2. Garde les projets dont le coût (COSTO_ACTUALIZADO + CTRL_CONCURR) atteint 100 millions de soles.
3. Sur ces grands projets, met à vide les valeurs impossibles (avancement hors de 0-100 %,
   bénéficiaires plus nombreux que la population du Pérou, coordonnées hors du pays).
4. Range chaque projet dans un secteur (fichier secteurs.csv) et repère ses modes
   de réalisation (APP, travaux contre impôts, marché public...).
5. Calcule, par secteur et par mode : nombre de projets, coût total, part sans budget ni dépense,
   budget de l'année (PIM), dépenses de l'année (devengado) et taux d'exécution, en soles et en dollars.
6. Signale les cas à vérifier à la main (doublon probable, coût sans rapport avec l'entité).
7. Écrit le tout dans exports/indicateurs_<date>.xlsx (fichier de travail, pas une sortie publique).

Lancement : python indicateurs.py
"""

import json
import sys
import unicodedata
import urllib.request
from datetime import date
from pathlib import Path

import pandas as pd

from archiver import DATA_DIR, SNAP_DIR

DOSSIER = Path(__file__).parent
SECTEURS_CSV = DOSSIER / "secteurs.csv"
CORRECTIONS_CSV = DOSSIER / "corrections_projets.csv"
SORTIE_DIR = DOSSIER / "exports"
TAUX_CACHE = DATA_DIR / "taux_change_bcrp.json"

SEUIL_SOLES = 100e6
# Le Pérou compte environ 34 millions d'habitants (INEI) : au-delà de 35 millions, la valeur est impossible.
MAX_BENEFICIAIRES = 35_000_000
# Rectangle qui contient le Pérou (latitude, longitude). Le MEF met (0, 0) quand il n'a pas de coordonnées.
LAT_MIN, LAT_MAX = -18.5, 0.1
LON_MIN, LON_MAX = -81.5, -68.5
# Un projet communal sans budget ni dépense qui coûte plus de 50 fois le budget de l'année de toute la commune
# est suspect.
RAPPORT_COUT_ENTITE_SUSPECT = 50

# Série BCRP PN01207PM : taux de change interbancaire, moyenne du mois, en soles pour 1 dollar.
URL_BCRP = "https://estadisticas.bcrp.gob.pe/estadisticas/series/api/PN01207PM/json/{debut}/{fin}"

# Modes de réalisation : (mots-clés cherchés dans le libellé du MEF, nom affiché).
# L'ordre compte : quand un projet a plusieurs modes, son « mode principal » est le premier de la liste.
# C'est une convention : on retient le montage le plus structurant déclaré, dans l'ordre de la liste ci-dessous,
# parce que le marché public et la régie servent souvent à des parties annexes (études, supervision).
MODES = [
    (["ASOCIACION PUBLICA PRIVADA"], "APP"),
    (["GOBIERNO A GOBIERNO"], "Gouvernement à gouvernement (G2G)"),
    (["OBRAS POR IMPUESTOS"], "Travaux contre impôts (OxI)"),
    (["NUCLEO EJECUTOR"], "Núcleo ejecutor (comité de bénéficiaires)"),
    (["CONVENIO DE ADMINISTRACION DE RECURSOS"], "Convention avec un organisme international"),
    (["POR CONTRATA", "CONCURSO OFERTA"], "Marché public (por contrata)"),
    (["BIENES Y SERVICIOS"], "Achat de biens et services"),
    (["ADMINISTRACION DIRECTA"], "Régie (administration directe)"),
]
AUTRE = "Autre"
NON_RENSEIGNE = "Non renseigné"
ORDRE_MODES = [nom for _, nom in MODES] + [AUTRE, NON_RENSEIGNE]

# Pour toute sortie publique (fiche, carte), seuls l'APP, les travaux contre impôts, le marché public et la régie
# sont détaillés : tous les autres montages sont regroupés dans « Autres montages » (le total reste juste).
AUTRES_MONTAGES = "Autres montages"
MODE_PUBLIC = {
    "Gouvernement à gouvernement (G2G)": AUTRES_MONTAGES,
    "Núcleo ejecutor (comité de bénéficiaires)": AUTRES_MONTAGES,
    "Convention avec un organisme international": AUTRES_MONTAGES,
    "Achat de biens et services": AUTRES_MONTAGES,
    AUTRE: AUTRES_MONTAGES,
}
ORDRE_MODES_PUBLICS = ["APP", "Travaux contre impôts (OxI)", "Marché public (por contrata)",
                       "Régie (administration directe)", AUTRES_MONTAGES, NON_RENSEIGNE]


def simplifier(texte):
    """Majuscules sans accents ni espaces autour : « Núcleo ejecutor » devient « NUCLEO EJECUTOR »."""
    decompose = unicodedata.normalize("NFD", str(texte))
    sans_accents = "".join(c for c in decompose if unicodedata.category(c) != "Mn")
    return sans_accents.upper().strip()


# ---------------------------------------------------------------- 1 à 3 : nettoyage

def retirer_doublons(df):
    """Retire les lignes dont le CODIGO_UNICO est déjà apparu plus haut.

    Les lignes sans code (anciens projets SNIP) ne sont pas des doublons entre elles : on les garde.
    """
    sans_code = df["CODIGO_UNICO"].fillna("").str.strip() == ""
    doublon = ~sans_code & df.duplicated("CODIGO_UNICO", keep="first")
    return df[~doublon].copy(), int(doublon.sum())


def harmoniser_cout(df):
    """Rend le coût comparable entre toutes les archives : coût = COSTO_ACTUALIZADO + CTRL_CONCURR.

    D'habitude, le coût du contrôle concomitant de la Contraloría est dans une colonne à part (CTRL_CONCURR)
    et n'est PAS compris dans COSTO_ACTUALIZADO. Mais dans ses fichiers des 20 et 23/11/2026, le MEF l'avait
    ajouté au coût et mis la colonne à 0, avant de revenir à l'ancien format le 24/11. L'addition est juste
    dans les deux formats : quand le contrôle est déjà dans le coût, la colonne vaut 0 et rien n'est compté
    deux fois. Sans cela, 12 projets semblaient passer au-dessus de 100 M entre le 14 et le 23/11 sans rien de réel.
    """
    df = df.copy()
    controle = df["CTRL_CONCURR"].fillna(0)
    df["COSTO_ACTUALIZADO"] = df["COSTO_ACTUALIZADO"] + controle
    df["CTRL_CONCURR"] = 0.0
    return df, int((controle != 0).sum())


def nettoyer(df):
    """Met à vide (NaN) les valeurs impossibles, remet dans l'ordre les latitudes et longitudes inversées,
    et compte combien de valeurs on a retirées ou corrigées par colonne.

    On ne compte que les valeurs qui étaient remplies : une case déjà vide n'est pas « retirée ».
    """
    df = df.copy()
    controles = []

    def vider(colonne, masque, regle):
        controles.append({"colonne": colonne, "regle": regle, "valeurs_retirees": int(masque.sum())})
        df.loc[masque, colonne] = float("nan")

    for col in ["AVANCE_FISICO", "AVANCE_EJECUCION"]:
        vider(col, (df[col] < 0) | (df[col] > 100), "hors de 0 à 100 %")
    benef = df["NUM_HABITANTES_BENEF"]
    vider("NUM_HABITANTES_BENEF", (benef < 0) | (benef > MAX_BENEFICIAIRES),
          f"négatif ou plus de {MAX_BENEFICIAIRES:,} habitants".replace(",", " "))
    # Certaines entités ont inversé latitude et longitude (ex. -76,97 / -12,15 pour Lima) : on les remet
    # dans le bon ordre au lieu de les jeter, car le point est alors bien au Pérou. Pas de faux positif possible :
    # une latitude entre -81,5 et -68,5 n'existe pas au Pérou (ce serait l'Antarctique).
    inverse = (df["LONGITUD"].between(LAT_MIN, LAT_MAX) & df["LATITUD"].between(LON_MIN, LON_MAX))
    df.loc[inverse, ["LATITUD", "LONGITUD"]] = df.loc[inverse, ["LONGITUD", "LATITUD"]].values
    controles.append({"colonne": "LATITUD/LONGITUD", "regle": "latitude et longitude inversées, remises dans l'ordre (corrigées, pas retirées)",
                      "valeurs_retirees": int(inverse.sum())})
    # between() renvoie False pour une case vide : on ne regarde donc que les points remplis.
    connu = df["LATITUD"].notna() & df["LONGITUD"].notna()
    dans_le_perou = df["LATITUD"].between(LAT_MIN, LAT_MAX) & df["LONGITUD"].between(LON_MIN, LON_MAX)
    hors_perou = connu & ~dans_le_perou
    regle = "point hors du Pérou, presque toujours (0, 0) = pas de coordonnées"
    vider("LATITUD", hors_perou, regle)
    vider("LONGITUD", hors_perou, regle)
    return df, pd.DataFrame(controles)


# ---------------------------------------------------------------- 4 : secteurs et modes

def lire_secteurs():
    """Lit secteurs.csv : pour chaque FUNCION (et parfois un PROGRAMA précis), le secteur de la fiche."""
    table = pd.read_csv(SECTEURS_CSV, sep=";", dtype=str, encoding="utf-8")
    return {(simplifier(r.FUNCION), simplifier(r.PROGRAMA)): r.SECTEUR for r in table.itertuples()}


def secteur_du_projet(funcion, programa, regles):
    """Cherche la règle la plus précise : FUNCION + PROGRAMA, puis PROGRAMA seul, puis FUNCION seule."""
    f, p = simplifier(funcion), simplifier(programa)
    for cle in [(f, p), ("*", p), (f, "*")]:
        if cle in regles:
            return regles[cle]
    return "Non classé"


def modes_du_projet(libelle):
    """Liste des modes d'un projet, sans doublon, dans l'ordre de MODES.

    « ADMINISTRACIÓN DIRECTA,ADMINISTRACIÓN INDIRECTA - POR CONTRATA » donne
    ["Marché public (por contrata)", "Régie (administration directe)"].
    """
    if libelle is None or pd.isna(libelle):
        return [NON_RENSEIGNE]
    trouves = set()
    for morceau in simplifier(libelle).split(","):
        if morceau.strip(" -.") == "":  # vide, « - » ou « -.- »
            continue
        nom = next((nom for cles, nom in MODES if any(cle in morceau for cle in cles)), AUTRE)
        trouves.add(nom)
    if not trouves:
        return [NON_RENSEIGNE]
    return sorted(trouves, key=ORDRE_MODES.index)


def lire_corrections():
    """Lit corrections_projets.csv : corrections et notes faites à la main, projet par projet.

    Colonnes : CODIGO_UNICO ; MODE_CORRIGE (vide = on garde le mode du MEF) ; NOTE ; SOURCE.
    Chaque ligne doit citer sa source : on ne corrige jamais le MEF « de mémoire ».
    """
    colonnes = ["CODIGO_UNICO", "MODE_CORRIGE", "NOTE", "SOURCE"]
    if not CORRECTIONS_CSV.exists():
        return pd.DataFrame(columns=colonnes)
    table = pd.read_csv(CORRECTIONS_CSV, sep=";", dtype=str, encoding="utf-8", keep_default_na=False)
    manquantes = set(colonnes) - set(table.columns)
    if manquantes:
        raise ValueError(f"Colonnes manquantes dans {CORRECTIONS_CSV.name} : {manquantes}")
    inconnus = set(table["MODE_CORRIGE"]) - set(ORDRE_MODES) - {""}
    if inconnus:
        raise ValueError(f"Mode inconnu dans {CORRECTIONS_CSV.name} : {inconnus}")
    if (table["SOURCE"].str.strip() == "").any():
        raise ValueError(f"Une ligne de {CORRECTIONS_CSV.name} n'a pas de source.")
    if table["CODIGO_UNICO"].duplicated().any():
        raise ValueError(f"Un code apparaît deux fois dans {CORRECTIONS_CSV.name}.")
    return table[colonnes]


def ajouter_secteur_et_modes(df, corrections=None):
    regles = lire_secteurs()
    corrections = lire_corrections() if corrections is None else corrections
    mode_par_code = dict(zip(corrections["CODIGO_UNICO"], corrections["MODE_CORRIGE"]))
    note_par_code = dict(zip(corrections["CODIGO_UNICO"], corrections["NOTE"]))
    df = df.copy()
    df["SECTEUR_FICHE"] = [secteur_du_projet(f, p, regles) for f, p in zip(df["FUNCION"], df["PROGRAMA"])]
    mode_corrige = [mode_par_code.get(code, "") for code in df["CODIGO_UNICO"]]
    df["MODE_CORRIGE_A_LA_MAIN"] = [corrige != "" for corrige in mode_corrige]
    # Un mode corrigé à la main remplace tous les modes déclarés par le MEF pour ce projet.
    df["MODES"] = [[corrige] if corrige else modes_du_projet(libelle)
                   for libelle, corrige in zip(df["DES_MODALIDAD"], mode_corrige)]
    df["NOTE"] = [note_par_code.get(code, "") for code in df["CODIGO_UNICO"]]
    df["MODE_PRINCIPAL"] = [modes[0] for modes in df["MODES"]]
    df["MODE_PUBLIC"] = df["MODE_PRINCIPAL"].replace(MODE_PUBLIC)
    df["NB_MODES"] = [len(modes) for modes in df["MODES"]]
    return df


# ---------------------------------------------------------------- 5 : indicateurs

def sans_budget_ni_depense(g):
    """Vrai pour les projets sans aucun crédit public : ni PIM ni devengado cette année, ni devengado les années
    précédentes. Le financement privé des APP n'est pas dans le fichier : il n'est donc pas compté ici."""
    return ((g["PIM_ANIO_ACTUAL"] <= 0) & (g["DEV_ANIO_ACTUAL"] <= 0)
            & (g["DEVEN_ACUMUL_ANIO_ANT"].fillna(0) <= 0))


def indicateurs_groupe(g, taux, cout_total_general):
    """Les indicateurs d'un groupe de projets (un secteur, un mode, ou tous les projets).

    Taux d'exécution 2026 = somme des devengados / somme des PIM, sur les projets qui ont un PIM.
    On fait le rapport des sommes et pas la moyenne des taux : un projet de 1 milliard pèse plus
    qu'un projet de 100 millions. C'est aussi le calcul de la Consulta Amigable du MEF.
    """
    cout = g["COSTO_ACTUALIZADO"].sum()
    jamais = g[sans_budget_ni_depense(g)]
    avec_pim = g[g["PIM_ANIO_ACTUAL"] > 0]
    pim = avec_pim["PIM_ANIO_ACTUAL"].sum()
    dev = avec_pim["DEV_ANIO_ACTUAL"].sum()
    return {
        "nb_projets": len(g),
        "cout_total_Md_PEN": cout / 1e9,
        "cout_total_Md_USD": cout / 1e9 / taux,
        "part_du_cout_%": 100 * cout / cout_total_general,
        "nb_sans_budget_ni_depense": len(jamais),
        "cout_sans_budget_ni_depense_Md_PEN": jamais["COSTO_ACTUALIZADO"].sum() / 1e9,
        "nb_avec_PIM_annee": len(avec_pim),
        "PIM_annee_M_PEN": pim / 1e6,
        "devengado_annee_M_PEN": dev / 1e6,
        "PIM_annee_M_USD": pim / 1e6 / taux,
        "devengado_annee_M_USD": dev / 1e6 / taux,
        "taux_execution_annee_%": 100 * dev / pim if pim > 0 else None,
        # Si un seul projet porte l'essentiel du PIM, le taux du groupe est surtout le sien.
        "part_du_PIM_du_plus_gros_projet_%": 100 * avec_pim["PIM_ANIO_ACTUAL"].max() / pim if pim > 0 else None,
        "nb_sans_expediente_tecnico": int((g["EXPEDIENTE_TECNICO"] == "NO").sum()),
    }


def tableau_par(df, colonne, taux, ordre=None):
    """Une ligne par valeur de `colonne` (triée par coût, ou selon `ordre`), plus une ligne TOTAL."""
    cout_total = df["COSTO_ACTUALIZADO"].sum()
    lignes = [{colonne: nom} | indicateurs_groupe(g, taux, cout_total) for nom, g in df.groupby(colonne)]
    tableau = pd.DataFrame(lignes)
    if ordre:
        tableau = tableau.sort_values(colonne, key=lambda s: s.map(ordre.index))
    else:
        tableau = tableau.sort_values("cout_total_Md_PEN", ascending=False)
    total = pd.DataFrame([{colonne: "TOTAL"} | indicateurs_groupe(df, taux, cout_total)])
    return pd.concat([tableau, total], ignore_index=True)


def tableau_mentions(df, taux):
    """Combien de projets mentionnent chaque mode. Un projet à deux modes compte dans les deux lignes :
    les colonnes ne s'additionnent donc pas (c'est pour ça qu'il n'y a pas de ligne TOTAL)."""
    eclate = df.explode("MODES")
    tableau = tableau_par(eclate, "MODES", taux, ordre=ORDRE_MODES)
    tableau = tableau[tableau["MODES"] != "TOTAL"].rename(columns={"MODES": "mode_mentionne"})
    return tableau.drop(columns=["part_du_cout_%"])


def taux_change(annee):
    """Taux de change moyen de l'année des données (série BCRP PN01207PM), gardé en cache.

    On prend la moyenne des mois déjà publiés de l'année (janvier à octobre pour des données de
    novembre 2026). Un seul taux pour tous les montants : c'est une conversion indicative pour lire
    les ordres de grandeur en dollars. Les comparaisons d'une semaine à l'autre se font en soles.
    """
    try:
        url = URL_BCRP.format(debut=f"{annee}-1", fin=f"{annee}-12")
        requete = urllib.request.Request(url, headers={"User-Agent": "pipeline-inversiones-peru"})
        with urllib.request.urlopen(requete, timeout=30) as reponse:
            texte = reponse.read().decode("utf-8-sig")
        # Le serveur de la BCRP colle parfois un message d'erreur HTML après le JSON :
        # raw_decode lit le premier objet JSON complet et ignore ce qui suit.
        donnees, _ = json.JSONDecoder().raw_decode(texte.strip())
        publies = [(p["name"], float(p["values"][0])) for p in donnees["periods"]
                   if p["values"][0] not in ("n.d.", "")]
        moyenne = sum(valeur for _, valeur in publies) / len(publies)
        # La BCRP nomme les mois en espagnol abrégé (« Ene.2026 ») : on écrit la période en français.
        mois_fr = {"Ene": "janvier", "Feb": "février", "Mar": "mars", "Abr": "avril", "May": "mai", "Jun": "juin",
                   "Jul": "juillet", "Ago": "août", "Sep": "septembre", "Oct": "octobre", "Nov": "novembre",
                   "Dic": "décembre"}
        premier, dernier = (mois_fr.get(nom.split(".")[0], nom) for nom in (publies[0][0], publies[-1][0]))
        info = {"serie": "PN01207PM", "annee": annee, "soles_par_dollar": round(moyenne, 3),
                "periode": f"taux interbancaire, moyenne de {premier} à {dernier} {annee}",
                "recupere_le": date.today().isoformat()}
        TAUX_CACHE.write_text(json.dumps(info, ensure_ascii=False, indent=1), encoding="utf-8")
    except (OSError, ValueError, KeyError, IndexError, TypeError, ZeroDivisionError) as erreur:
        if not TAUX_CACHE.exists():
            raise
        info = json.loads(TAUX_CACHE.read_text(encoding="utf-8"))
        print(f"Réponse BCRP inutilisable ({erreur!r}) : taux en cache, {info['periode']}.")
        if info.get("annee") != annee:
            print(f"Attention : le taux en cache est celui de {info.get('annee')}, pas de {annee}.")
    return info


# ---------------------------------------------------------------- 6 : contrôles à la main

def projets_a_verifier(grands):
    """Cinq projets à vérifier à la main dans la source, avec la raison de chaque choix.
    On parcourt les critères dans l'ordre et on saute un projet déjà choisi : comme la ligne 3 du
    métro est déjà une APP, l'« APP » retenue est la plus grosse APP autre que le métro."""
    criteres = [
        ("le plus cher", pd.Series(True, index=grands.index)),
        ("ligne 3 du métro (exemple de référence)", grands["CODIGO_UNICO"] == "2300242"),
        ("plus grosse APP (hors projets déjà choisis)", grands["MODE_PRINCIPAL"] == "APP"),
        ("plus gros projet en travaux contre impôts", grands["MODE_PRINCIPAL"] == "Travaux contre impôts (OxI)"),
        ("plus gros projet à plusieurs modes (hors autres montages)",
         (grands["NB_MODES"] > 1) & (grands["MODE_PUBLIC"] != AUTRES_MONTAGES)),
    ]
    choix, raisons = [], []
    for raison, masque in criteres:
        restants = grands[masque & ~grands.index.isin(choix)]  # grands est déjà trié du plus cher au moins cher
        if len(restants):
            choix.append(restants.index[0])
            raisons.append(raison)
    colonnes = ["CODIGO_UNICO", "NOMBRE_INVERSION", "DES_MODALIDAD", "MODE_PRINCIPAL", "SECTEUR_FICHE",
                "COSTO_ACTUALIZADO", "PIM_ANIO_ACTUAL", "DEV_ANIO_ACTUAL", "EXPEDIENTE_TECNICO", "SITUACION", "NOTE"]
    tableau = grands.loc[choix, colonnes].copy()
    tableau.insert(0, "raison_du_choix", raisons)
    tableau["ou_verifier"] = "https://ofi5.mef.gob.pe/ssi/ssi/Index puis « Cód. SNIP o CUI » et le code"
    tableau["valeur_lue_dans_la_source"] = ""
    tableau["identique ?"] = ""
    return tableau


def signalements(grands, df_complet):
    """Cas à vérifier à la main avant d'en parler. Ils ne sont PAS retirés des calculs."""
    cas = []
    # Même entité et même coût au centime près : probablement un même ouvrage enregistré deux fois.
    doublon = grands.duplicated(["ENTIDAD", "COSTO_ACTUALIZADO"], keep=False)
    for _, p in grands[doublon].iterrows():
        cas.append({"CODIGO_UNICO": p["CODIGO_UNICO"], "probleme": "doublon probable (même entité, même coût)",
                    "NOMBRE_INVERSION": p["NOMBRE_INVERSION"], "ENTIDAD": p["ENTIDAD"],
                    "COSTO_ACTUALIZADO": p["COSTO_ACTUALIZADO"]})
    # Commune dont un projet sans budget ni dépense écrase le budget de l'année de toute la commune.
    # On se limite aux communes (NIVEL = GL) : un ministère ou ProInversión porte normalement
    # des projets bien plus gros que son budget d'une année, ce n'est pas suspect.
    pim_entite = df_complet.groupby("ENTIDAD")["PIM_ANIO_ACTUAL"].sum()
    rapport = grands["COSTO_ACTUALIZADO"] / grands["ENTIDAD"].map(pim_entite)
    suspect = (grands["NIVEL"] == "GL") & sans_budget_ni_depense(grands) & (rapport > RAPPORT_COUT_ENTITE_SUSPECT)
    for _, p in grands[suspect].iterrows():
        cas.append({"CODIGO_UNICO": p["CODIGO_UNICO"],
                    "probleme": f"commune : sans budget ni dépense et plus de {RAPPORT_COUT_ENTITE_SUSPECT} fois le PIM de l'année de la commune",
                    "NOMBRE_INVERSION": p["NOMBRE_INVERSION"], "ENTIDAD": p["ENTIDAD"],
                    "COSTO_ACTUALIZADO": p["COSTO_ACTUALIZADO"]})
    return pd.DataFrame(cas, columns=["CODIGO_UNICO", "probleme", "NOMBRE_INVERSION", "ENTIDAD", "COSTO_ACTUALIZADO"])


# ---------------------------------------------------------------- programme principal

def pour_affichage(tableau):
    """Le fichier du MEF remplace certains tirets par « ¿ » dans les noms : on les remet pour l'affichage."""
    tableau = tableau.copy()
    if "NOMBRE_INVERSION" in tableau:
        tableau["NOMBRE_INVERSION"] = tableau["NOMBRE_INVERSION"].str.replace("¿", "-", regex=False)
    return tableau


def calculer(df, taux):
    """Tout le calcul, sans lecture ni écriture de fichier (c'est ce que testent les tests)."""
    df, nb_doublons = retirer_doublons(df)
    df, nb_controles_ajoutes = harmoniser_cout(df)
    grands = df[df["COSTO_ACTUALIZADO"] >= SEUIL_SOLES]
    grands, controles = nettoyer(grands)
    grands = ajouter_secteur_et_modes(grands).sort_values("COSTO_ACTUALIZADO", ascending=False)

    controles = pd.concat([
        pd.DataFrame([{"colonne": "CODIGO_UNICO", "regle": "ligne en double retirée (tout le fichier)",
                       "valeurs_retirees": nb_doublons},
                      {"colonne": "CTRL_CONCURR", "regle": "ajouté au coût quand la colonne est remplie (tout le fichier)",
                       "valeurs_retirees": nb_controles_ajoutes}]),
        controles,
        pd.DataFrame([{"colonne": "DES_MODALIDAD", "regle": "mode corrigé à la main (corrections_projets.csv)",
                       "valeurs_retirees": int(grands["MODE_CORRIGE_A_LA_MAIN"].sum())}]),
    ], ignore_index=True)

    top = grands.head(15)[["CODIGO_UNICO", "NOMBRE_INVERSION", "SECTEUR_FICHE", "MODE_PUBLIC",
                           "DEPARTAMENTO", "SITUACION", "EXPEDIENTE_TECNICO", "COSTO_ACTUALIZADO",
                           "PIM_ANIO_ACTUAL", "DEV_ANIO_ACTUAL", "AVANCE_FISICO", "NOTE"]].copy()
    top.insert(8, "COSTO_Md_USD", top["COSTO_ACTUALIZADO"] / 1e9 / taux)
    top.insert(9, "sans_budget_ni_depense", sans_budget_ni_depense(grands.head(15)).map({True: "oui", False: "non"}))

    return {
        "grands": grands,
        "secteurs": tableau_par(grands, "SECTEUR_FICHE", taux),
        "modes_public": tableau_par(grands, "MODE_PUBLIC", taux, ordre=ORDRE_MODES_PUBLICS),
        "modes_detail": tableau_par(grands, "MODE_PRINCIPAL", taux, ordre=ORDRE_MODES),
        "modes_mentions": tableau_mentions(grands, taux),
        "top15": pour_affichage(top),
        "a_verifier": pour_affichage(projets_a_verifier(grands)),
        "signalements": pour_affichage(signalements(grands, df)),
        "controles": controles,
    }


def ecrire_excel(res, sortie, info_taux, jour):
    grands = res["grands"]
    resume = pd.DataFrame([
        ("Fichier de travail", "ne pas diffuser tel quel", "pour une sortie publique, utiliser modes_public et non modes_detail"),
        ("Date des données MEF", jour, ""),
        ("Seuil", "100 M de soles", "coût = COSTO_ACTUALIZADO + CTRL_CONCURR, pluriannuel et indicatif"),
        ("Taux de change", info_taux["soles_par_dollar"], f"BCRP {info_taux['serie']}, {info_taux['periode']}, conversion indicative"),
        ("Projets retenus", len(grands), "après retrait des doublons de code"),
        ("dont sans budget ni dépense", int(sans_budget_ni_depense(grands).sum()), "ni PIM de l'année, ni dépense depuis l'origine"),
        ("Projets à plusieurs modes", int((grands["NB_MODES"] > 1).sum()), "voir l'onglet modes_mentions"),
        ("Contrôles", "sur les grands projets", "sauf les doublons de code, retirés sur tout le fichier"),
    ], columns=["indicateur", "valeur", "note"])

    onglets = {"resume": resume} | {nom: res[nom] for nom in
               ["secteurs", "modes_public", "modes_detail", "modes_mentions", "top15",
                "a_verifier", "signalements", "controles"]}
    with pd.ExcelWriter(sortie, engine="openpyxl") as xl:
        for nom, tableau in onglets.items():
            tableau.round(2).to_excel(xl, sheet_name=nom, index=False)
            feuille = xl.sheets[nom]
            feuille.freeze_panes = "B2"
            for colonne in feuille.columns:
                titre = str(colonne[0].value)
                feuille.column_dimensions[colonne[0].column_letter].width = 60 if titre == "NOMBRE_INVERSION" else max(14, len(titre) + 2)
                if titre in ("COSTO_ACTUALIZADO", "PIM_ANIO_ACTUAL", "DEV_ANIO_ACTUAL"):
                    for cellule in colonne[1:]:
                        cellule.number_format = "#,##0"


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    archive = sorted(SNAP_DIR.glob("inversiones_*.parquet"))[-1]
    jour = archive.stem.replace("inversiones_", "")
    info_taux = taux_change(int(jour[:4]))
    res = calculer(pd.read_parquet(archive), info_taux["soles_par_dollar"])

    SORTIE_DIR.mkdir(exist_ok=True)
    sortie = SORTIE_DIR / f"indicateurs_{jour}.xlsx"
    ecrire_excel(res, sortie, info_taux, jour)

    pd.set_option("display.width", 220)
    colonnes = ["nb_projets", "cout_total_Md_PEN", "cout_total_Md_USD", "part_du_cout_%",
                "cout_sans_budget_ni_depense_Md_PEN", "PIM_annee_M_PEN", "devengado_annee_M_PEN", "taux_execution_annee_%"]
    print(f"Données MEF du {jour}, 1 USD = {info_taux['soles_par_dollar']:.3f} PEN ({info_taux['periode']})\n")
    print(res["secteurs"].set_index("SECTEUR_FICHE")[colonnes].round(1).to_string(), "\n")
    print(res["modes_public"].set_index("MODE_PUBLIC")[colonnes].round(1).to_string(), "\n")
    print(res["controles"].to_string(index=False), "\n")
    print(res["signalements"][["CODIGO_UNICO", "probleme", "COSTO_ACTUALIZADO"]].to_string(index=False), "\n")
    print(f"-> {sortie}")


if __name__ == "__main__":
    main()
