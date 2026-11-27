"""Étape 5 : la note de deux pages sur les grands projets d'investissement public au Pérou.

Pour qui : une entreprise (ingénierie, travaux, équipements) qui veut savoir, en deux pages, quels grands projets
publics existent, à quel stade ils sont, dans quels secteurs, par quel montage, et lesquels suivre.

La forme suit les règles observées dans des notes publiées par des cabinets de conseil et des institutions
(Banque mondiale, OCDE, FMI, McKinsey, BCG) :
- chaque titre est un message : une phrase, un constat chiffré, recalculé à chaque lancement (aucun chiffre en dur) ;
- les graphiques sont numérotés, avec une note et une source dessous ; une couleur par stade, la même partout ;
- une seule interprétation : le texte « À retenir », écrit à la main dans fiche/lecture.txt.

Ce que fait le script, dans l'ordre :
1. Calcule les indicateurs de la dernière archive (étape 2) et classe chaque grand projet par stade
   (avant exécution, études détaillées, travaux, clôture) d'après les phases déclarées au MEF.
2. Calcule les chiffres de chaque bloc, puis écrit les titres à partir de ces chiffres.
3. Dessine les graphiques en SVG (du texte, pas des images : ils restent nets à l'impression).
4. Remplit fiche/modele.html, contrôle le texte (noms bruts du MEF, valeurs non calculées, titres qui jugent),
   imprime le PDF avec Chrome et vérifie qu'il fait exactement deux pages.

La note peut être montrée à l'extérieur : elle ne cite aucune entreprise en dehors des intitulés officiels du MEF,
ne classe aucune région et ne parle pas de politique intérieure.
Tant que fiche/lecture.txt manque ou est vide, le PDF est marqué « brouillon » et ne doit pas être diffusé.

Lancement : python fiche.py      (produit exports/fiche_<date>.html et exports/fiche_<date>.pdf)
"""

import html
import os
import re
import shutil
import subprocess
import sys
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from string import Template

import numpy as np
import pandas as pd
from pypdf import PdfReader

import indicateurs as ind
import changements as ch

DOSSIER_FICHE = Path(__file__).parent / "fiche"
MODELE = DOSSIER_FICHE / "modele.html"
LECTURE = DOSSIER_FICHE / "lecture.txt"
NOMS_COURTS = DOSSIER_FICHE / "noms_courts.csv"
NOMS_CONSULTATIONS = DOSSIER_FICHE / "noms_consultations.csv"
# Chrome sans interface imprime la fiche en PDF. On le cherche : variable CHROME, puis Linux, puis Windows.
CHROME = Path(os.environ.get("CHROME") or shutil.which("google-chrome") or shutil.which("chromium")
              or shutil.which("chromium-browser") or r"C:\Program Files\Google\Chrome\Application\chrome.exe")
LECTURE_MAX_CARACTERES = 900  # la zone « À retenir » a une hauteur fixe
C = "COSTO_ACTUALIZADO"
PIM = "PIM_ANIO_ACTUAL"
MOIS_FR = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre",
           "novembre", "décembre"]
PHASES_EN_COURS = ["avant le dépôt des offres", "offres reçues, en évaluation"]
SECTEUR_COURT = {"Transports et télécoms": "Transports", "Agriculture, irrigation et pêche": "Agriculture",
                 "Eau et assainissement": "Eau", "Éducation, recherche, culture et sport": "Éducation",
                 "Administration, justice et sécurité": "Administration", "Prévention des risques": "Prévention",
                 "Énergie, environnement et autres": "Énergie"}
NIVEAUX = {"GN": "Gouvernement national", "GR": "Gouvernements régionaux", "GL": "Gouvernements locaux"}

# ---------------------------------------------------------------- stades et couleurs

AVANT, ETUDES, TRAVAUX, CLOTURE = "Avant exécution", "Études détaillées", "Travaux", "Clôture"
STADES = [AVANT, ETUDES, TRAVAUX, CLOTURE]
# Bleus : pas encore en travaux (le message de la note) ; gris : travaux et clôture. Distincts aussi en noir et blanc.
COULEUR_STADE = {AVANT: "#A9C4DE", ETUDES: "#1F4E79", TRAVAUX: "#737373", CLOTURE: "#D0D0D0"}
TEXTE_SUR_STADE = {AVANT: "#1A1A1A", ETUDES: "#FFFFFF", TRAVAUX: "#FFFFFF", CLOTURE: "#1A1A1A"}
OCRE, OCRE_TEXTE, GRIS_COUT = "#B5651D", "#8F4E14", "#9A9A9A"
# Au-delà de cette part de projets sans phase, le fichier a sans doute été publié sans la colonne (cas réel :
# fichiers des 20 et 23/11/2026, où ETAPA_F8 était vide partout). D'habitude, environ 10 % des grands projets.
PART_MAX_SANS_PHASE = 0.5

# Les modes de réalisation, avec ce qu'ils veulent dire pour une entreprise (une ligne).
MODES = {
    "Marché public (por contrata)": ("Marché public", "l'administration met des entreprises en concurrence"),
    "APP": ("PPP", "un opérateur privé construit et exploite l'ouvrage"),
    ind.AUTRES_MONTAGES: ("Autres montages", "surtout des accords d'État à État"),
    "Régie (administration directe)": ("Régie", "l'administration réalise elle-même l'ouvrage"),
    "Travaux contre impôts (OxI)": ("Travaux contre impôts", "une entreprise finance l'ouvrage contre un crédit d'impôt"),
    ind.NON_RENSEIGNE: ("Non renseigné", "mode absent du fichier"),
}

# Mots qui feraient d'un titre un jugement : un titre ne dit que des faits.
MOTS_DE_JUGEMENT = ["seulement", "à peine", "retard", "bloqué", "opportunité", "dynamique", "faible", "fort ",
                    "record", "dérive", "glissement", "inquiétant", "malheureusement", "excellent"]
# Noms bruts du MEF qui doivent avoir été raccourcis avant impression.
NOMS_BRUTS = [("DEPARTAMENTO", "nom brut du MEF non raccourci")]


# ---------------------------------------------------------------- mise en forme

def fr(nombre, decimales=1):
    """Nombre à la française : 1385 donne « 1 385 », 724.66 donne « 724,7 ». L'espace est insécable.
    Arrondi commercial : 726,5 donne 727 (Python seul arrondirait au chiffre pair, 726)."""
    if pd.notna(nombre):
        nombre = Decimal(str(nombre)).quantize(Decimal(1).scaleb(-decimales), rounding=ROUND_HALF_UP)
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


def pc(part):
    """Une part (0,581) en pourcentage pour le texte : « 58 % » ; « 0,2 % » sous 1 % (jamais « 0 % »)."""
    valeur = 100 * part
    if 0 < valeur < 1:
        return f"{fr(valeur, 1)}\u00a0%"
    return f"{fr(valeur, 0)}\u00a0%"


def md(soles):
    """Milliards de soles pour le texte : entier au-delà de 100 (« 727 »), une décimale en dessous (« 20,9 »)."""
    milliards = soles / 1e9
    return fr(milliards, 0 if milliards >= 100 else 1)


def montant_M(soles):
    """En millions de soles, avec une décimale sous 10 M (sinon 0,47 M s'afficherait « 0 »)."""
    millions = soles / 1e6
    return fr(millions, 1 if 0 < millions < 10 else 0)


def millions_entiers(soles):
    """Colonnes de tableau en M S/ : toujours des entiers (alignés), « <1 » pour une valeur non nulle sous 1 M,
    « n.d. » si la valeur est absente du fichier."""
    if pd.isna(soles):
        return "n.d."
    millions = soles / 1e6
    return "&lt;1" if 0 < millions < 0.5 else fr(millions, 0)


def typographie(page):
    """Espaces insécables à la française dans le corps de la page : avant « : ; % ? ! » », après « « »,
    et entre un nombre et le mot qui suit, pour éviter « 13 / coûts » coupé en fin de ligne."""
    tete, corps = page.split("<body>", 1)

    def texte(m):
        t = re.sub(r" ([:;%?!»])", "\u00a0\\1", m.group(0))
        t = t.replace("« ", "«\u00a0").replace(" S/", "\u00a0S/")
        return re.sub(r"(\d) (?=[a-zéèA-Z])", "\\1\u00a0", t)

    # Seulement le texte entre les balises : dans un attribut SVG (d="M1,5 L2,4"), une espace insécable casse le tracé.
    corps = re.sub(r">[^<]+<", texte, corps)
    return tete + "<body>" + corps


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


def execution(g):
    """Part du budget de l'année déjà dépensée : somme des devengados / somme des PIM, sur les projets qui ont un PIM."""
    avec_pim = g[g[PIM] > 0]
    total = avec_pim[PIM].sum()
    return avec_pim["DEV_ANIO_ACTUAL"].sum() / total if total > 0 else float("nan")


def budget_ou_depense(projet):
    """« oui » si le projet a un budget cette année ou une dépense passée (crédits publics seulement).
    Utilisé par la carte (cercle plein ou creux)."""
    return "non" if ind.sans_budget_ni_depense(projet.to_frame().T).iloc[0] else "oui"


# ---------------------------------------------------------------- stade d'un projet

def stade(projet):
    """Le stade d'un projet, d'après les phases qu'il a déclarées au MEF (formatos 8 et 9 d'Invierte.pe) :
    - rapport de fin des travaux enregistré (formato 9, « en attente de liquidation ») : Clôture ;
    - phase d'exécution en partie C (« ejecución física ») : Travaux. La partie C s'ouvre quand les études
      détaillées sont validées : le chantier peut être lancé, en cours, ou presque fini. Un formato 9 encore
      « en attente de fin des travaux » reste en Travaux ;
    - phase d'exécution ouverte, parties A ou B (études détaillées, terrains) : Études détaillées ;
    - pas de formato 8 : Avant exécution (projet approuvé, phase d'exécution pas encore ouverte)."""
    cloture = str(projet.get("ETAPA_F9") or "").strip()
    if cloture and "Culminación" not in cloture:
        return CLOTURE
    phase = str(projet.get("ETAPA_F8") or "").strip()
    if phase.startswith("Ejecución física") or cloture:
        return TRAVAUX
    return ETUDES if phase else AVANT


def verifier_phases(grands):
    """Arrête le script si la colonne des phases semble vide pour tout le fichier : les stades seraient faux."""
    sans_phase = (grands["ETAPA_F8"].fillna("").str.strip() == "").mean()
    if sans_phase > PART_MAX_SANS_PHASE:
        raise SystemExit(f"{sans_phase:.0%} des grands projets n'ont pas de phase (ETAPA_F8) : le MEF a sans doute "
                         "publié ce fichier sans cette colonne. Attendre le fichier suivant.")


def preparer(grands):
    """Ajoute à chaque grand projet son stade, « pas encore en travaux » et « sans aucun crédit public »."""
    verifier_phases(grands)
    g = grands.copy()
    g["STADE"] = g.apply(stade, axis=1)
    g["PRE"] = g["STADE"].isin([AVANT, ETUDES])
    g["SANS"] = ind.sans_budget_ni_depense(g)
    return g


# ---------------------------------------------------------------- petits éléments graphiques

def carre(couleur, taille=2.2):
    return (f'<span class="carre" style="background:{couleur};width:{taille}mm;height:{taille}mm"></span>')


def cle_stades(effectifs=None):
    """Légende des stades (« Avant exécution (145) »), sur une ligne."""
    morceaux = []
    for s in STADES:
        n = f" ({fr(effectifs[s], 0)})" if effectifs is not None else ""
        morceaux.append(f'<span class="cle-item">{carre(COULEUR_STADE[s])}{e(s)}{n}</span>')
    return '<div class="cle">' + "".join(morceaux) + "</div>"


def svg(largeur, hauteur, contenu):
    return (f'<svg class="graphique" width="{largeur}mm" height="{hauteur}mm" viewBox="0 0 {largeur} {hauteur}" '
            f'xmlns="http://www.w3.org/2000/svg">{contenu}</svg>')


def texte_svg(x, y, contenu, taille=2.5, couleur="#1A1A1A", ancre="start", gras=False):
    poids = ' font-weight="600"' if gras else ""
    return (f'<text x="{x:.2f}" y="{y:.2f}" font-size="{taille}" fill="{couleur}" text-anchor="{ancre}"{poids}>'
            f"{e(contenu)}</text>")


def rect(x, y, l, h, couleur, bord=True):
    trait = ' stroke="#FFFFFF" stroke-width="0.15"' if bord else ""
    return f'<rect x="{x:.2f}" y="{y:.2f}" width="{max(l, 0):.2f}" height="{h:.2f}" fill="{couleur}"{trait}/>'


# ---------------------------------------------------------------- page 1

def chiffres_par_stade(g):
    s = g.groupby("STADE").agg(n=(C, "size"), cout=(C, "sum"), pim=(PIM, "sum")).reindex(STADES).fillna(0)
    s["pc"] = s["cout"] / s["cout"].sum()
    s["pp"] = s["pim"] / s["pim"].sum()
    return s


def graphique_stades(s, annee):
    """Graphique 1 : deux barres à 100 % (coût prévu, budget de l'année), segments par stade, reliées par les
    segments « Travaux » ; accolade sur la part « pas encore en travaux »."""
    L, x0, larg = 186, 36, 150
    y_cout, y_pim, h = 7.5, 21.5, 7
    contenu = []
    pre_cout = s.loc[[AVANT, ETUDES], "pc"].sum()
    pre_pim = s.loc[[AVANT, ETUDES], "pp"].sum()
    # Accolade au-dessus de la part « pas encore en travaux » de la barre du coût.
    xa = x0 + larg * pre_cout
    contenu.append(f'<path d="M{x0:.2f},5.6L{x0:.2f},4.4L{xa:.2f},4.4L{xa:.2f},5.6" fill="none" stroke="#1F4E79" stroke-width="0.25"/>')
    contenu.append(texte_svg(x0, 3.2, f"Pas encore en travaux : {pc(pre_cout)} du coût ({md(s.loc[[AVANT, ETUDES], 'cout'].sum())} Md S/), "
                                      f"{pc(pre_pim)} du budget {annee}", 2.45, "#1F4E79", gras=True))
    # Libellés à gauche.
    contenu.append(texte_svg(0, y_cout + 3.1, "Coût prévu", 2.55, gras=True))
    contenu.append(texte_svg(0, y_cout + 6.1, f"{md(s['cout'].sum())} Md S/", 2.4, "#6B6B6B"))
    contenu.append(texte_svg(0, y_pim + 3.1, f"Budget {annee}", 2.55, gras=True))
    contenu.append(texte_svg(0, y_pim + 6.1, f"{md(s['pim'].sum())} Md S/", 2.4, OCRE_TEXTE))
    # Bande de liaison entre les segments « Travaux » des deux barres.
    debut_c, debut_p = s["pc"].cumsum().shift(fill_value=0), s["pp"].cumsum().shift(fill_value=0)
    a1, a2 = x0 + larg * debut_c[TRAVAUX], x0 + larg * (debut_c[TRAVAUX] + s.loc[TRAVAUX, "pc"])
    b1, b2 = x0 + larg * debut_p[TRAVAUX], x0 + larg * (debut_p[TRAVAUX] + s.loc[TRAVAUX, "pp"])
    contenu.append(f'<polygon points="{a1:.2f},{y_cout + h} {a2:.2f},{y_cout + h} {b2:.2f},{y_pim} {b1:.2f},{y_pim}" fill="#EDEDED"/>')
    # Les deux barres, avec les étiquettes dans les segments assez larges, dehors sinon.
    for y, col, debut, dehors_y in [(y_cout, "pc", debut_c, y_cout - 1.0), (y_pim, "pp", debut_p, y_pim + h + 2.8)]:
        for st in STADES:
            x, l = x0 + larg * debut[st], larg * s.loc[st, col]
            contenu.append(rect(x, y, l, h, COULEUR_STADE[st]))
            if l >= 12:
                contenu.append(texte_svg(x + l / 2, y + h / 2 + 0.9, pc(s.loc[st, col]), 2.5, TEXTE_SUR_STADE[st], "middle", True))
            elif s.loc[st, col] > 0:
                milieu = x + l / 2
                # Le petit segment du début est étiqueté à gauche de son milieu, celui de la fin à droite.
                ancre = "start" if milieu < x0 + larg / 2 else "end"
                cible = milieu - 0.6 if ancre == "end" else milieu + 0.6
                bord = y if dehors_y < y else y + h
                contenu.append(f'<line x1="{milieu:.2f}" y1="{bord:.2f}" x2="{milieu:.2f}" y2="{dehors_y + (0.6 if dehors_y < y else -2.2):.2f}" stroke="#A6A6A6" stroke-width="0.2"/>')
                contenu.append(texte_svg(cible, dehors_y, f"{st} : {pc(s.loc[st, col])}", 2.2, "#4D4D4D", ancre))
    return svg(L, 33, "".join(contenu))


def barre_empilee(valeurs, echelle, largeur, hauteur=3.4, total=None):
    """Une barre horizontale empilée par stade (valeurs en Md S/), suivie du total."""
    x, contenu = 0.0, []
    for st in STADES:
        l = valeurs.get(st, 0) * echelle
        contenu.append(rect(x, 0.3, l, hauteur, COULEUR_STADE[st]))
        x += l
    if total is not None:
        contenu.append(texte_svg(x + 1.2, 0.3 + hauteur / 2 + 0.85, total, 2.45, "#1A1A1A", gras=True))
    return svg(largeur, hauteur + 0.6, "".join(contenu))


def croisement(g, colonne, ordre=None):
    """Coût par stade (Md S/), nombre de projets, part pas encore en travaux, budget et part du budget,
    pour chaque valeur de `colonne`."""
    x = pd.crosstab(g[colonne], g["STADE"], values=g[C], aggfunc="sum").reindex(columns=STADES).fillna(0) / 1e9
    x["total"] = x[STADES].sum(axis=1)
    x["n"] = g.groupby(colonne).size()
    x["pre"] = (x[AVANT] + x[ETUDES]) / x["total"]
    x["pim"] = g.groupby(colonne)[PIM].sum()
    x["pp"] = x["pim"] / g[PIM].sum()
    x["pc"] = x["total"] / x["total"].sum()
    if ordre:
        return x.reindex([o for o in ordre if o in x.index])
    return x.sort_values("total", ascending=False)


def lignes_croisement(x, libelles, echelle, gras_premier=True):
    lignes = []
    for i, (cle, r) in enumerate(x.iterrows()):
        nom, definition = libelles(cle)
        cellule_nom = f'<span class="nom">{e(nom)}</span>' + (f'<span class="def">{e(definition)}</span>' if definition else "")
        classe = ' class="fort"' if (i == 0 and gras_premier) else ""
        barre = barre_empilee(r, echelle, 72, total=fr(r["total"], 1))
        lignes.append(f"<tr{classe}><td>{cellule_nom}</td><td>{barre}</td><td class='n'>{fr(r['n'], 0)}</td>"
                      f"<td class='n'>{pc(r['pre'])}</td><td class='n ocre'>{fr(r['pim'] / 1e6, 0)}</td>"
                      f"<td class='n'>{pc(r['pp'])}</td></tr>")
    return "\n".join(lignes)


# ---------------------------------------------------------------- page 2

def dates_debut(g):
    """Date de début des travaux déclarée (formato 12-B), au format ISO « AAAA-MM-JJ HH:MM:SS ».
    Attention : avec dayfirst=True, pandas inverserait jour et mois."""
    brut = g["FEC_INI_EJEC_FISICA"].astype("string").str.strip().replace("", pd.NA)
    return pd.to_datetime(brut, format="%Y-%m-%d %H:%M:%S", errors="coerce")


def calendrier(g, jour):
    """Projets en études détaillées par année de début des travaux déclarée : classes, projets, coût."""
    etudes = g[g["STADE"] == ETUDES].copy()
    etudes["DEBUT"] = dates_debut(etudes)
    annee = jour.year
    classes = [(f"{annee - 1} ou avant", lambda d: d.dt.year <= annee - 1),
               (str(annee), lambda d: d.dt.year == annee),
               (str(annee + 1), lambda d: d.dt.year == annee + 1),
               (str(annee + 2), lambda d: d.dt.year == annee + 2),
               (f"{annee + 3} ou après", lambda d: d.dt.year >= annee + 3),
               ("non déclarée", lambda d: d.isna())]
    lignes = []
    for nom, test in classes:
        sel = etudes[test(etudes["DEBUT"]).fillna(False).astype(bool)]
        passe = sel[sel["DEBUT"] < pd.Timestamp(jour)]
        lignes.append({"classe": nom, "n": len(sel), "cout": sel[C].sum(), "cout_passe": passe[C].sum()})
    t = pd.DataFrame(lignes).set_index("classe")
    fenetre = etudes[etudes["DEBUT"].dt.year.isin([annee + 1, annee + 2])]
    passees = etudes[etudes["DEBUT"] < pd.Timestamp(jour)]
    return t, etudes, fenetre, passees


def graphique_calendrier(t, fenetre, annee):
    """Graphique 4 : colonnes par année de début déclarée ; gris = date déjà passée ; bleu foncé = les deux
    années qui viennent ; accolade sur ces deux années."""
    L, H, base = 104, 37, 29.5
    larg, pas, x0 = 11.5, 16.4, 2
    haut_max = 21 / max(t["cout"].max(), 1)
    contenu = [f'<line x1="0" y1="{base}" x2="{L}" y2="{base}" stroke="#A6A6A6" stroke-width="0.2"/>']
    for i, (nom, r) in enumerate(t.iterrows()):
        x = x0 + i * pas + (2 if nom == "non déclarée" else 0)
        h_tot, h_passe = r["cout"] * haut_max, r["cout_passe"] * haut_max
        fenetre_ = nom in (str(annee + 1), str(annee + 2))
        contenu.append(f'<rect x="{x}" y="{base - h_tot:.2f}" width="{larg}" height="{h_tot:.2f}" '
                       f'fill="{"#1F4E79" if fenetre_ else "#FFFFFF"}" stroke="{"#1F4E79" if fenetre_ else "#8C8C8C"}" stroke-width="0.2"/>')
        if h_passe > 0:
            contenu.append(f'<rect x="{x}" y="{base - h_passe:.2f}" width="{larg}" height="{h_passe:.2f}" '
                           f'fill="#D9D9D9" stroke="#8C8C8C" stroke-width="0.2"/>')
        contenu.append(texte_svg(x + larg / 2, base - h_tot - 1.0, fr(r["cout"] / 1e9, 1), 2.4, "#1A1A1A", "middle", True))
        contenu.append(texte_svg(x + larg / 2, base + 3.0, nom, 2.3, "#1A1A1A", "middle"))
        contenu.append(texte_svg(x + larg / 2, base + 5.8, compte(r["n"], "projet", "projets"), 2.1, "#6B6B6B", "middle"))
    # Accolade au-dessus des deux années qui viennent (colonnes 3 et 4).
    xa, xb = x0 + 2 * pas, x0 + 3 * pas + larg
    sommet = base - max(t.iloc[2]["cout"], t.iloc[3]["cout"]) * haut_max - 4.0
    contenu.append(f'<path d="M{xa:.2f},{sommet + 1.2:.2f}L{xa:.2f},{sommet:.2f}L{xb:.2f},{sommet:.2f}L{xb:.2f},{sommet + 1.2:.2f}" fill="none" stroke="#1F4E79" stroke-width="0.25"/>')
    contenu.append(texte_svg((xa + xb) / 2, sommet - 1.0, f"{compte(len(fenetre), 'projet', 'projets')}, {md(fenetre[C].sum())} Md S/",
                             2.4, "#1F4E79", "middle", True))
    return svg(L, H, "".join(contenu))


def classes_de_taille(g):
    bornes = [1e8, 2.5e8, 5e8, 1e9, 5e9, np.inf]
    noms = ["100 à 250 M S/", "250 à 500 M S/", "0,5 à 1 Md S/", "1 à 5 Md S/", "5 Md S/ ou plus"]
    classe = pd.cut(g[C], bornes, right=False, labels=noms)
    t = g.groupby(classe, observed=False).agg(n=(C, "size"), cout=(C, "sum"), pim=(PIM, "sum"))
    t["pc"], t["pp"] = t["cout"] / g[C].sum(), t["pim"] / g[PIM].sum()
    t["pre"] = g[g["PRE"]].groupby(classe[g["PRE"]], observed=False)[C].sum() / t["cout"]
    return t


def barres_appariees(t, libelles, largeur, echelle_max, col=27):
    """Pour chaque ligne : part du coût (gris) et part du budget de l'année (ocre), valeur au bout."""
    l_barre, pas = largeur - col - 9, 7.2
    contenu = []
    for i, (cle, r) in enumerate(t.iterrows()):
        y = 1 + i * pas
        nom, sous = libelles(cle, r)
        contenu.append(texte_svg(0, y + 2.4, nom, 2.35, gras=True))
        contenu.append(texte_svg(0, y + 5.0, sous, 2.1, "#6B6B6B"))
        for j, (part, couleur, coul_txt) in enumerate([(r["pc"], GRIS_COUT, "#4D4D4D"), (r["pp"], OCRE, OCRE_TEXTE)]):
            yy, l = y + 0.6 + j * 2.9, l_barre * part / echelle_max
            contenu.append(rect(col, yy, l, 2.4, couleur, bord=False))
            contenu.append(texte_svg(col + l + 0.8, yy + 1.95, pc(part), 2.2, coul_txt, gras=True))
    return svg(largeur, 1 + len(t) * pas, "".join(contenu))


def cle_appariee(annee):
    return (f'<div class="cle"><span class="cle-item">{carre(GRIS_COUT)}part du coût prévu</span>'
            f'<span class="cle-item">{carre(OCRE)}part du budget {annee}</span></div>')


def niveaux(g):
    t = g.groupby("NIVEL").agg(n=(C, "size"), cout=(C, "sum"), pim=(PIM, "sum")).reindex(list(NIVEAUX)).fillna(0)
    t["pc"], t["pp"] = t["cout"] / g[C].sum(), t["pim"] / g[PIM].sum()
    return t


def date_courte(d):
    return "n.d." if pd.isna(d) else f"{d:%m/%Y}"


def tableau_pre(g, noms_courts, jour):
    """Tableau 1 : les 10 plus gros projets pas encore en travaux."""
    t = g[g["PRE"]].head(10).copy()
    t["DEBUT"] = dates_debut(t)
    lignes = []
    for _, p in t.iterrows():
        passee = pd.notna(p["DEBUT"]) and p["DEBUT"] < pd.Timestamp(jour)
        annees = [p[f"PMI_ANIO_{k}"] for k in (2, 3, 4)]
        programme = float("nan") if all(pd.isna(a) for a in annees) else sum(a for a in annees if pd.notna(a))
        # Un « ° » invisible garde l'alignement des chiffres quand le projet a reçu des crédits.
        rond = "°" if p["SANS"] else '<span class="vide">°</span>'
        lignes.append(
            f"<tr><td class='code'>{e(p['CODIGO_UNICO'])}</td>"
            f"<td>{e(nom_court(p['CODIGO_UNICO'], p['NOMBRE_INVERSION'], noms_courts))}</td>"
            f"<td>{e(SECTEUR_COURT.get(p['SECTEUR_FICHE'], p['SECTEUR_FICHE']))}</td>"
            f"<td>{e(MODES.get(p['MODE_PUBLIC'], (p['MODE_PUBLIC'],))[0])}</td>"
            f"<td>{carre(COULEUR_STADE[p['STADE']], 2)}{e('Études' if p['STADE'] == ETUDES else p['STADE'])}</td>"
            f"<td class='n'>{fr(p[C] / 1e9, 1)}{rond}</td>"
            f"<td class='n ocre'>{millions_entiers(p[PIM])}</td><td class='n'>{millions_entiers(programme)}</td>"
            f"<td class='n{' passee' if passee else ''}'>{date_courte(p['DEBUT'])}</td></tr>")
    return t, "\n".join(lignes)


def tableau_travaux(g, noms_courts, echelle_max):
    """Tableau 2 : les 10 projets en travaux qui ont le plus gros budget de l'année."""
    t = g[g["STADE"] == TRAVAUX].nlargest(10, PIM)
    lignes = []
    for _, p in t.iterrows():
        avancement = p["AVANCE_FISICO"]
        barre = f'<span class="barre-ocre" style="width:{12 * p[PIM] / echelle_max:.2f}mm"></span>'
        lignes.append(
            f"<tr><td class='code'>{e(p['CODIGO_UNICO'])}</td>"
            f"<td>{e(nom_court(p['CODIGO_UNICO'], p['NOMBRE_INVERSION'], noms_courts))}</td>"
            f"<td>{e(SECTEUR_COURT.get(p['SECTEUR_FICHE'], p['SECTEUR_FICHE']))}</td>"
            f"<td>{e(MODES.get(p['MODE_PUBLIC'], (p['MODE_PUBLIC'],))[0])}</td>"
            f"<td class='n'>{fr(p[C] / 1e9, 1)}</td>"
            f"<td class='n ocre'>{barre}{millions_entiers(p[PIM])}</td>"
            f"<td class='n'>{millions_entiers(p['PMI_ANIO_2'])}</td>"
            f"<td class='n'>{'n.d.' if pd.isna(avancement) else fr(avancement, 0) + chr(160) + '%'}</td></tr>")
    return t, "\n".join(lignes)


def derniere_consultation_proinversion(jour):
    """L'export ProInversión du jour des données (sinon le plus récent avant) : la note est datée d'un seul jour."""
    exports = sorted(p for p in ind.SORTIE_DIR.glob("proinversion_*.xlsx")
                     if p.stem.replace("proinversion_", "") <= jour.isoformat())
    if not exports:
        return None, None
    date = exports[-1].stem.replace("proinversion_", "")
    return pd.read_excel(exports[-1], sheet_name="non_closes", dtype={"projets_mef": str}), date


def bloc_proinversion(non_closes, date, noms_consultations, g):
    if non_closes is None:
        return "<li>ProInversión : lancer d'abord proinversion.py.</li>"
    en_cours = non_closes[non_closes["phase_d_apres_les_documents"].isin(PHASES_EN_COURS)]
    texte = (f"<li>PPP et travaux contre impôts : ProInversión (investinperu.pe). Au {pd.Timestamp(date):%d/%m/%Y}, "
             f"{compte(len(en_cours), 'appel de conseil était', 'appels de conseil étaient')} en cours pour préparer des projets"
             f"{' :' if len(en_cours) else '.'}</li>")
    grands = g.set_index("CODIGO_UNICO")
    for c in en_cours.itertuples():
        nom = noms_consultations.get(str(c.id), c.titre)
        precision = ("offres en évaluation" if c.phase_d_apres_les_documents == "offres reçues, en évaluation"
                     else "avant le dépôt des offres")
        lien = ""
        for code in str(getattr(c, "projets_mef", "") or "").replace(",", " ").split():
            if code in grands.index:
                p = grands.loc[code]
                lien = f" ; projet {code} : {md(p[C])} Md S/, {p['STADE'].lower()}"
                break
        texte += f'<li class="sous">{e(nom[:1].upper() + nom[1:])}, {precision}{e(lien)}.</li>'
    return texte


# ---------------------------------------------------------------- titres (constats chiffrés)

def titres(v):
    """Toutes les phrases de titre, à partir des chiffres calculés. Aucun chiffre n'est écrit en dur."""
    a = v["annee"]
    s, sect, modes, niv, taille = v["stades"], v["secteurs"], v["modes"], v["niveaux"], v["taille"]
    pre_cout = s.loc[[AVANT, ETUDES], "pc"].sum()
    s1 = sect.index[0]
    m1 = modes["total"].idxmax()
    # Second mode cité : les PPP s'ils existent et ne sont pas en tête, sinon le deuxième par coût.
    autres = [m for m in modes.sort_values("total", ascending=False).index if m != m1 and m != ind.NON_RENSEIGNE]
    m2 = "APP" if ("APP" in modes.index and m1 != "APP") else (autres[0] if autres else None)
    nom = lambda m: MODES.get(m, (m,))[0]
    gros = taille.iloc[-1]
    t1, t2 = v["t1"], v["t2"]
    n_app = int((t1["MODE_PUBLIC"] == "APP").sum())
    t = {
        "h1": (f"Pérou : {fr(len(v['g']), 0)} grands projets publics, {md(v['g'][C].sum())} Md S/ de coût prévu, "
               f"dont {pc(pre_cout)} pas encore en travaux"),
        "g1": f"Les projets en travaux font {pc(s.loc[TRAVAUX, 'pc'])} du coût et {pc(s.loc[TRAVAUX, 'pp'])} du budget {a}",
        "g2": f"{s1} : {pc(sect.loc[s1, 'pc'])} du coût, dont {pc(sect.loc[s1, 'pre'])} pas encore en travaux",
        "g3": (f"{nom(m1)} : {pc(modes.loc[m1, 'pc'])} du coût"
               + (f" ; {nom(m2)} : {pc(modes.loc[m2, 'pc'])}, dont {pc(modes.loc[m2, 'pre'])} pas encore en travaux" if m2 else "")),
        "g4": (f"{compte(len(v['fenetre']), 'projet', 'projets')} en études détaillées, {md(v['fenetre'][C].sum())} Md S/, "
               f"{'a' if len(v['fenetre']) < 2 else 'ont'} une date de début inscrite en {a + 1} ou {a + 2}"),
        "g5": (f"Les {fr(gros['n'], 0)} projets de 5 Md S/ ou plus font {pc(gros['pc'])} du coût et "
               f"{pc(gros['pp'])} du budget {a}"),
        "t1": (f"Les {len(t1)} plus gros projets pas encore en travaux pèsent {md(t1[C].sum())} Md S/, "
               + ("aucun en PPP" if n_app == 0 else f"dont {n_app} en PPP")),
        "t2": (f"Les {len(t2)} projets en travaux au plus gros budget {a} en reçoivent "
               f"{pc(t2[PIM].sum() / v['g'][PIM].sum())} ({md(t2[PIM].sum())} Md S/)"),
        "g6": f"Le gouvernement national porte {pc(niv.loc['GN', 'pc'])} du coût et {pc(niv.loc['GN', 'pp'])} du budget {a}",
    }
    return {k: x.replace("’", "'") for k, x in t.items()}


def lecture():
    """Le texte « À retenir » est écrit à la main dans fiche/lecture.txt (une ligne vide entre deux paragraphes).
    Renvoie (html, vide) : vide = True tant que rien n'est écrit."""
    texte = LECTURE.read_text(encoding="utf-8").strip() if LECTURE.exists() else ""
    if not texte:
        return ('<p class="vide">Brouillon : ce texte est l\'interprétation de l\'auteur, à écrire dans fiche/lecture.txt '
                f'({LECTURE_MAX_CARACTERES} caractères au plus).</p>'), True
    if len(texte) > LECTURE_MAX_CARACTERES:
        print(f"Attention : « À retenir » fait {len(texte)} caractères (conseil : {LECTURE_MAX_CARACTERES} au plus).")
    paragraphes = [p.strip() for p in texte.split("\n\n") if p.strip()]
    return "".join(f"<p>{e(p)}</p>" for p in paragraphes), False


def controler(page, titres_):
    """Arrête le script si la note contient un nom brut du MEF ou une valeur non calculée, ou si un titre porte
    un jugement."""
    corps = re.sub(r"<[^>]+>", " ", page.split("<body>", 1)[1])
    problemes = [f"{nom} (« {signe_} »)" for signe_, nom in NOMS_BRUTS if signe_ in corps]
    if re.search(r"\bnan\b|\binf\b", corps, flags=re.IGNORECASE):
        problemes.append("valeur non calculée (nan ou inf)")
    for cle, titre in titres_.items():
        for mot in MOTS_DE_JUGEMENT:
            if mot in titre.lower():
                problemes.append(f"mot de jugement « {mot.strip()} » dans le titre {cle}")
    if problemes:
        raise SystemExit("Note refusée : " + " ; ".join(problemes))


# ---------------------------------------------------------------- impression

def imprimer(page_html, pdf):
    if not CHROME.exists():
        raise SystemExit(f"Chrome introuvable ({CHROME}) : installer Google Chrome ou donner son chemin dans la "
                         "variable d'environnement CHROME.")
    subprocess.run([str(CHROME), "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
                    f"--print-to-pdf={pdf}", page_html.resolve().as_uri()], check=True, capture_output=True, timeout=90)
    pages = len(PdfReader(pdf).pages)
    if pages != 2:
        raise SystemExit(f"La fiche fait {pages} pages au lieu de deux : raccourcir « À retenir » ou un bloc.")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    archives = ch.lister_archives()
    jour = max(archives)
    brut = pd.read_parquet(archives[jour])
    # L'année des budgets (PIM, PMI_ANIO_1...) est celle du fichier, pas forcément celle de la date de l'archive.
    annee = int(brut["ANIO_PROCESO"].astype(str).mode()[0]) if "ANIO_PROCESO" in brut else jour.year
    info_taux = ind.taux_change(annee)
    taux = info_taux["soles_par_dollar"]
    res = ind.calculer(brut, taux)
    g = preparer(res["grands"])
    complet, _ = ind.harmoniser_cout(ind.retirer_doublons(brut)[0])
    noms_courts = lire_noms(NOMS_COURTS, "CODIGO_UNICO")

    # Chiffres de chaque bloc.
    stades_ = chiffres_par_stade(g)
    secteurs = croisement(g, "SECTEUR_FICHE")
    modes = croisement(g, "MODE_PUBLIC", ordre=None)
    modes = modes.reindex(sorted(modes.index, key=lambda m: (m == ind.NON_RENSEIGNE, -modes.loc[m, "total"])))
    echelle = 64 / max(secteurs["total"].max(), modes["total"].max())  # échelle commune aux graphiques 2 et 3
    t_cal, etudes, fenetre, passees = calendrier(g, jour)
    taille = classes_de_taille(g)
    niv = niveaux(g)
    t1, lignes_t1 = tableau_pre(g, noms_courts, jour)
    t2, lignes_t2 = tableau_travaux(g, noms_courts, g[g["STADE"] == TRAVAUX][PIM].max())
    non_closes, date_proinversion = derniere_consultation_proinversion(jour)
    texte_lecture, brouillon = lecture()
    v = {"annee": annee, "g": g, "stades": stades_, "secteurs": secteurs, "modes": modes, "niveaux": niv,
         "taille": taille, "n_etudes": len(etudes), "fenetre": fenetre, "t1": t1, "t2": t2}
    tt = titres(v)

    total, pim_total = g[C].sum(), g[PIM].sum()
    rail = projets_ferroviaires(g)
    app_sans = g[(g["MODE_PUBLIC"] == "APP") & g["SANS"]]
    plusieurs_modes = int((g["NB_MODES"] > 1).sum())
    valeurs = {
        "mois": f"{MOIS_FR[jour.month - 1]} {annee}", "annee": annee, "date": f"{jour:%d/%m/%Y}",
        "an1": annee + 1, "an3": annee + 3,
        "mention_brouillon": ' · <span class="brouillon">Brouillon</span>' if brouillon else "",
        **{f"titre_{k}": e(x) for k, x in tt.items()},
        "chapeau": (f"Projets d'investissement public actifs de {fr(ind.SEUIL_SOLES / 1e6, 0)} M S/ ou plus (environ "
                    f"{fr(ind.SEUIL_SOLES / 1e6 / taux, 0)} M US$), d'après le fichier ouvert du ministère de l'Économie et des "
                    f"Finances (MEF) au {jour:%d/%m/%Y}. Coûts prévus sur toute la durée des projets, indicatifs ; "
                    f"{md(total)} Md S/ font environ {fr(total / 1e9 / taux, 0)} Md US$ (1 US$ = {fr(taux, 2)} S/)."),
        "lecture": texte_lecture,
        "k1": pc(total / complet[C].sum()),
        "k1_legende": (f"du coût de tout l'investissement public actif, porté par {fr(len(g), 0)} projets "
                       f"({pc(len(g) / len(complet))} des {fr(len(complet), 0)} du fichier)"),
        "k2": f"{md(pim_total)} Md S/",
        "k2_legende": (f"de budget {annee} ({pc(pim_total / complet[PIM].sum())} de l'investissement public de l'année), "
                       f"dépensé à {pc(execution(g))} au {jour:%d/%m}"),
        "k3": pc(g["SALDO_EJECUTAR"].sum() / total),
        "k3_legende": (f"du coût ({md(g['SALDO_EJECUTAR'].sum())} Md S/) reste à dépenser après le budget {annee} ; "
                       f"{pc(g['DEVEN_ACUMUL_ANIO_ANT'].fillna(0).sum() / total)} l'a été avant {annee}"),
        "k4": pc(g.loc[g["SANS"], C].sum() / total),
        "k4_legende": (f"du coût ({md(g.loc[g['SANS'], C].sum())} Md S/, {fr(g['SANS'].sum(), 0)} projets) n'a reçu "
                       f"aucun crédit public : ni budget {annee}, ni dépense passée"),
        "note_chiffres": (f"Crédits publics seulement : le financement privé des partenariats public-privé (PPP) n'est pas "
                          f"dans le fichier ({compte(len(app_sans), 'PPP', 'PPP')}, {md(app_sans[C].sum())} Md S/, sans crédit public). "
                          f"Dépense de l'année partielle jusqu'au 31/12."),
        "g1": graphique_stades(stades_, annee),
        "cle_g1": cle_stades(stades_["n"]),
        "note_g1": (f"Stade d'après les phases déclarées au MEF. Avant exécution : projet approuvé, phase d'exécution pas "
                    f"encore ouverte. Études détaillées : phase d'exécution ouverte, études et terrains, travaux pas lancés. "
                    f"Travaux : phase travaux ouverte, chantier lancé ou à lancer. Clôture : fin des travaux déclarée, "
                    f"contrats en liquidation. Totaux arrondis."),
        "cle_g2": cle_stades(),
        "lignes_g2": lignes_croisement(secteurs, lambda s: (s, ""), echelle),
        "note_g2": (f"Secteur : fonction budgétaire du MEF regroupée en {len(secteurs)} secteurs ; les protections contre "
                    f"les crues sont presque toutes en prévention des risques. Trains et métros : {compte(len(rail), 'projet', 'projets')}, "
                    f"{md(rail[C].sum())} Md S/ ({pc(rail[C].sum() / total)} du coût total), dont "
                    f"{fr((rail['STADE'] == TRAVAUX).sum(), 0)} en travaux. Totaux arrondis."),
        "lignes_g3": lignes_croisement(modes, lambda m: MODES.get(m, (m, "")), echelle, gras_premier=True),
        "note_g3": (f"Un projet qui déclare plusieurs modes ({plusieurs_modes} cas) est compté une fois, sous le plus "
                    f"spécifique (PPP d'abord, régie en dernier). Le coût d'un PPP comprend la part privée ; son budget, "
                    f"seulement les crédits publics. Totaux arrondis."),
        "g4": graphique_calendrier(t_cal, fenetre, annee),
        "note_g4": (f"Date de début inscrite au MEF, le plus souvent celle de toute la phase d'exécution, pas toujours mise "
                    f"à jour : c'est ce qui est inscrit, pas ce qui se fera. En gris, une date déjà passée au "
                    f"{jour:%d/%m/%Y} ({compte(len(passees), 'projet', 'projets')}, {md(passees[C].sum())} Md S/). "
                    + (f"En {annee + 1}-{annee + 2}, le plus gros projet, "
                       f"{e(nom_court(fenetre.iloc[0]['CODIGO_UNICO'], fenetre.iloc[0]['NOMBRE_INVERSION'], noms_courts))}, "
                       f"fait {pc(fenetre.iloc[0][C] / fenetre[C].sum())} du coût." if len(fenetre) else "")),
        "g5": barres_appariees(taille, lambda k, r: (k, compte(r["n"], "projet", "projets")), 79, max(taille["pc"].max(), taille["pp"].max())),
        "cle_g5": cle_appariee(annee),
        "note_g5": (f"Borne basse comprise. {pc(taille.iloc[-1]['pre'])} du coût des projets de 5 Md S/ ou plus concerne des "
                    f"projets pas encore en travaux, contre {pc(taille.iloc[0]['pre'])} pour la classe de 100 à 250 M S/. "
                    f"Totaux arrondis."),
        "lignes_t1": lignes_t1,
        "note_t1": (f"° : aucun crédit public reçu (ni budget {annee}, ni dépense passée). Code : numéro unique (CUI), à saisir "
                    f"dans la consultation des investissements du MEF. Programmé {annee + 1}-{annee + 3} : montants inscrits au "
                    f"programme multiannuel, indicatifs. Début : date de début inscrite (souvent celle de la phase d'exécution), "
                    f"en gris si elle est déjà passée ; n.d. : non renseigné."),
        "lignes_t2": lignes_t2,
        "note_t2": (f"Avancement physique déclaré par l'entité ; n.d. : non renseigné. Programmé {annee + 1} : "
                    f"montant inscrit au programme multiannuel, indicatif. "
                    f"{fr(((g['STADE'] == TRAVAUX) & (g[PIM] > 0)).sum(), 0)} des {fr((g['STADE'] == TRAVAUX).sum(), 0)} projets "
                    f"en travaux ont un budget {annee}. Pour un PPP, seuls les crédits publics figurent."),
        "g6": barres_appariees(niv, lambda k, r: (NIVEAUX[k], compte(r["n"], "projet", "projets")), 91,
                               max(niv["pc"].max(), niv["pp"].max()), col=34),
        "cle_g6": cle_appariee(annee),
        "proinversion": bloc_proinversion(non_closes, date_proinversion or jour.isoformat(),
                                          lire_noms(NOMS_CONSULTATIONS, "ID_PROINVERSION"), g),
        "periode_taux": info_taux["periode"], "taux3": fr(taux, 3),
        "date_proinversion": pd.Timestamp(date_proinversion).strftime("%d/%m/%Y") if date_proinversion else "non consulté",
    }
    page = typographie(Template(MODELE.read_text(encoding="utf-8")).substitute(valeurs))
    controler(page, tt)

    ind.SORTIE_DIR.mkdir(exist_ok=True)
    nom = f"fiche_{jour.isoformat()}" + ("_brouillon" if brouillon else "")
    sortie_html, sortie_pdf = ind.SORTIE_DIR / f"{nom}.html", ind.SORTIE_DIR / f"{nom}.pdf"
    sortie_html.write_text(page, encoding="utf-8")
    imprimer(sortie_html, sortie_pdf)
    if brouillon:
        print("Attention : fiche/lecture.txt est absent ou vide, le PDF est un brouillon (ne pas le diffuser).")
    print(f"Fiche des données MEF du {jour:%d/%m/%Y} -> {sortie_pdf}")


def projets_ferroviaires(grands):
    """Trains et métros : typologie « ferroviaire » ou « métro » du MEF, ou nom « ... del Metro de Lima » (sauf la
    voirie urbaine, comme une correspondance avec une station). On ne cherche pas le mot FERROCARRIL seul : il
    attraperait une avenue (Av. Ferrocarril, Huancayo)."""
    typologie = grands["DES_TIPOLOGIA"].fillna("")
    par_type = typologie.str.contains("FERROVIARIO|METRO")
    par_nom = grands["NOMBRE_INVERSION"].str.contains("DEL METRO DE LIMA") & (typologie != "VIAS URBANAS")
    return grands[par_type | par_nom]


if __name__ == "__main__":
    main()
