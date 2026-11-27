"""Étape 3 : ce qui a bougé entre deux archives, pour les grands projets.

Ce que fait le script, dans l'ordre :
1. Choisit deux archives : la plus récente, et la plus récente datant d'au moins 7 jours avant elle
   (ou une ou deux dates données à la main).
2. Cherche les ruptures de format : une colonne dont le taux de remplissage change fortement d'une
   archive à l'autre veut dire que le MEF a changé son fichier, pas que les projets ont bougé.
3. Prépare chaque archive comme à l'étape 2 : doublons retirés, coût harmonisé (contrôle concomitant
   compris), valeurs impossibles vidées. Le CODIGO_UNICO sert de clé pour suivre un projet.
4. Garde les grands projets : coût d'au moins 100 M de soles dans l'une OU l'autre archive.
5. Liste les signaux, projet par projet (voir SIGNAUX plus bas).
6. Écrit exports/changements_<ancienne>_<recente>.xlsx (fichier de travail, pas une sortie publique).

Lancement : python changements.py                          (choix automatique des deux archives)
            python changements.py 2026-11-14                (cette date, comparée à la plus récente)
            python changements.py 2026-11-14 2026-11-23     (deux dates au choix)
"""

import sys
from datetime import date, timedelta

import pandas as pd

import indicateurs as ind
from archiver import SNAP_DIR

ECART_MINIMUM_JOURS = 7
SEUIL_AVANCEMENT_POINTS = 10      # avancement physique : hausse d'au moins 10 points de %
SEUIL_PIM_SOLES = 5e6             # PIM de l'année : variation d'au moins 5 M de soles, dans un sens ou l'autre
SEUIL_COUT_RELATIF = 0.10         # coût : variation d'au moins 10 %
VARIATION_MIN_SEUIL_FRANCHI = 0.05  # un franchissement des 100 M n'est signalé que si le coût bouge d'au moins 5 %
SEUIL_RUPTURE_POINTS = 5          # rupture de format : taux de remplissage qui bouge d'au moins 5 points

# Les signaux, dans leur ordre d'affichage.
NOUVEAU = "Nouveau grand projet"
SORTI = "Ne figure plus parmi les investissements actifs"
AU_DESSUS = "Passé au-dessus de 100 M"
EN_DESSOUS = "Repassé sous 100 M"
SITUATION = "Situation changée"
EXPEDIENTE = "Expediente técnico changé"
AVANCEMENT = f"Avancement physique +{SEUIL_AVANCEMENT_POINTS} points ou plus"
PIM_HAUSSE = "PIM de l'année en hausse"
PIM_BAISSE = "PIM de l'année en baisse"
COUT_HAUSSE = f"Coût en hausse de {SEUIL_COUT_RELATIF * 100:.0f} % ou plus"
COUT_BAISSE = f"Coût en baisse de {SEUIL_COUT_RELATIF * 100:.0f} % ou plus"
MODES = "Modes de réalisation changés"
SIGNAUX = [NOUVEAU, SORTI, AU_DESSUS, EN_DESSOUS, SITUATION, EXPEDIENTE, AVANCEMENT,
           PIM_HAUSSE, PIM_BAISSE, COUT_HAUSSE, COUT_BAISSE, MODES]


# ---------------------------------------------------------------- 1 : choix des archives

def lister_archives():
    """Dictionnaire {date: chemin} des archives. La date est celle de la mise à jour du fichier par le MEF."""
    archives = {}
    for chemin in sorted(SNAP_DIR.glob("inversiones_*.parquet")):
        try:
            archives[date.fromisoformat(chemin.stem.replace("inversiones_", ""))] = chemin
        except ValueError:
            print(f"Fichier ignoré (le nom ne contient pas une date AAAA-MM-JJ) : {chemin.name}")
    return archives


def choisir_dates(dates, ancienne=None, recente=None):
    """Par défaut : la plus récente, et la plus récente qui a au moins 7 jours de moins.
    S'il n'y en a pas, la plus ancienne disponible (la comparaison portera alors sur moins de 7 jours)."""
    if len(dates) < 2:
        raise ValueError("Il faut au moins deux archives pour comparer.")
    recente = recente or max(dates)
    if ancienne is None:
        assez_vieilles = [d for d in dates if d <= recente - timedelta(days=ECART_MINIMUM_JOURS)]
        plus_vieilles = [d for d in dates if d < recente]
        if not plus_vieilles:
            raise ValueError(f"Aucune archive plus ancienne que le {recente}.")
        ancienne = max(assez_vieilles) if assez_vieilles else min(plus_vieilles)
    if ancienne >= recente:
        raise ValueError(f"L'archive ancienne ({ancienne}) doit être plus vieille que la récente ({recente}).")
    return ancienne, recente


# ---------------------------------------------------------------- 2 : ruptures de format

def taux_remplissage(df):
    """Pour chaque colonne, la part de cases remplies, en %. Un montant à 0 compte comme vide."""
    taux = {}
    for colonne in df.columns:
        serie = df[colonne]
        if pd.api.types.is_numeric_dtype(serie):
            remplie = serie.notna() & (serie != 0)
        else:
            remplie = serie.notna() & (serie.astype(str).str.strip() != "")
        taux[colonne] = 100 * remplie.mean()
    return pd.Series(taux)


def ruptures_de_format(brut_avant, brut_apres):
    """Colonnes dont le taux de remplissage bouge d'au moins SEUIL_RUPTURE_POINTS entre les deux archives.
    D'une semaine à l'autre, ces taux bougent très peu : un grand écart veut dire que le MEF a changé
    la façon de remplir la colonne (exemple réel : CTRL_CONCURR et ETAPA_F8, vidés dans les fichiers des 20 et 23/11/2026)."""
    taux = pd.DataFrame({"rempli_avant_%": taux_remplissage(brut_avant),
                         "rempli_apres_%": taux_remplissage(brut_apres)})
    taux["ecart_points"] = taux["rempli_apres_%"] - taux["rempli_avant_%"]
    ruptures = taux[taux["ecart_points"].abs() >= SEUIL_RUPTURE_POINTS]
    return ruptures.rename_axis("colonne").reset_index().round(1)


# ---------------------------------------------------------------- 3 : préparation

def preparer(df):
    """Même préparation qu'à l'étape 2, puis le CODIGO_UNICO devient l'index (la clé de comparaison).
    Les lignes sans code ne peuvent pas être suivies d'une archive à l'autre : on les retire.
    Pour un code en double, on garde la première ligne (au 25/11/2026, le seul doublon a deux lignes identiques)."""
    df, _ = ind.retirer_doublons(df)
    df = df[df["CODIGO_UNICO"].fillna("").str.strip() != ""]
    df, _ = ind.harmoniser_cout(df)
    df, _ = ind.nettoyer(df)
    return df.set_index("CODIGO_UNICO", drop=False)


# ---------------------------------------------------------------- 4 et 5 : comparaison

def en_millions(montants):
    """Montants en soles vers un texte lisible : 15425826 devient « 15.4 M »."""
    return montants.map(lambda x: f"{x / 1e6:,.1f} M".replace(",", " "))


def profil_de_sortie(projets):
    """Pourquoi un projet a pu quitter la liste des investissements actifs, d'après son dernier état connu.
    Le fichier ne le dit pas : clôture par format 9, ou désactivation (règles du MEF, qui ne visent que
    des investissements sans aucune exécution physique ni financière). Une désactivation peut être levée."""
    cloture = projets["ETAPA_F9"].isin(["Cierre", "Pendiente de liquidación"])
    jamais_execute = (projets["TIENE_F9"] == "NO") & ind.sans_budget_ni_depense(projets)
    return pd.Series(
        ["clôture probable (format 9)" if c else
         "sans budget ni dépense : désactivation probable, à vérifier dans la Consulta de Inversiones" if j else
         "motif inconnu"
         for c, j in zip(cloture, jamais_execute)], index=projets.index)


def remarques_transfert(codes, avant, apres):
    """Pour chaque code, les autres projets (de TOUT le fichier) dont le PIM a bougé du même montant exact,
    en sens inverse. C'est sans doute une modification budgétaire, mais le fichier ne le dit pas :
    - même unité exécutrice (SEC_EJEC) : réaffectation interne probable ;
    - unité différente : transfert possible, à vérifier (il passe par une norme publiée au journal officiel).
    On compare SEC_EJEC et pas ENTIDAD, car c'est l'unité exécutrice qui porte les crédits."""
    suivis = avant.index.intersection(apres.index)
    ecart = apres.loc[suivis, "PIM_ANIO_ACTUAL"] - avant.loc[suivis, "PIM_ANIO_ACTUAL"]
    remarques = {}
    for code in codes:
        contreparties = ecart.index[(ecart == -ecart[code]) & (ecart.index != code)]
        textes = []
        for autre in contreparties:
            if apres.at[autre, "SEC_EJEC"] == apres.at[code, "SEC_EJEC"]:
                textes.append(f"{autre} : même montant en sens inverse, même unité exécutrice, réaffectation interne probable")
            else:
                textes.append(f"{autre} : même montant en sens inverse, autre unité exécutrice, transfert possible à vérifier")
        remarques[code] = " ; ".join(textes)
    return pd.Series(remarques, dtype=object)


def comparer(avant, apres):
    """Compare deux archives préparées (fichier entier). Renvoie (signaux, bilan).

    signaux : une ligne par projet et par signal, avec les colonnes CODIGO_UNICO, signal, avant, apres
    (textes lisibles), ecart_M_soles (montants), ecart_points (avancement), remarque, puis le nom,
    le secteur et le coût du projet. Un même projet peut avoir plusieurs signaux.
    """
    seuil = ind.SEUIL_SOLES
    perimetre = avant.index[avant["COSTO_ACTUALIZADO"] >= seuil].union(
        apres.index[apres["COSTO_ACTUALIZADO"] >= seuil])
    gA = ind.ajouter_secteur_et_modes(avant[avant.index.isin(perimetre)])
    gB = ind.ajouter_secteur_et_modes(apres[apres.index.isin(perimetre)])

    morceaux = []

    def ajouter(codes, signal, valeur_avant=None, valeur_apres=None, ecart_M=None, ecart_points=None,
                remarque=None):
        """Ajoute une ligne par code. Les valeurs sont des colonnes (Series) indexées par code, ou None."""
        def prendre(serie, vide=None):
            return vide if serie is None else serie.reindex(codes).values
        # Colonnes de nombres : une case sans valeur est un NaN (nombre), pas un None (texte), pour que toutes les
        # lignes gardent le même type de colonne une fois rassemblées.
        morceaux.append(pd.DataFrame({
            "CODIGO_UNICO": codes, "signal": signal,
            "avant": prendre(valeur_avant), "apres": prendre(valeur_apres),
            "ecart_M_soles": prendre(ecart_M, float("nan")), "ecart_points": prendre(ecart_points, float("nan")),
            "remarque": prendre(remarque),
        }))

    # Projets présents d'un seul côté.
    nouveaux = gB.index.difference(gA.index)
    sortis = gA.index.difference(gB.index)
    ajouter(nouveaux, NOUVEAU, valeur_apres=en_millions(gB["COSTO_ACTUALIZADO"]))
    ajouter(sortis, SORTI, valeur_avant=en_millions(gA["COSTO_ACTUALIZADO"]),
            remarque=profil_de_sortie(gA.loc[sortis]))

    # Projets suivis des deux côtés : A et B sont alignés sur les mêmes codes, dans le même ordre.
    suivis = gA.index.intersection(gB.index)
    A, B = gA.loc[suivis], gB.loc[suivis]

    cout_a, cout_b = A["COSTO_ACTUALIZADO"], B["COSTO_ACTUALIZADO"]
    ecart_cout_M = (cout_b - cout_a) / 1e6
    # Variation relative, seulement si le coût d'avant est positif (sinon la division n'a pas de sens).
    variation = (cout_b / cout_a - 1).where(cout_a > 0)
    # « Pas une petite variation » : vrai aussi quand la variation est inconnue (coût d'avant à 0).
    pas_negligeable = ~(variation.abs() < VARIATION_MIN_SEUIL_FRANCHI)
    monte = (cout_a < seuil) & (cout_b >= seuil)
    descend = (cout_a >= seuil) & (cout_b < seuil)
    cout = dict(valeur_avant=en_millions(cout_a), valeur_apres=en_millions(cout_b), ecart_M=ecart_cout_M)
    ajouter(suivis[monte & pas_negligeable], AU_DESSUS, **cout)
    ajouter(suivis[descend & pas_negligeable], EN_DESSOUS, **cout)

    # Colonnes texte : une case vide des deux côtés ne doit pas compter comme un changement.
    for colonne, signal in [("SITUACION", SITUATION), ("EXPEDIENTE_TECNICO", EXPEDIENTE)]:
        texte_a, texte_b = A[colonne].fillna(""), B[colonne].fillna("")
        ajouter(suivis[texte_a != texte_b], signal, texte_a, texte_b)

    # Avancement : les valeurs impossibles ont été vidées par nettoyer(), et une case vide donne NaN
    # dans la soustraction : un projet sans avancement connu des deux côtés ne déclenche jamais ce signal.
    hausse_avancement = B["AVANCE_FISICO"] - A["AVANCE_FISICO"]
    pourcent = lambda s: s.map(lambda x: f"{x:.1f} %")
    ajouter(suivis[hausse_avancement >= SEUIL_AVANCEMENT_POINTS], AVANCEMENT,
            pourcent(A["AVANCE_FISICO"]), pourcent(B["AVANCE_FISICO"]), ecart_points=hausse_avancement)

    # PIM et devengado repartent de zéro chaque année : on ne les compare que dans la même année budgétaire.
    meme_annee = set(avant["ANIO_PROCESO"].unique()) == set(apres["ANIO_PROCESO"].unique())
    if meme_annee:
        ecart_pim = B["PIM_ANIO_ACTUAL"] - A["PIM_ANIO_ACTUAL"]
        bouge = suivis[ecart_pim.abs() >= SEUIL_PIM_SOLES]
        pim = dict(valeur_avant=en_millions(A["PIM_ANIO_ACTUAL"]), valeur_apres=en_millions(B["PIM_ANIO_ACTUAL"]),
                   ecart_M=ecart_pim / 1e6, remarque=remarques_transfert(bouge, avant, apres))
        ajouter(suivis[ecart_pim >= SEUIL_PIM_SOLES], PIM_HAUSSE, **pim)
        ajouter(suivis[ecart_pim <= -SEUIL_PIM_SOLES], PIM_BAISSE, **pim)

    ajouter(suivis[variation >= SEUIL_COUT_RELATIF], COUT_HAUSSE, **cout)
    ajouter(suivis[variation <= -SEUIL_COUT_RELATIF], COUT_BAISSE, **cout)

    # Modes : on compare des ENSEMBLES de modes normalisés, pas le texte brut. Le MEF change souvent
    # l'ordre (« DIRECTA,CONTRATA » devient « CONTRATA,DIRECTA ») sans que rien ne change vraiment.
    modes_a, modes_b = A["MODES"].map(frozenset), B["MODES"].map(frozenset)
    ajouter(suivis[modes_a != modes_b], MODES, A["MODES"].map(" + ".join), B["MODES"].map(" + ".join))

    # Les morceaux vides (aucun projet pour ce signal) sont écartés : ils ne changent rien au résultat et pandas
    # avertit qu'il les traitera autrement dans une prochaine version.
    signaux = pd.concat([m for m in morceaux if len(m)] or morceaux, ignore_index=True)
    # Nom, secteur et coût du projet, pris dans l'archive récente (dans l'ancienne pour les sortis).
    infos = pd.concat([gB, gA.loc[sortis]])[["CODIGO_UNICO", "NOMBRE_INVERSION", "SECTEUR_FICHE", "COSTO_ACTUALIZADO"]]
    signaux = signaux.merge(infos.reset_index(drop=True), on="CODIGO_UNICO", how="left")
    signaux["ordre"] = signaux["signal"].map(SIGNAUX.index)
    signaux = signaux.sort_values(["ordre", "COSTO_ACTUALIZADO"], ascending=[True, False]).drop(columns="ordre")

    non_comparable = "non comparable (années budgétaires différentes)"
    bilan = {
        "grands projets (100 M ou plus) dans l'ancienne archive": int((cout_a >= seuil).sum() + len(sortis)),
        "grands projets dans la récente": int((cout_b >= seuil).sum() + len(nouveaux)),
        "projets suivis = grands dans au moins une archive et présents dans les deux": len(suivis),
        f"franchissements du seuil non signalés (coût qui bouge de moins de {VARIATION_MIN_SEUIL_FRANCHI * 100:.0f} %)":
            int(((monte | descend) & ~pas_negligeable).sum()),
        "grands projets suivis sans avancement physique connu (archive récente)": int(B["AVANCE_FISICO"].isna().sum()),
        "variation nette du PIM de l'année (M soles, projets suivis)":
            ecart_pim.sum() / 1e6 if meme_annee else non_comparable,
        "variation nette du devengado de l'année (M soles, projets suivis)":
            (B["DEV_ANIO_ACTUAL"] - A["DEV_ANIO_ACTUAL"]).sum() / 1e6 if meme_annee else non_comparable,
        "projets distincts avec au moins un signal": int(signaux["CODIGO_UNICO"].nunique()),
    }
    return ind.pour_affichage(signaux.reset_index(drop=True)), bilan


# ---------------------------------------------------------------- 6 : écriture

def ecrire_excel(signaux, bilan, ruptures, sortie, ancienne, recente):
    resume = [("Fichier de travail", "ne pas diffuser tel quel (projets nommés, transferts, modes détaillés)"),
              ("Archive ancienne (date MEF)", str(ancienne)), ("Archive récente (date MEF)", str(recente)),
              ("Écart", f"{(recente - ancienne).days} jours"),
              ("Ruptures de format repérées", f"{len(ruptures)} colonne(s), voir l'onglet ruptures_format")]
    resume += [(cle, round(valeur, 1) if isinstance(valeur, float) else valeur) for cle, valeur in bilan.items()]
    resume += [(f"signal : {s}", int((signaux["signal"] == s).sum())) for s in SIGNAUX]
    resume = pd.DataFrame(resume, columns=["indicateur", "valeur"])

    with pd.ExcelWriter(sortie, engine="openpyxl") as xl:
        resume.to_excel(xl, sheet_name="resume", index=False)
        signaux.round(1).to_excel(xl, sheet_name="signaux", index=False)
        ruptures.to_excel(xl, sheet_name="ruptures_format", index=False)
        xl.sheets["resume"].column_dimensions["A"].width = 75
        xl.sheets["resume"].column_dimensions["B"].width = 30
        feuille = xl.sheets["signaux"]
        feuille.freeze_panes = "C2"
        feuille.auto_filter.ref = feuille.dimensions
        for lettre, largeur in zip("ABCDEFGHIJ", [12, 38, 30, 30, 14, 12, 60, 60, 34, 16]):
            feuille.column_dimensions[lettre].width = largeur
        for cellule in feuille["J"][1:]:
            cellule.number_format = "#,##0"
        xl.sheets["ruptures_format"].column_dimensions["A"].width = 28


def main(arguments):
    sys.stdout.reconfigure(encoding="utf-8")
    if len(arguments) > 2:
        raise SystemExit("Usage : python changements.py [date_ancienne] [date_recente], dates au format AAAA-MM-JJ")
    try:
        dates_donnees = [date.fromisoformat(a) for a in arguments]
    except ValueError:
        raise SystemExit("Les dates s'écrivent au format AAAA-MM-JJ, par exemple 2026-11-14.")
    archives = lister_archives()
    # 0 date : choix automatique. 1 date : l'ancienne, comparée à la plus récente. 2 dates : les deux.
    ancienne, recente = choisir_dates(list(archives), *dates_donnees)
    for d in (ancienne, recente):
        if d not in archives:
            raise SystemExit(f"Pas d'archive du {d}. Archives disponibles : {', '.join(map(str, archives))}")

    brut_avant, brut_apres = pd.read_parquet(archives[ancienne]), pd.read_parquet(archives[recente])
    ruptures = ruptures_de_format(brut_avant, brut_apres)
    signaux, bilan = comparer(preparer(brut_avant), preparer(brut_apres))

    ind.SORTIE_DIR.mkdir(exist_ok=True)
    sortie = ind.SORTIE_DIR / f"changements_{ancienne}_{recente}.xlsx"
    ecrire_excel(signaux, bilan, ruptures, sortie, ancienne, recente)

    ecart = (recente - ancienne).days
    print(f"Comparaison du {ancienne} au {recente} ({ecart} jour{'s' if ecart > 1 else ''})\n")
    if ecart < ECART_MINIMUM_JOURS:
        print(f"Attention : moins de {ECART_MINIMUM_JOURS} jours entre les deux archives (pas d'archive plus ancienne).\n")
    if len(ruptures):
        print("Attention, ruptures de format du MEF entre les deux archives :")
        print(ruptures.to_string(index=False), "\n")
    for cle, valeur in bilan.items():
        print(f"  {cle} : {round(valeur, 1) if isinstance(valeur, float) else valeur}")
    print()
    print(signaux["signal"].value_counts().reindex(SIGNAUX, fill_value=0).to_string(), "\n")
    print(f"-> {sortie}")


if __name__ == "__main__":
    main(sys.argv[1:])
