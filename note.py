"""Note épurée sur les grands projets d'investissement public au Pérou (deuxième format, à côté de fiche.py).

Format : un court essai. Une ligne directrice, de la prose, deux graphiques et un petit tableau, chacun commenté.
La ligne directrice : le portefeuille des grands projets réunit deux générations. Les chantiers en cours, déclarés
viables il y a près de neuf ans (en médiane), reçoivent presque tout le budget de l'année ; la vague suivante,
plus récente, pèse plus de la moitié du coût mais n'est encore que sur plans, et elle tient dans peu de dossiers.

Le texte est écrit à la main dans note/modele.html, mais chaque chiffre est recalculé à chaque lancement. Les phrases qui
comparent (« plus de la moitié », « près de neuf ans »...) sont protégées par des garde-fous : si les données ne
les confirment plus, le script s'arrête et demande de relire le texte (fonction verifier_le_texte).

Lancement : python note.py      (produit exports/note_<date>.html et exports/note_<date>.pdf)
"""

import html
import json
import re
import sys
from pathlib import Path
from string import Template

import pandas as pd
from pypdf import PdfReader
import subprocess

import changements as ch
import fiche
import indicateurs as ind
from fiche import C, PIM, e, fr, md, pc

DOSSIER = Path(__file__).parent / "note"
PAGES_MAX = 3

# Couleurs, en un seul endroit : les graphiques (SVG) et la feuille de style (variables CSS) les lisent ici.
# Une couleur franche pour ce que la note montre (la vague à venir), sa version claire pour les chantiers, un gris
# légèrement teinté pour le marginal (projets en clôture), un gris foncé pour le texte secondaire, un filet presque
# invisible pour le quadrillage et les tableaux. Fond blanc (« fond »), texte principal presque noir (« encre »).
# Les trois palettes viennent de strategie/palettes-graphiques-2026-11-27.md (contrastes vérifiés).
PALETTES = {
    "bleu": {"nom": "bleu", "avant": "#1D5FB4", "secondaire": "#8DBDEB", "marginale": "#CBD5DF",
             "texte_doux": "#4D5B69", "filet": "#E2E7EC", "encre": "#171C22", "fond": "#FFFFFF"},
    "sarcelle": {"nom": "sarcelle", "avant": "#0B7A80", "secondaire": "#8FD3D3", "marginale": "#D2DCDC",
                 "texte_doux": "#4A5A5B", "filet": "#E2E9E9", "encre": "#161D1E", "fond": "#FFFFFF"},
    "terracotta": {"nom": "terracotta", "avant": "#B9461A", "secondaire": "#F2B38E", "marginale": "#D9D1C8",
                   "texte_doux": "#5A524B", "filet": "#ECE6DF", "encre": "#1E1A17", "fond": "#FFFFFF"},
}
PALETTE = PALETTES["sarcelle"]


def palette_de(palette=None):
    """La palette à utiliser : PALETTE par défaut, un nom de PALETTES (sans tenir compte de la casse), ou un dict,
    complété par la palette de PALETTES qui porte son « nom », sinon par PALETTE."""
    if palette is None:
        return dict(PALETTE)
    if isinstance(palette, str):
        nom = palette.strip().lower()
        if nom not in PALETTES:
            raise ValueError(f"Palette inconnue : « {palette} ». Palettes possibles : {', '.join(PALETTES)}.")
        return dict(PALETTES[nom])
    base = PALETTES.get(str(palette.get("nom", "")).lower(), PALETTE)  # un dict nommé est complété par sa palette
    return {**base, **palette}


def variables_css(palette=None):
    """Les couleurs de la palette en variables CSS (--avant, --secondaire...), placées avant style.css."""
    pal = palette_de(palette)
    lignes = "".join(f"  --{cle.replace('_', '-')}: {valeur};\n" for cle, valeur in pal.items() if cle != "nom")
    return ":root {\n" + lignes + "}"


LETTRES = ["zéro", "un", "deux", "trois", "quatre", "cinq", "six", "sept", "huit", "neuf", "dix", "onze", "douze",
           "treize", "quatorze", "quinze", "seize"]


def en_lettres(n, majuscule=False):
    """Petits nombres écrits en lettres dans la prose (« cinq », « Sept »), en chiffres au-delà de seize."""
    texte = LETTRES[n] if 0 <= n < len(LETTRES) else fr(n, 0)
    return texte[:1].upper() + texte[1:] if majuscule else texte


# ---------------------------------------------------------------- calculs

def dates(serie):
    """Dates du fichier du MEF, au format ISO « AAAA-MM-JJ HH:MM:SS » (jamais jour d'abord)."""
    brut = serie.astype("string").str.strip().replace("", pd.NA)
    return pd.to_datetime(brut, format="%Y-%m-%d %H:%M:%S", errors="coerce")


def calculer(jour):
    archives = ch.lister_archives()
    brut = pd.read_parquet(archives[jour])
    annee = int(brut["ANIO_PROCESO"].astype(str).mode()[0])
    info_taux = ind.taux_change(annee)
    taux = info_taux["soles_par_dollar"]
    res = ind.calculer(brut, taux)
    g = fiche.preparer(res["grands"])
    complet, _ = ind.harmoniser_cout(ind.retirer_doublons(brut)[0])
    g["VIABLE_LE"] = dates(g["FECHA_VIABILIDAD"])
    g["DEBUT_INSCRIT"] = dates(g["FEC_INI_EJEC_FISICA"])
    g["PROGRAMME"] = g[["PMI_ANIO_2", "PMI_ANIO_3", "PMI_ANIO_4"]].fillna(0).sum(axis=1)
    g["DEPENSE"] = g["DEVEN_ACUMUL_ANIO_ANT"].fillna(0) + g["DEV_ANIO_ACTUAL"].fillna(0)
    jour_ts = pd.Timestamp(jour)

    pre, travaux, cloture = g[g["PRE"]], g[g["STADE"] == fiche.TRAVAUX], g[g["STADE"] == fiche.CLOTURE]
    v = {"jour": jour, "annee": annee, "taux": taux, "periode_taux": info_taux["periode"], "g": g, "complet": complet,
         "pre": pre, "travaux": travaux, "cloture": cloture}

    # Section 1 : stock et flux.
    v["parts"] = {mesure: [x[col].sum() / g[col].sum() for x in (pre, travaux, cloture)]
                  for mesure, col in [("cout", C), ("budget", PIM), ("programme", "PROGRAMME")]}
    v["totaux"] = {"cout": g[C].sum(), "budget": g[PIM].sum(), "programme": g["PROGRAMME"].sum()}

    # Section 2 : l'âge des projets.
    v["age_travaux"] = ((jour_ts - travaux["VIABLE_LE"]).dt.days / 365.25).median()
    debut_vague = pd.Timestamp(annee - 2, 1, 1)
    v["debut_vague"] = debut_vague
    v["part_pre_recente"] = pre.loc[pre["VIABLE_LE"] >= debut_vague, C].sum() / pre[C].sum()
    v["part_travaux_2012_2020"] = travaux.loc[travaux["VIABLE_LE"].dt.year.between(2012, 2020), C].sum() / travaux[C].sum()
    par_an = g.groupby([g["VIABLE_LE"].dt.year, g["PRE"]])[C].sum().unstack(fill_value=0) / 1e9
    par_an.columns = ["autres" if not c else "pre" for c in par_an.columns]
    v["par_an"] = par_an.reindex(range(int(par_an.index.min()), annee + 1), fill_value=0)
    v["n_par_an"] = g.groupby(g["VIABLE_LE"].dt.year).size()
    cette_annee = g[g["VIABLE_LE"].dt.year == annee]
    v["annee_n"], v["annee_cout"] = len(cette_annee), cette_annee[C].sum()
    v["annee_dernier"] = cette_annee["VIABLE_LE"].max()

    # Section 3 : les très gros projets de la vague.
    gros = pre[pre[C] >= 5e9].sort_values(C, ascending=False)
    v["gros"] = gros
    rail = fiche.projets_ferroviaires(g)
    v["rail_pre"] = rail[rail["PRE"]]
    v["rail_gros"] = gros[gros["CODIGO_UNICO"].isin(rail["CODIGO_UNICO"])]
    v["rail_travaux"] = rail[rail["STADE"] == fiche.TRAVAUX]

    # Section 4 : par où passent les projets.
    def modes(x):
        part = x.groupby("MODE_PUBLIC")[C].sum() / x[C].sum()
        ppp, marche = part.get("APP", 0), part.get("Marché public (por contrata)", 0)
        return {"ppp": ppp, "marche": marche, "autres": 1 - ppp - marche, "cout": x[C].sum()}
    v["modes_travaux"], v["modes_pre"] = modes(travaux), modes(pre)
    datees = g[(g["STADE"] == fiche.ETUDES) & g["DEBUT_INSCRIT"].dt.year.isin([annee + 1, annee + 2])]
    v["datees"], v["modes_datees"] = datees, modes(datees)
    v["age_pre"] = ((jour_ts - pre["VIABLE_LE"]).dt.days / 365.25).median()
    v["ppp_pre_median"] = pre.loc[pre["MODE_PUBLIC"] == "APP", C].median()
    marche_pre = pre[pre["MODE_PUBLIC"] == "Marché public (por contrata)"]
    v["marche_pre_n"] = len(marche_pre)
    v["marche_pre_entites"] = marche_pre["ENTIDAD"].nunique()
    v["marche_pre_median"] = marche_pre[C].median()
    return v


def verifier_le_texte(v):
    """Chaque phrase qui compare doit rester vraie. Sinon, on arrête : le texte est à relire, pas à publier."""
    p = v["parts"]
    ratio_ppp = v["modes_pre"]["ppp"] / max(v["modes_travaux"]["ppp"], 1e-9)
    part_gros = v["gros"][C].sum() / v["pre"][C].sum()
    regles = [
        (p["cout"][0] > 0.5, "« plus de la moitié du coût » : la vague à venir ne fait plus plus de la moitié du coût"),
        (p["budget"][0] < 0.10, "« moins d'un dixième de ce budget » : la vague reçoit maintenant 10 % du budget ou plus"),
        (p["budget"][0] < p["programme"][0] < 0.5, "« le programme leur réserve un peu plus » : n'est plus vrai"),
        (7.5 <= v["age_travaux"] < 9.5, "« près de neuf ans » (chapeau et texte) : l'âge médian des chantiers a changé"),
        (v["part_pre_recente"] > 0.5, "« la vague est récente » : moins de la moitié de son coût déclaré viable depuis le début de la vague"),
        (v["part_travaux_2012_2020"] > 0.5, "« les chantiers viennent surtout des années 2012 à 2020 » : n'est plus vrai"),
        (len(v["gros"]) == 11, "« Onze projets » (intertitre et À retenir) : le nombre de projets de 5 Md S/ ou plus a changé"),
        (0.4 <= part_gros < 0.55, "« près de la moitié de la vague » : la part des onze plus gros projets a changé"),
        (len(v["rail_gros"]) >= 3, "« plusieurs trains et métros » : moins de 3 projets de rail parmi les plus gros"),
        (v["modes_pre"]["marche"] > 0.5, "« le marché public reste majoritaire » : n'est plus vrai"),
        (v["marche_pre_median"] < v["ppp_pre_median"], "« des projets moyens, contre ... pour les PPP » : la médiane du marché public dépasse celle des PPP"),
        (v["age_pre"] < 3, "« elle remonte à moins de trois ans » : l'âge médian de la vague a changé"),
        (2 <= ratio_ppp < 3.5, "« les PPP pèsent trois fois / plus de deux fois plus » : le rapport est sorti de cet intervalle"),
    ]
    erreurs = [message for ok, message in regles if not ok]
    if erreurs:
        raise SystemExit("Le texte de la note ne correspond plus aux données, à relire dans note.py :\n- " + "\n- ".join(erreurs))


# ---------------------------------------------------------------- graphiques (SVG, unités en mm)
# Police des graphiques : celle de la feuille de style (règle « svg »), sans empattement et à chiffres alignés.

def t(x, y, texte, taille, couleur, ancre="start", poids=None):
    style = f' font-weight="{poids}"' if poids else ""
    return (f'<text x="{x:.2f}" y="{y:.2f}" font-size="{taille}" fill="{couleur}" text-anchor="{ancre}"{style}>'
            f"{e(texte)}</text>")


def r(x, y, l, h, couleur):
    return f'<rect x="{x:.2f}" y="{y:.2f}" width="{max(l, 0):.2f}" height="{max(h, 0):.2f}" fill="{couleur}"/>'


def trait(x1, y1, x2, y2, couleur, epaisseur):
    return f'<line x1="{x1:.2f}" y1="{y1:.2f}" x2="{x2:.2f}" y2="{y2:.2f}" stroke="{couleur}" stroke-width="{epaisseur}"/>'


def largeur(texte, taille):
    """Largeur approchée d'un texte (mm), pour éviter les chevauchements d'étiquettes."""
    return 0.5 * taille * len(str(texte))


def svg(l, h, contenu):
    return f'<svg width="{l}mm" height="{h:.2f}mm" viewBox="0 0 {l} {h:.2f}" xmlns="http://www.w3.org/2000/svg">{contenu}</svg>'


def barres_100(lignes, categories, palette=None, L=170, extra=0.0):
    """Barres empilées à 100 %, l'une sous l'autre. lignes = [(libellé, total, [parts])], dans l'ordre des
    catégories : la première est mise en avant (couleur franche), la deuxième en clair, la troisième en gris.
    Les catégories sont nommées une seule fois, au-dessus de la première barre ; la part mise en avant est écrite
    en gras au début de chaque barre, alignée d'une barre à l'autre. Un segment de moins d'un demi-millimètre (une
    part de quelques dixièmes de pour cent) n'est pas dessiné à part : il ne ferait qu'un liseré, pris pour un défaut.
    extra (mm) : hauteur en plus, surtout pour l'espace entre les barres (remplissage de page)."""
    pal = palette_de(palette)
    couleurs = [pal["avant"], pal["secondaire"], pal["marginale"]]
    n = len(lignes)
    x0, y0 = 38, 6.5
    larg = L - x0
    h = 7.0 + min(extra / n * 0.3, 1.0)
    pas = h + 5.0 + max(extra - n * (h - 7.0), 0) / max(n - 1, 1)
    taille_pc = 3.4 + min((h - 7.0) * 0.2, 0.2)
    c = []
    # Noms des catégories, au-dessus de la première barre, au début de leur segment (le dernier calé à droite).
    fin_precedente, debut = -1e9, 0.0
    for k, (nom, part) in enumerate(zip(categories, lignes[0][2])):
        if nom and part > 0:
            dernier = k == len(categories) - 1 and k > 0
            x = x0 + larg * (debut + part) if dernier else x0 + larg * debut
            gauche = x - largeur(nom, 3.0) if dernier else x
            if gauche > fin_precedente + 2:
                c.append(t(x, y0 - 2.0, nom, 3.0, pal["avant"] if k == 0 else pal["texte_doux"],
                           "end" if dernier else "start", 600 if k == 0 else None))
                fin_precedente = gauche + largeur(nom, 3.0)
        debut += part
    for i, (libelle, total, parts) in enumerate(lignes):
        y = y0 + i * pas
        c.append(t(0, y + h / 2 - 0.3, libelle, 3.2, pal["encre"]))
        c.append(t(0, y + h / 2 + 3.3, total, 2.7, pal["texte_doux"]))
        # Largeurs dessinées : un segment trop fin pour se voir est rendu au segment précédent (le total reste 100 %).
        dessin = [larg * part for part in parts]
        for k in range(1, len(dessin)):
            if 0 < dessin[k] < 0.5:
                dessin[k - 1], dessin[k] = dessin[k - 1] + dessin[k], 0.0
        x, segments = x0, []
        for k, (part, l, couleur) in enumerate(zip(parts, dessin, couleurs)):
            if l > 0:
                c.append(r(x, y, l, h, couleur))
            texte = pc(part)
            if k == 0:  # la part mise en avant : toujours écrite, dans la barre si elle y tient, sinon juste après, en encre
                dedans = l >= largeur(texte, taille_pc) + 3.6
                c.append(t(x + 1.8 if dedans else x + l + 1.5, y + h / 2 + taille_pc * 0.36, texte, taille_pc,
                           pal["fond"] if dedans else pal["encre"], "start", 600))
            elif k == 1 and l >= largeur(texte, 3.1) + 3.6 and (x - x0) >= largeur(pc(parts[0]), taille_pc) + 3.6:
                c.append(t(x + 1.8, y + h / 2 + 3.1 * 0.36, texte, 3.1, pal["encre"]))
            x += l
            if l > 0:
                segments.append((x, l))
        for (xb, l), (_, l_suivant) in zip(segments, segments[1:]):  # filet blanc entre deux segments visibles
            if min(l, l_suivant) >= 0.8:
                c.append(trait(xb, y, xb, y + h, pal["fond"], 0.35))
    return svg(L, y0 + (n - 1) * pas + h + 1.0, "".join(c))


def annee_pic(v):
    """L'année où le coût des projets pas encore en travaux est le plus haut (titre et annotation du graphique 2)."""
    return int(v["par_an"]["pre"].idxmax())


def colonnes_par_annee(v, palette=None, L=170, H=66):
    """Coût des grands projets selon l'année de déclaration de viabilité, en colonnes empilées : la vague à venir
    en bas (couleur franche), les chantiers et projets en clôture au-dessus (en clair). Étiquettes directes :
    les chantiers au-dessus de leur plus haute colonne ancienne, la vague à droite de la dernière colonne.
    L'année du pic de la vague (annee_pic) est annotée, calée à droite sur sa colonne."""
    pal = palette_de(palette)
    d = v["par_an"]
    total = d.sum(axis=1)
    annees = list(d.index)
    marge_droite = 22
    x0, x1, haut, base = 0, L - marge_droite, 8, H - 9
    k = (base - haut) / total.max()
    pas = (x1 - x0) / len(d)
    larg = pas * 0.72

    def centre(i):
        return x0 + i * pas + pas / 2

    c = []
    # Quadrillage : deux ou trois lignes presque invisibles, valeur posée au-dessus de la ligne, unité sur la dernière.
    pas_grille = next(s for s in (10, 20, 25, 50, 100, 200, 500) if total.max() / s <= 3)
    valeurs = list(range(pas_grille, int(total.max()) + 1, pas_grille))
    for val in valeurs:
        y = base - val * k
        c.append(trait(x0, y, x1, y, pal["filet"], 0.25))
        c.append(t(x0, y - 1.2, fr(val, 0) + (" Md S/" if val == valeurs[-1] else ""), 2.7, pal["texte_doux"]))
    for i, (annee, ligne) in enumerate(d.iterrows()):
        x = centre(i) - larg / 2
        h_pre, h_autres = ligne.get("pre", 0) * k, ligne.get("autres", 0) * k
        c.append(r(x, base - h_pre, larg, h_pre, pal["avant"]))
        c.append(r(x, base - h_pre - h_autres, larg, h_autres, pal["secondaire"]))
        if min(h_pre, h_autres) >= 0.6:  # filet blanc entre les deux parties, si les deux se voient
            c.append(trait(x, base - h_pre, x + larg, base - h_pre, pal["fond"], 0.35))
        if annee % 4 == v["annee"] % 4:
            c.append(t(centre(i), base + 4.2, str(annee), 2.7, pal["texte_doux"], "middle"))
    c.append(trait(x0, base, x1, base, pal["texte_doux"], 0.25))
    c.append(t(centre(len(d) - 1), base + 7.6, f"au {v['annee_dernier']:%d/%m}", 2.5, pal["texte_doux"], "middle"))

    def au_dessus(gauche, droite, ecart=1.5):
        """Hauteur (mm) d'une étiquette posée entre les abscisses gauche et droite, au-dessus des colonnes qu'elle couvre."""
        voisines = [j for j in range(len(d)) if centre(j) + larg / 2 >= gauche and centre(j) - larg / 2 <= droite]
        return base - max(total.iloc[voisines]) * k - ecart

    # L'année du pic de la vague, annotée sobrement au-dessus de sa colonne, calée sur son bord droit.
    pic = annee_pic(v)
    i_pic = annees.index(pic)
    note_pic = f"{pic} : {fr(v['n_par_an'].get(pic, 0), 0)} projets, {md(total[pic] * 1e9)} Md S/"
    x_pic = centre(i_pic) + larg / 2
    c.append(t(x_pic, au_dessus(x_pic - largeur(note_pic, 2.7), x_pic), note_pic, 2.7, pal["encre"], "end"))
    # Chantiers et clôtures : au-dessus de la plus haute colonne où la vague à venir pèse peu.
    anciennes = [i for i, a in enumerate(annees) if total[a] > 0 and d.loc[a].get("pre", 0) < 0.15 * total[a]]
    if anciennes:
        i_c = max(anciennes, key=lambda i: total.iloc[i])
        texte = "En travaux ou en clôture"
        demi = largeur(texte, 2.8) / 2
        c.append(t(centre(i_c), au_dessus(centre(i_c) - demi, centre(i_c) + demi), texte, 2.8, pal["texte_doux"], "middle"))
    # Vague à venir : à droite de la dernière colonne, à mi-hauteur de sa partie foncée.
    h_pre_fin = d.iloc[-1].get("pre", 0) * k
    y_v = base - max(h_pre_fin / 2, 4.5)
    x_v = centre(len(d) - 1) + larg / 2 + 1.8
    c.append(t(x_v, y_v - 0.6, "Pas encore", 2.8, pal["avant"], "start", 600))
    c.append(t(x_v, y_v + 2.9, "en travaux", 2.8, pal["avant"], "start", 600))
    return svg(L, H, "".join(c))


# ---------------------------------------------------------------- page

def tableau_gros(v, noms_courts):
    lignes = []
    for _, p in v["gros"].iterrows():
        mode = fiche.MODES.get(p["MODE_PUBLIC"], (p["MODE_PUBLIC"],))[0]
        depense = "aucun" if p["SANS"] else fr(p["DEPENSE"] / 1e6, 0)
        lignes.append(f"<tr><td>{e(fiche.nom_court(p['CODIGO_UNICO'], p['NOMBRE_INVERSION'], noms_courts))}</td>"
                      f"<td class='n'>{fr(p[C] / 1e9, 1)}</td><td>{e(mode)}</td>"
                      f"<td class='n'>{p['VIABLE_LE']:%Y}</td><td class='n'>{depense}</td></tr>")
    return "\n".join(lignes)


def remplir(v, extras=None, palette=None):
    """Toutes les valeurs du modèle. extras : hauteur en plus pour les graphiques et interligne du tableau (mm),
    calculés par mettre_en_page pour que chaque page soit pleine. palette : voir palette_de."""
    extras = extras or {"g1": 0.0, "g2": 0.0, "ligne": 1.2}
    g, pre, p, tot = v["g"], v["pre"], v["parts"], v["totaux"]
    annee, jour = v["annee"], v["jour"]
    gros, rail_gros = v["gros"], v["rail_gros"]
    noms_courts = fiche.lire_noms(fiche.NOMS_COURTS, "CODIGO_UNICO")
    sans_gros = int(gros["SANS"].sum())
    valeurs = {
        "annee": annee, "an1": annee + 1, "an2": annee + 2, "an3": annee + 3,
        "mois": f"{fiche.MOIS_FR[jour.month - 1]} {annee}", "date": f"{jour:%d/%m/%Y}",
        "nb": fr(len(g), 0), "cout": md(tot["cout"]), "cout_usd": fr(tot["cout"] / 1e9 / v["taux"], 0),
        "part_complet": pc(tot["cout"] / v["complet"][C].sum()), "nb_complet": fr(round(len(v["complet"]), -3), 0),
        "budget": md(tot["budget"]), "programme": md(tot["programme"]),
        "pre_cout": pc(p["cout"][0]), "pre_budget": pc(p["budget"][0]), "travaux_budget": pc(p["budget"][1]),
        "pre_programme": pc(p["programme"][0]), "pre_md": md(pre[C].sum()),
        "age": fr(v["age_travaux"], 0), "part_recente": pc(v["part_pre_recente"]), "debut_vague": v["debut_vague"].year,
        "annee_n": fr(v["annee_n"], 0), "annee_cout": md(v["annee_cout"]),
        "annee_ratio": fr(v["annee_cout"] / tot["budget"], 1), "annee_dernier": f"{v['annee_dernier']:%d/%m}",
        "gros_n": fr(len(gros), 0), "gros_part": pc(gros[C].sum() / pre[C].sum()), "autres_n": fr(len(pre) - len(gros), 0),
        "gros_sans": fr(sans_gros, 0), "rail_gros_n": fr(len(rail_gros), 0),
        "rail_pre_md": md(v["rail_pre"][C].sum()), "rail_pre_part": pc(v["rail_pre"][C].sum() / pre[C].sum()),
        "rail_pre_depense": fr(v["rail_pre"]["DEPENSE"].sum() / 1e6, 0),
        "ppp_travaux": pc(v["modes_travaux"]["ppp"]), "ppp_pre": pc(v["modes_pre"]["ppp"]),
        "marche_pre": pc(v["modes_pre"]["marche"]), "datees_n": fr(len(v["datees"]), 0),
        "marche_datees": pc(v["modes_datees"]["marche"]), "marche_n": fr(v["marche_pre_n"], 0),
        "marche_entites": fr(v["marche_pre_entites"], 0), "marche_median": fr(v["marche_pre_median"] / 1e6, 0),
        "taux": fr(v["taux"], 3), "periode_taux": v["periode_taux"],
        "age_lettres": en_lettres(int(round(v["age_travaux"]))), "gros_lettres": en_lettres(len(gros)),
        "age_pre_lettres": en_lettres(3), "ppp_median": fr(v["ppp_pre_median"] / 1e6, 0),
        "gros_ppp_Lettres": en_lettres(int((gros["MODE_PUBLIC"] == "APP").sum()), True),
        "rail_gros_Lettres": en_lettres(len(rail_gros), True), "rail_gros_lettres": en_lettres(len(rail_gros)),
        "gros_sans_lettres": en_lettres(sans_gros), "gros_ppp_lettres": en_lettres(int((gros["MODE_PUBLIC"] == "APP").sum())),
        "annee_dernier_long": f"{v['annee_dernier'].day} {fiche.MOIS_FR[v['annee_dernier'].month - 1]}",
        "md_usd": fr(1e3 / v["taux"], 0), "marche_median_usd": fr(v["marche_pre_median"] / 1e6 / v["taux"], 0),
        "ppp_facteur": ("trois fois plus" if v["modes_pre"]["ppp"] / v["modes_travaux"]["ppp"] >= 2.6 else "plus de deux fois plus"),
        "pic": annee_pic(v),
        "graphique_1": barres_100(
            [("Coût prévu", f"{md(tot['cout'])} Md S/", p["cout"]),
             (f"Budget {annee}", f"{md(tot['budget'])} Md S/", p["budget"]),
             (f"Programme {annee + 1}-{annee + 3}", f"{md(tot['programme'])} Md S/", p["programme"])],
            ["Pas encore en travaux", "En travaux", "En clôture"], palette, extra=extras["g1"]),
        "graphique_2": colonnes_par_annee(v, palette, H=66 + extras["g2"]),
        "tableau": tableau_gros(v, noms_courts),
        "ligne": f"{extras['ligne']:.2f}mm",
    }
    return valeurs


# ---------------------------------------------------------------- mise en page : trois pages pleines

HAUTEUR_PAGE = 262  # mm, hauteur de section.page dans style.css
RESPIRATION = 9     # mm laissés à chaque « respiration » avant de grandir les graphiques


def composer(v, extras, palette=None):
    valeurs = remplir(v, extras, palette)
    valeurs["couleurs"] = variables_css(palette)
    valeurs["style"] = (DOSSIER / "style.css").read_text(encoding="utf-8")
    return fiche.typographie(Template((DOSSIER / "modele.html").read_text(encoding="utf-8")).substitute(valeurs))


def mesurer(page, dossier=None):
    """Hauteur naturelle (mm) du contenu de chaque page, sans les respirations, telle que Chrome la compose.
    On libère la hauteur des pages, on écrase les respirations, et un petit script écrit les mesures dans le DOM.
    Le fichier d'essai est écrit (puis effacé) dans dossier, exports/ par défaut."""
    sonde = """<style>.page{height:auto!important}.respire{flex:none!important;height:0!important;min-height:0!important}
    .pied{margin-top:0!important}body{width:170mm}</style><script>
    addEventListener('load',()=>{document.body.dataset.mesures=JSON.stringify([...document.querySelectorAll('section.page')]
      .map(s=>({h:s.getBoundingClientRect().height*25.4/96, r:s.querySelectorAll('.respire').length})))});</script>"""
    dossier = Path(dossier) if dossier else ind.SORTIE_DIR
    dossier.mkdir(parents=True, exist_ok=True)
    essai = dossier / "note_mesure.html"
    essai.write_text(page.replace("</head>", sonde + "</head>"), encoding="utf-8")
    dom = subprocess.run([str(fiche.CHROME), "--headless=new", "--disable-gpu", "--virtual-time-budget=3000", "--dump-dom",
                          essai.as_uri()], capture_output=True, text=True, encoding="utf-8", timeout=90).stdout
    essai.unlink(missing_ok=True)
    trouve = re.search(r'data-mesures="([^"]*)"', dom)
    if not trouve:
        raise SystemExit("Mesure de la mise en page impossible (Chrome n'a pas rendu la page).")
    return json.loads(html.unescape(trouve.group(1)))


G1_EXTRA_MAX = 8   # mm : au-delà, les barres du graphique 1 s'écartent trop les unes des autres
G2_EXTRA_MAX = 25  # mm : au-delà, la zone de tracé du graphique 2 devient plus haute que la moitié de sa largeur


def mettre_en_page(v, palette=None, dossier=None):
    """Compose la note, mesure la place libre sur chaque page, puis en donne une part plafonnée aux graphiques
    (pages 1 et 2) et à l'interligne du tableau (page 3). Les respirations entre les parties prennent le reste,
    dans leur limite : mieux vaut un peu de blanc en bas d'une page qu'un graphique étiré. Le pied de la dernière
    page descend en bas. Arrête le script si une page déborde. dossier : voir mesurer."""
    extras = {"g1": 0.0, "g2": 0.0, "ligne": 1.2}
    mesures = mesurer(composer(v, extras, palette), dossier)
    libre = [HAUTEUR_PAGE - m["h"] - m["r"] * RESPIRATION for m in mesures]
    if min(HAUTEUR_PAGE - m["h"] for m in mesures) < 0:
        raise SystemExit(f"Une page déborde (hauteurs : {[round(m['h']) for m in mesures]} mm pour {HAUTEUR_PAGE}) : raccourcir.")
    extras["g1"] = min(max(libre[0], 0), G1_EXTRA_MAX)
    extras["g2"] = min(max(libre[1], 0), G2_EXTRA_MAX)
    lignes = len(v["gros"])
    extras["ligne"] = 1.2 + min(max(libre[2], 0) / (2 * lignes), 1.6)
    page = composer(v, extras, palette)
    apres = mesurer(page, dossier)
    if max(m["h"] for m in apres) > HAUTEUR_PAGE:
        raise SystemExit(f"Une page déborde après remplissage ({[round(m['h']) for m in apres]} mm) : à corriger.")
    return page, extras, [round(HAUTEUR_PAGE - m["h"], 1) for m in apres]


def imprimer(page_html, pdf):
    subprocess.run([str(fiche.CHROME), "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
                    f"--print-to-pdf={pdf}", page_html.resolve().as_uri()], check=True, capture_output=True, timeout=90)
    pages = len(PdfReader(pdf).pages)
    if pages > PAGES_MAX:
        raise SystemExit(f"La note fait {pages} pages (au plus {PAGES_MAX}) : raccourcir le texte.")
    return pages


def generer(jour, palette=None, sortie=None):
    """Produit la note des données MEF du jour donné, avec la palette donnée (nom de PALETTES, dict, ou None pour
    PALETTE). sortie : un dossier (note_<jour>.html et note_<jour>.pdf dedans, exports/ par défaut) ou le chemin
    d'un PDF (le HTML est écrit à côté, même nom). Renvoie le chemin du PDF, son nombre de pages et les réglages
    de mise en page."""
    v = calculer(jour)
    verifier_le_texte(v)
    sortie = Path(sortie) if sortie else ind.SORTIE_DIR
    if sortie.suffix.lower() == ".pdf":
        sortie_pdf, sortie_html = sortie, sortie.with_suffix(".html")
    else:
        sortie_html, sortie_pdf = sortie / f"note_{jour.isoformat()}.html", sortie / f"note_{jour.isoformat()}.pdf"
    sortie_pdf.parent.mkdir(parents=True, exist_ok=True)
    page, extras, reste = mettre_en_page(v, palette, sortie_pdf.parent)
    fiche.controler(page, {})
    sortie_html.write_text(page, encoding="utf-8")
    pages = imprimer(sortie_html, sortie_pdf)
    return {"pdf": sortie_pdf, "html": sortie_html, "pages": pages, "extras": extras, "reste": reste}


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    jour = max(ch.lister_archives())
    ind.SORTIE_DIR.mkdir(exist_ok=True)
    res = generer(jour)
    extras = res["extras"]
    print(f"Mise en page : graphique 1 +{extras['g1']:.0f} mm, graphique 2 +{extras['g2']:.0f} mm, "
          f"interligne du tableau {extras['ligne']:.1f} mm ; place pour les respirations : {res['reste']} mm")
    print(f"Note des données MEF du {jour:%d/%m/%Y} ({res['pages']} pages, palette {palette_de()['nom']}) -> {res['pdf']}")


if __name__ == "__main__":
    main()
