"""Étape 5 : la fiche de deux pages sur les grands projets d'investissement public au Pérou.

Ce que fait le script, dans l'ordre :
1. Calcule les indicateurs de la dernière archive (étape 2) : chiffres clés, secteurs, modes, top 15.
2. Prépare les encadrés : urgences et prévention ; ferroviaire ; niveaux de gouvernement.
3. Compare la dernière archive à celle d'au moins 7 jours avant (étape 3), et n'en garde que des totaux.
4. Reprend les consultations en cours de ProInversión (étape 4, dernier export).
5. Remplit le modèle fiche/modele.html, avec le paragraphe « Lecture » écrit à la main dans fiche/lecture.txt.
6. Imprime le PDF avec Chrome et vérifie qu'il fait exactement deux pages.

La fiche peut être montrée à l'extérieur : elle ne cite aucune entreprise en dehors des intitulés officiels du MEF,
ne classe aucune région, ne détaille pas les baisses de budget projet par projet et regroupe dans « Autres montages »
les modes autres que l'APP, les travaux contre impôts, le marché public et la régie.
Tant que fiche/lecture.txt manque ou est vide, le PDF est marqué « brouillon » et ne doit pas être diffusé.

Lancement : python fiche.py      (produit exports/fiche_<date>.html et exports/fiche_<date>.pdf)
"""

import html
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from string import Template

import pandas as pd
from pypdf import PdfReader

import changements as ch
import indicateurs as ind

DOSSIER_FICHE = Path(__file__).parent / "fiche"
MODELE = DOSSIER_FICHE / "modele.html"
LECTURE = DOSSIER_FICHE / "lecture.txt"
NOMS_COURTS = DOSSIER_FICHE / "noms_courts.csv"
NOMS_CONSULTATIONS = DOSSIER_FICHE / "noms_consultations.csv"
# Chrome sans interface imprime la fiche en PDF. On le cherche : variable CHROME, puis Linux, puis Windows.
CHROME = Path(os.environ.get("CHROME") or shutil.which("google-chrome") or shutil.which("chromium")
              or shutil.which("chromium-browser") or r"C:\Program Files\Google\Chrome\Application\chrome.exe")
LECTURE_MAX_CARACTERES = 1450  # environ 12 lignes : au-delà, la fiche risque de passer à trois pages
MOIS_FR = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre",
           "novembre", "décembre"]
PHASES_EN_COURS = ["avant le dépôt des offres", "offres reçues, en évaluation"]
SECTEUR_COURT = {"Transports et télécoms": "Transports", "Agriculture, irrigation et pêche": "Agriculture",
                 "Eau et assainissement": "Eau", "Éducation, recherche, culture et sport": "Éducation",
                 "Administration, justice et sécurité": "Administration", "Prévention des risques": "Prévention",
                 "Énergie, environnement et autres": "Énergie"}
NIVEAUX = {"GN": "Gouvernement national", "GR": "Gouvernements régionaux", "GL": "Gouvernements locaux"}


# ---------------------------------------------------------------- mise en forme

def fr(nombre, decimales=1):
    """Nombre à la française : 1385 donne « 1 385 », 724.66 donne « 724,7 ». L'espace est insécable."""
    texte = f"{nombre:,.{decimales}f}"
    return texte.replace(",", "\u00a0").replace(".", ",")


def signe(nombre, decimales=0):
    """« +100 » ou « −14 » : le signe est calculé, jamais écrit en dur."""
    return ("+" if nombre >= 0 else "\u2212") + fr(abs(nombre), decimales)


def compte(n, singulier, pluriel):
    """Accord en français : 0 et 1 prennent le singulier (« 1 nouveau projet », « 2 nouveaux projets »)."""
    return f"{fr(n, 0)} {singulier if n < 2 else pluriel}"


def e(texte):
    """Échappe un texte pour le HTML (un « & » ou un « < » dans un nom ne doit pas casser la page)."""
    return html.escape(str(texte))


def pourcentage(valeur):
    return "" if pd.isna(valeur) else f"{fr(valeur, 0)}\u00a0%"


def montant_M(soles):
    """En millions de soles, avec une décimale sous 10 M (sinon 0,47 M s'afficherait « 0 »)."""
    millions = soles / 1e6
    return fr(millions, 1 if 0 < millions < 10 else 0)


def typographie(page):
    """Espaces insécables à la française dans le corps de la page : avant « : ; % ? ! » », après « « »,
    et entre un nombre et le mot qui suit, pour éviter « 13 / coûts » coupé en fin de ligne."""
    tete, corps = page.split("<body>", 1)
    corps = re.sub(r" ([:;%?!»])", "\u00a0\\1", corps)
    corps = corps.replace("« ", "«\u00a0")
    corps = re.sub(r"(\d) (?=[a-zéèA-Z])", "\\1\u00a0", corps)
    return tete + "<body>" + corps


def ligne_tableau(cellules, total=False):
    """Une ligne de tableau HTML. Chaque cellule est (texte, classe CSS) ; la classe « n » aligne les nombres à droite."""
    tds = "".join(f'<td class="{classe}">{texte}</td>' for texte, classe in cellules)
    return f'<tr class="total">{tds}</tr>' if total else f"<tr>{tds}</tr>"


def lire_noms(chemin, cle):
    if not chemin.exists():
        return {}
    table = pd.read_csv(chemin, sep=";", dtype=str, keep_default_na=False)
    return dict(zip(table[cle], table["NOM_COURT"]))


def nom_court(code, nom, noms_courts):
    """Nom écrit à la main dans noms_courts.csv, sinon le nom du MEF coupé avant le lieu (« DISTRITO DE... »)."""
    if code in noms_courts:
        return noms_courts[code]
    coupe = re.split(r",?\s+(?:EN EL |EN LA |EN LOS )?(?:DISTRITO|PROVINCIA|DEPARTAMENTO)S?\b", nom)[0]
    # Le MEF écrit parfois « ¿ » ou « ` » à la place d'un tiret ou d'une apostrophe.
    coupe = coupe.replace("¿", "-").replace("`", "'").strip(" ,-").capitalize()
    # Au-delà de 90 caractères, on coupe au dernier mot entier.
    return (coupe[:90].rsplit(" ", 1)[0] + "...") if len(coupe) > 90 else coupe


# ---------------------------------------------------------------- page 1

def lignes_secteurs(secteurs):
    """Une ligne par secteur, avec une barre proportionnelle au coût : en foncé la part des projets qui ont un
    budget cette année ou une dépense passée, en clair la part des projets qui n'ont ni l'un ni l'autre."""
    cout_max = secteurs.loc[secteurs["SECTEUR_FICHE"] != "TOTAL", "cout_total_Md_PEN"].max()
    lignes = []
    for _, s in secteurs.iterrows():
        total = s["SECTEUR_FICHE"] == "TOTAL"
        barre = ""
        if not total:
            largeur = 100 * s["cout_total_Md_PEN"] / cout_max
            sans = 100 * s["cout_sans_budget_ni_depense_Md_PEN"] / cout_max
            barre = (f'<div class="barre"><div class="finance" style="width:{largeur - sans:.1f}%"></div>'
                     f'<div class="jamais" style="left:{largeur - sans:.1f}%;width:{sans:.1f}%"></div></div>')
        lignes.append(ligne_tableau([
            (e("Total" if total else s["SECTEUR_FICHE"]), ""), (fr(s["nb_projets"], 0), "n"),
            (fr(s["cout_total_Md_PEN"]), "n"), (barre, ""), (fr(s["PIM_annee_M_PEN"], 0), "n"),
            (pourcentage(s["taux_execution_annee_%"]), "n")], total))
    return "\n".join(lignes)


def lignes_modes(modes):
    lignes = []
    for _, m in modes.iterrows():
        total = m["MODE_PUBLIC"] == "TOTAL"
        lignes.append(ligne_tableau([
            (e("Total" if total else m["MODE_PUBLIC"]), ""), (fr(m["nb_projets"], 0), "n"),
            (fr(m["cout_total_Md_PEN"]), "n"), (pourcentage(m["part_du_cout_%"]), "n"),
            (fr(m["PIM_annee_M_PEN"], 0), "n"), (pourcentage(m["taux_execution_annee_%"]), "n")], total))
    return "\n".join(lignes)


def lecture():
    """Le paragraphe « Lecture » est écrit à la main dans fiche/lecture.txt (une ligne vide entre deux paragraphes).
    Renvoie (html, vide) : vide = True tant que rien n'est écrit."""
    texte = LECTURE.read_text(encoding="utf-8").strip() if LECTURE.exists() else ""
    if not texte:
        return '<div class="lecture vide">Brouillon : la lecture reste à écrire dans fiche/lecture.txt.</div>', True
    if len(texte) > LECTURE_MAX_CARACTERES:
        print(f"Attention : lecture de {len(texte)} caractères (conseil : {LECTURE_MAX_CARACTERES} au plus).")
    paragraphes = [p.strip() for p in texte.split("\n\n") if p.strip()]
    return '<div class="lecture">' + "".join(f"<p>{e(p)}</p>" for p in paragraphes) + "</div>", False


def execution(g):
    """Taux d'exécution d'un groupe : somme des devengados / somme des PIM, sur les projets qui ont un PIM."""
    avec_pim = g[g["PIM_ANIO_ACTUAL"] > 0]
    pim = avec_pim["PIM_ANIO_ACTUAL"].sum()
    return 100 * avec_pim["DEV_ANIO_ACTUAL"].sum() / pim if pim > 0 else float("nan")


def encadre_urgences(df_complet, grands, jour):
    """Trois mesures, sur tout le fichier pour les deux premières (quel que soit le montant) :
    - IOARR d'urgence approuvées cette année. Celles approuvées dans le mois en cours ne peuvent pas encore être
      exécutées : on donne leur budget à part, et le taux d'exécution des autres ;
    - interventions de reconstruction (IRI) du Plan intégral de reconstruction (loi 30556 de 2017) ;
    - grands projets du secteur « Prévention des risques » (surtout des protections contre les crues)."""
    annee = jour.year
    viabilite = df_complet["FECHA_VIABILIDAD"].fillna("").astype(str)
    ioarr = df_complet[(df_complet["IND_IOARR_EMERG"] == "SI") & (viabilite.str[:4] == str(annee))]
    du_mois = ioarr[viabilite.loc[ioarr.index].str[:7] == f"{annee}-{jour.month:02d}"]
    avant_le_mois = ioarr.drop(du_mois.index)
    iri = df_complet[df_complet["TIPO_INVERSION"] == "INTERVENCIONES IRI"]
    prevention = grands[grands["SECTEUR_FICHE"] == "Prévention des risques"]
    mois = MOIS_FR[jour.month - 1]
    return (
        '<p class="petit">Les deux premières lignes couvrent tous les investissements du fichier, quel que soit leur montant.</p><ul>'
        f"<li><b>IOARR d'urgence approuvées en {annee}</b> : {fr(len(ioarr), 0)}, pour {fr(ioarr['COSTO_ACTUALIZADO'].sum() / 1e9)} Md S/ "
        f"(petits investissements de remise en état, approuvés en zone d'état d'urgence déclaré) ; "
        f"budget {annee} : {fr(ioarr['PIM_ANIO_ACTUAL'].sum() / 1e6, 0)} M S/, dont {fr(du_mois['PIM_ANIO_ACTUAL'].sum() / 1e6, 0)} M S/ "
        f"pour des IOARR approuvées en {mois}, pas encore exécutées ; les autres sont exécutées à {pourcentage(execution(avant_le_mois))}.</li>"
        f"<li><b>Reconstruction (IRI)</b> : interventions du Plan intégral de reconstruction (loi 30556 de 2017). "
        f"{fr(len(iri), 0)} figurent encore parmi les investissements actifs ({fr(iri['COSTO_ACTUALIZADO'].sum() / 1e9)} Md S/), "
        f"dont {fr((iri['PIM_ANIO_ACTUAL'] > 0).sum(), 0)} avec un budget {annee} : {fr(iri['PIM_ANIO_ACTUAL'].sum() / 1e6, 0)} M S/, "
        f"exécuté à {pourcentage(execution(iri))}.</li>"
        f"<li><b>Prévention des risques</b>, grands projets (surtout des protections contre les crues) : "
        f"{compte(len(prevention), 'projet', 'projets')}, {fr(prevention['COSTO_ACTUALIZADO'].sum() / 1e9)} Md S/ ; "
        f"budget {annee} : {fr(prevention['PIM_ANIO_ACTUAL'].sum() / 1e6, 0)} M S/, exécuté à {pourcentage(execution(prevention))}.</li></ul>")


# ---------------------------------------------------------------- page 2

def budget_ou_depense(projet):
    """« oui » si le projet a un budget cette année ou une dépense passée (crédits publics seulement)."""
    return "non" if ind.sans_budget_ni_depense(projet.to_frame().T).iloc[0] else "oui"


def stade(projet):
    """Situation courte : « viable, ET non » = déclaré viable, sans expediente técnico (ET) enregistré."""
    situation = {"VIABLE": "viable", "APROBADO": "approuvé", "EN FORMULACION": "en formulation"}.get(
        projet["SITUACION"], projet["SITUACION"].lower())
    return f"{situation}, ET {'oui' if projet['EXPEDIENTE_TECNICO'] == 'SI' else 'non'}"


def et(projet):
    """La colonne ET du top 15 : « oui » si l'expediente técnico est enregistré. Si un projet n'est pas
    « viable », on l'écrit aussi (par exemple « approuvé, ET non »)."""
    return ("oui" if projet["EXPEDIENTE_TECNICO"] == "SI" else "non") if projet["SITUACION"] == "VIABLE" else stade(projet)


def lignes_top(grands, noms_courts):
    lignes = []
    for _, p in grands.head(15).iterrows():
        lignes.append(ligne_tableau([
            (e(p["CODIGO_UNICO"]), "code"), (e(nom_court(p["CODIGO_UNICO"], p["NOMBRE_INVERSION"], noms_courts)), ""),
            (e(SECTEUR_COURT.get(p["SECTEUR_FICHE"], p["SECTEUR_FICHE"])), ""), (e(et(p)), "nw"),
            (fr(p["COSTO_ACTUALIZADO"] / 1e9), "n"), (montant_M(p["PIM_ANIO_ACTUAL"]), "n"), (budget_ou_depense(p), "")]))
    return "\n".join(lignes)


def projets_ferroviaires(grands):
    """Trains et métros : typologie « ferroviaire » ou « métro » du MEF, ou nom « ... del Metro de Lima » (sauf la
    voirie urbaine, comme une correspondance avec une station). On ne cherche pas le mot FERROCARRIL seul : il
    attraperait une avenue (Av. Ferrocarril, Huancayo)."""
    typologie = grands["DES_TIPOLOGIA"].fillna("")
    par_type = typologie.str.contains("FERROVIARIO|METRO")
    par_nom = grands["NOMBRE_INVERSION"].str.contains("DEL METRO DE LIMA") & (typologie != "VIAS URBANAS")
    return grands[par_type | par_nom]


def encadre_rail(grands, noms_courts, annee):
    rail = projets_ferroviaires(grands)
    cout, total = rail["COSTO_ACTUALIZADO"].sum(), grands["COSTO_ACTUALIZADO"].sum()
    pim = rail["PIM_ANIO_ACTUAL"].sum()
    texte = (f"<p>{compte(len(rail), 'grand projet', 'grands projets')} : {fr(cout / 1e9)} Md S/ de coût indicatif, "
             f"soit {fr(100 * cout / total, 0)}\u00a0% du total ; budget {annee} : {fr(pim / 1e6, 0)} M S/.")
    if len(rail) and pim > 0:
        plus_gros = rail.loc[rail["PIM_ANIO_ACTUAL"].idxmax()]
        nom = nom_court(plus_gros["CODIGO_UNICO"], plus_gros["NOMBRE_INVERSION"], noms_courts)
        # Seule la première lettre passe en minuscule (« Ligne 2 » devient « ligne 2 », Lima garde sa majuscule).
        texte += (f" La {e(nom[:1].lower() + nom[1:])} "
                  f"concentre {fr(100 * plus_gros['PIM_ANIO_ACTUAL'] / pim, 0)}\u00a0% de ce budget.")
    texte += "</p>"
    # Les projets du top 15 sont déjà détaillés au-dessus : on ne liste que les autres.
    hors_top = rail[~rail["CODIGO_UNICO"].isin(grands.head(15)["CODIGO_UNICO"])]
    if len(hors_top):
        liste = ", ".join(f"{e(nom_court(p['CODIGO_UNICO'], p['NOMBRE_INVERSION'], noms_courts))} "
                          f"({fr(p['COSTO_ACTUALIZADO'] / 1e9)} Md S/)" for _, p in hors_top.iterrows())
        texte += f'<p class="petit">Hors top 15 : {liste}.</p>'
    return texte


def encadre_niveaux(grands, annee):
    """Répartition par niveau de gouvernement (colonne NIVEL du MEF), sans classer aucune région."""
    lignes = []
    for code, nom in NIVEAUX.items():
        g = grands[grands["NIVEL"] == code]
        lignes.append(ligne_tableau([(nom, ""), (fr(len(g), 0), "n"), (fr(g["COSTO_ACTUALIZADO"].sum() / 1e9), "n"),
                                     (fr(g["PIM_ANIO_ACTUAL"].sum() / 1e6, 0), "n"), (pourcentage(execution(g)), "n")]))
    return (f'<table class="petit"><tr><th>Niveau</th><th class="n">Projets</th><th class="n">Md S/</th>'
            f'<th class="n">Budget {annee}</th><th class="n">Exécuté</th></tr>{"".join(lignes)}</table>')


def encadre_changements(signaux, bilan, rupture, avant, apres):
    """Seulement des totaux : aucune baisse de budget ni sortie n'est détaillée projet par projet.
    Le motif d'une sortie n'est pas dans le fichier : on ne l'écrit pas."""
    n = signaux["signal"].value_counts()
    pim = bilan["variation nette du PIM de l'année (M soles, projets suivis)"]
    dev = bilan["variation nette du devengado de l'année (M soles, projets suivis)"]
    flux = (f"Grands projets : {fr(avant, 0)} au début, {fr(apres, 0)} à la fin "
            f"({compte(n.get(ch.NOUVEAU, 0), 'entré', 'entrés')} dans le fichier, "
            f"{compte(n.get(ch.AU_DESSUS, 0), 'passé', 'passés')} au-dessus de 100 M S/, "
            f"{compte(n.get(ch.SORTI, 0), 'qui ne figure plus', 'qui ne figurent plus')} parmi les investissements actifs, "
            f"{compte(n.get(ch.EN_DESSOUS, 0), 'repassé', 'repassés')} sous le seuil).")
    montants = (f" Sur les projets présents aux deux dates : budget de l'année {signe(pim)} M S/, "
                f"dépense exécutée (devengado) {signe(dev)} M S/." if isinstance(pim, float)
                else " Budgets : années différentes, non comparés.")
    hausses, baisses = n.get(ch.COUT_HAUSSE, 0), n.get(ch.COUT_BAISSE, 0)
    autres = (f" {compte(n.get(ch.AVANCEMENT, 0), 'projet gagne', 'projets gagnent')} au moins {ch.SEUIL_AVANCEMENT_POINTS} points d'avancement "
              f"physique ; {compte(hausses + baisses, 'coût est réévalué', 'coûts sont réévalués')} d'au moins {ch.SEUIL_COUT_RELATIF * 100:.0f} % "
              f"({fr(hausses, 0)} à la hausse, {fr(baisses, 0)} à la baisse).")
    note = (' <span class="petit">Le MEF a changé le format de son fichier pendant la période : les coûts ont été harmonisés.</span>'
            if rupture else "")
    return f"<p>{flux}{montants}{autres}{note}</p>"


def derniere_consultation_proinversion():
    exports = sorted(ind.SORTIE_DIR.glob("proinversion_*.xlsx"))
    if not exports:
        return None, None
    jour = exports[-1].stem.replace("proinversion_", "")
    return pd.read_excel(exports[-1], sheet_name="non_closes", dtype={"projets_mef": str}), jour


def encadre_proinversion(non_closes, jour, noms_consultations):
    if non_closes is None:
        return "<p>Lancer d'abord proinversion.py.</p>"
    en_cours = non_closes[non_closes["phase_d_apres_les_documents"].isin(PHASES_EN_COURS)]
    noms = [noms_consultations.get(str(c.id), c.titre) for c in en_cours.itertuples()]
    return ("<p>ProInversión, l'agence de promotion de l'investissement privé, sélectionne des consultants pour préparer "
            f"ses projets. Le {pd.Timestamp(jour):%d/%m/%Y}, {compte(len(en_cours), 'consultation est', 'consultations sont')} "
            f"en cours d'après les documents publiés : {e(', '.join(noms))}. "
            "Ce sont des marchés de conseil, pas les appels d'offres des APP.</p>")


# ---------------------------------------------------------------- impression

def imprimer(page_html, pdf):
    if not CHROME.exists():
        raise SystemExit(f"Chrome introuvable ({CHROME}) : installer Google Chrome ou donner son chemin dans la "
                         "variable d'environnement CHROME.")
    subprocess.run([str(CHROME), "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
                    f"--print-to-pdf={pdf}", page_html.resolve().as_uri()], check=True, capture_output=True, timeout=90)
    pages = len(PdfReader(pdf).pages)
    if pages != 2:
        raise SystemExit(f"La fiche fait {pages} pages au lieu de deux : raccourcir la lecture ou un encadré.")


def rupture_entre(archives, ancienne, recente):
    """Vrai si le MEF a changé le format de son fichier entre deux dates. On compare chaque archive à la suivante :
    un aller-retour (format changé puis rétabli) serait invisible en ne regardant que les deux extrémités."""
    dates = [d for d in sorted(archives) if ancienne <= d <= recente]
    for avant, apres in zip(dates, dates[1:]):
        if len(ch.ruptures_de_format(pd.read_parquet(archives[avant]), pd.read_parquet(archives[apres]))):
            return True
    return False


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    archives = ch.lister_archives()
    recente = max(archives)
    annee = recente.year
    info_taux = ind.taux_change(annee)
    brut = pd.read_parquet(archives[recente])
    res = ind.calculer(brut, info_taux["soles_par_dollar"])
    grands, secteurs = res["grands"], res["secteurs"]
    total = secteurs[secteurs["SECTEUR_FICHE"] == "TOTAL"].iloc[0]
    df_complet, _ = ind.harmoniser_cout(ind.retirer_doublons(brut)[0])
    noms_courts = lire_noms(NOMS_COURTS, "CODIGO_UNICO")

    ancienne, _ = ch.choisir_dates(list(archives), recente=recente)
    signaux, bilan = ch.comparer(ch.preparer(pd.read_parquet(archives[ancienne])), ch.preparer(brut))
    non_closes, jour_proinversion = derniere_consultation_proinversion()
    texte_lecture, brouillon = lecture()

    valeurs = {
        "mois": f"{MOIS_FR[recente.month - 1]} {annee}",
        "annee": annee,
        "mention_brouillon": ' <span class="brouillon">BROUILLON, ne pas diffuser</span>' if brouillon else "",
        "date_donnees": f"{recente:%d/%m/%Y}", "date_donnees_court": f"{recente:%d/%m}",
        "taux": fr(info_taux["soles_par_dollar"], 3), "periode_taux": info_taux["periode"],
        "nb_projets": fr(total["nb_projets"], 0),
        "cout_total": fr(total["cout_total_Md_PEN"], 0), "cout_usd": fr(total["cout_total_Md_USD"], 0),
        "part_jamais": fr(100 * total["cout_sans_budget_ni_depense_Md_PEN"] / total["cout_total_Md_PEN"], 0),
        "nb_jamais": fr(total["nb_sans_budget_ni_depense"], 0),
        "pim": fr(total["PIM_annee_M_PEN"] / 1000), "taux_exec": fr(total["taux_execution_annee_%"], 0),
        "part_pim": fr(100 * total["PIM_annee_M_PEN"] * 1e6 / df_complet["PIM_ANIO_ACTUAL"].sum(), 0),
        "lecture": texte_lecture,
        "lignes_secteurs": lignes_secteurs(secteurs), "lignes_modes": lignes_modes(res["modes_public"]),
        "encadre_urgences": encadre_urgences(df_complet, grands, recente),
        "lignes_top": lignes_top(grands, noms_courts),
        "note_viables": "Tous ces projets sont déclarés viables." if (grands.head(15)["SITUACION"] == "VIABLE").all() else "",
        "encadre_rail": encadre_rail(grands, noms_courts, annee),
        "encadre_niveaux": encadre_niveaux(grands, annee),
        "date_ancienne": f"{ancienne:%d/%m}", "date_recente": f"{recente:%d/%m/%Y}",
        "encadre_changements": encadre_changements(
            signaux, bilan, rupture_entre(archives, ancienne, recente),
            avant=bilan["grands projets (100 M ou plus) dans l'ancienne archive"],
            apres=bilan["grands projets dans la récente"]),
        "encadre_proinversion": encadre_proinversion(non_closes, jour_proinversion, lire_noms(NOMS_CONSULTATIONS, "ID_PROINVERSION")),
        "date_proinversion": (pd.Timestamp(jour_proinversion).strftime("%d/%m/%Y") if jour_proinversion else "non consulté"),
    }
    page = typographie(Template(MODELE.read_text(encoding="utf-8")).substitute(valeurs))

    ind.SORTIE_DIR.mkdir(exist_ok=True)
    nom = f"fiche_{recente.isoformat()}" + ("_brouillon" if brouillon else "")
    sortie_html, sortie_pdf = ind.SORTIE_DIR / f"{nom}.html", ind.SORTIE_DIR / f"{nom}.pdf"
    sortie_html.write_text(page, encoding="utf-8")
    imprimer(sortie_html, sortie_pdf)
    if brouillon:
        print("Attention : fiche/lecture.txt est absent ou vide, le PDF est un brouillon (ne pas le diffuser).")
    print(f"Fiche des données MEF du {recente:%d/%m/%Y} (comparaison avec le {ancienne:%d/%m/%Y}) -> {sortie_pdf}")


if __name__ == "__main__":
    main()
