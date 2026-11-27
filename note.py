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

# Couleurs : un bleu nuit pour la vague à venir (le sujet de la note), des gris chauds pour le reste, un ocre pour les PPP.
BLEU, GRIS, GRIS_CLAIR, OCRE = "#2b3f6b", "#9c968a", "#d9d4c8", "#b5651d"
ENCRE, ENCRE_DOUCE = "#1a1a1a", "#6b665c"
CREME = "#f7f4ec"


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

def t(x, y, texte, taille=3.0, couleur=ENCRE, ancre="start", italique=False, gras=False):
    style = (' font-style="italic"' if italique else "") + (' font-weight="bold"' if gras else "")
    return (f'<text x="{x:.2f}" y="{y:.2f}" font-size="{taille}" fill="{couleur}" text-anchor="{ancre}"{style}>'
            f"{e(texte)}</text>")


def r(x, y, l, h, couleur):
    return f'<rect x="{x:.2f}" y="{y:.2f}" width="{max(l, 0):.2f}" height="{h:.2f}" fill="{couleur}"/>'


def svg(l, h, contenu):
    return f'<svg width="{l}mm" height="{h}mm" viewBox="0 0 {l} {h}" xmlns="http://www.w3.org/2000/svg">{contenu}</svg>'


def barres_100(lignes, couleurs, etiquettes_haut, L=158, extra=0.0):
    """Barres empilées à 100 %, l'une sous l'autre. lignes = [(libellé, sous-libellé, [parts])].
    extra (mm) : hauteur en plus, répartie entre l'épaisseur des barres et l'espace entre elles (remplissage de page)."""
    n = len(lignes)
    x0, larg, y0 = 44, L - 44, 6
    h = 6.6 + min(extra / n * 0.75, 5.0)
    pas = h + 4.9 + (extra - n * (h - 6.6)) / n
    taille_pc = 3.0 + min((h - 6.6) * 0.12, 0.9)  # pourcentages un peu plus grands dans des barres épaisses
    c = []
    # Étiquettes directes au-dessus de la première barre, au milieu de leur segment.
    debut = 0
    for part, (texte, couleur) in zip(lignes[0][2], etiquettes_haut):
        if texte:
            c.append(t(x0 + larg * (debut + part / 2), y0 - 1.6, texte, 3.1, couleur, "middle", italique=True))
        debut += part
    for i, (libelle, sous, parts) in enumerate(lignes):
        y = y0 + i * pas
        c.append(t(0, y + h / 2 - 0.3, libelle, 3.1))
        c.append(t(0, y + h / 2 + 3.0, sous, 2.8, ENCRE_DOUCE, italique=True))
        x = x0
        for part, couleur in zip(parts, couleurs):
            l = larg * part
            c.append(r(x, y, l, h, couleur))
            if l >= 9:
                clair = couleur in (BLEU, OCRE, GRIS)
                c.append(t(x + l / 2, y + h / 2 + taille_pc * 0.35, pc(part), taille_pc, "#ffffff" if clair else ENCRE, "middle"))
            x += l
    return svg(L, y0 + (n - 1) * pas + h + 1.5, "".join(c))


def colonnes_par_annee(v, L=158, H=66):
    """Coût des grands projets selon l'année de déclaration de viabilité, empilé : vague à venir en bas (bleu)."""
    d = v["par_an"]
    x0, x1, base, haut = 9, L - 2, H - 9, 9
    ymax = 25 * (int(d.sum(axis=1).max() // 25) + 1)
    k = (base - haut) / ymax
    pas = (x1 - x0) / len(d)
    larg = pas * 0.72
    c = []
    for val in range(25, ymax + 1, 25):
        y = base - val * k
        c.append(f'<line x1="{x0}" y1="{y:.2f}" x2="{x1}" y2="{y:.2f}" stroke="#e4dfd3" stroke-width="0.2"/>')
        c.append(t(x0 - 1.5, y + 1.0, fr(val, 0), 2.8, ENCRE_DOUCE, "end"))
    c.append(f'<line x1="{x0}" y1="{base}" x2="{x1}" y2="{base}" stroke="{GRIS}" stroke-width="0.25"/>')
    for i, (annee, ligne) in enumerate(d.iterrows()):
        x = x0 + i * pas + (pas - larg) / 2
        h_pre, h_autres = ligne.get("pre", 0) * k, ligne.get("autres", 0) * k
        c.append(r(x, base - h_pre, larg, h_pre, BLEU))
        c.append(r(x, base - h_pre - h_autres, larg, h_autres, GRIS))
        if annee % 4 == v["annee"] % 4 or annee == d.index.min():
            c.append(t(x + larg / 2, base + 4.4, str(annee), 2.9, ENCRE_DOUCE, "middle"))
    # Annotation de l'année la plus haute, et étiquettes directes des deux couleurs.
    pic = d.sum(axis=1).idxmax()
    i_pic = list(d.index).index(pic)
    x_pic = x0 + i_pic * pas + pas / 2
    y_pic = base - d.loc[pic].sum() * k
    c.append(t(x_pic - 3, y_pic - 2.2, f"{pic} : {fr(v['n_par_an'].get(pic, 0), 0)} projets, {md(d.loc[pic].sum() * 1e9)} Md S/",
               2.7, ENCRE, "end", italique=True))
    # « pas encore en travaux » : posé au-dessus des barres qui précèdent le début de la vague, avec un trait en coude
    # qui descend droit dans la partie bleue de l'année d'avant (sans traverser d'autre barre).
    i_cible = list(d.index).index(v["debut_vague"].year - 1) if v["debut_vague"].year - 1 in d.index else len(d) - 3
    x_cible = x0 + i_cible * pas + pas / 2
    y_cible = base - d.iloc[i_cible].get("pre", 0) * k * 0.5
    y_bleu = base - (d.iloc[max(i_cible - 6, 0):i_cible + 1].sum(axis=1).max() + 9) * k
    c.append(t(x_cible - 2.0, y_bleu, "pas encore en travaux", 2.9, BLEU, "end", italique=True, gras=True))
    c.append(f'<path d="M{x_cible - 1.4:.2f},{y_bleu - 0.9:.2f}L{x_cible:.2f},{y_bleu - 0.9:.2f}L{x_cible:.2f},{y_cible:.2f}" '
             f'fill="none" stroke="{BLEU}" stroke-width="0.25"/>')
    i_gris = list(d.index).index(2013) if 2013 in d.index else len(d) // 2
    y_gris = base - d.iloc[i_gris].sum() * k
    c.append(t(x0 + i_gris * pas + pas / 2, y_gris - 2.2, "en travaux ou en clôture", 2.7, ENCRE_DOUCE, "middle", italique=True))
    c.append(t(x0 + (len(d) - 1) * pas + pas / 2, base + 7.6, f"(au {v['annee_dernier']:%d/%m})", 2.5,
               ENCRE_DOUCE, "middle", italique=True))
    c.append(t(x0 - 1.5, haut - 3.5, "Md S/", 2.8, ENCRE_DOUCE, "end", italique=True))
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


def remplir(v, extras=None):
    """Toutes les valeurs du modèle. extras : hauteur en plus pour les graphiques et interligne du tableau (mm),
    calculés par mettre_en_page pour que chaque page soit pleine."""
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
        "graphique_1": barres_100(
            [("Coût prévu", f"{md(tot['cout'])} Md S/, sur toute la durée", p["cout"]),
             (f"Budget {annee}", f"{md(tot['budget'])} Md S/", p["budget"]),
             (f"Programme {annee + 1}-{annee + 3}", f"{md(tot['programme'])} Md S/ inscrits", p["programme"])],
            [BLEU, GRIS, GRIS_CLAIR], [("pas encore en travaux", BLEU), ("en travaux", ENCRE_DOUCE), ("", None)],
            extra=extras["g1"]),
        "graphique_2": colonnes_par_annee(v, H=66 + extras["g2"]),
        "tableau": tableau_gros(v, noms_courts),
        "ligne": f"{extras['ligne']:.2f}mm",
    }
    return valeurs


# ---------------------------------------------------------------- mise en page : trois pages pleines

HAUTEUR_PAGE = 262  # mm, hauteur de section.page dans style.css
RESPIRATION = 9     # mm laissés à chaque « respiration » avant de grandir les graphiques


def composer(v, extras):
    valeurs = remplir(v, extras)
    valeurs["style"] = (DOSSIER / "style.css").read_text(encoding="utf-8")
    return fiche.typographie(Template((DOSSIER / "modele.html").read_text(encoding="utf-8")).substitute(valeurs))


def mesurer(page):
    """Hauteur naturelle (mm) du contenu de chaque page, sans les respirations, telle que Chrome la compose.
    On libère la hauteur des pages, on écrase les respirations, et un petit script écrit les mesures dans le DOM."""
    sonde = """<style>.page{height:auto!important}.respire{flex:none!important;height:0!important;min-height:0!important}
    .pied{margin-top:0!important}body{width:170mm}</style><script>
    addEventListener('load',()=>{document.body.dataset.mesures=JSON.stringify([...document.querySelectorAll('section.page')]
      .map(s=>({h:s.getBoundingClientRect().height*25.4/96, r:s.querySelectorAll('.respire').length})))});</script>"""
    essai = ind.SORTIE_DIR / "note_mesure.html"
    essai.write_text(page.replace("</head>", sonde + "</head>"), encoding="utf-8")
    dom = subprocess.run([str(fiche.CHROME), "--headless=new", "--disable-gpu", "--virtual-time-budget=3000", "--dump-dom",
                          essai.as_uri()], capture_output=True, text=True, encoding="utf-8", timeout=90).stdout
    essai.unlink(missing_ok=True)
    trouve = re.search(r'data-mesures="([^"]*)"', dom)
    if not trouve:
        raise SystemExit("Mesure de la mise en page impossible (Chrome n'a pas rendu la page).")
    return json.loads(html.unescape(trouve.group(1)))


def mettre_en_page(v):
    """Compose la note, mesure la place libre sur chaque page, puis la donne aux graphiques (pages 1 et 2) et à
    l'interligne du tableau (page 3). Les respirations entre les parties prennent le reste, et le pied de la
    dernière page descend en bas. Arrête le script si une page déborde."""
    extras = {"g1": 0.0, "g2": 0.0, "ligne": 1.2}
    mesures = mesurer(composer(v, extras))
    libre = [HAUTEUR_PAGE - m["h"] - m["r"] * RESPIRATION for m in mesures]
    if min(HAUTEUR_PAGE - m["h"] for m in mesures) < 0:
        raise SystemExit(f"Une page déborde (hauteurs : {[round(m['h']) for m in mesures]} mm pour {HAUTEUR_PAGE}) : raccourcir.")
    extras["g1"] = min(max(libre[0] + 8, 0), 28)
    extras["g2"] = min(max(libre[1], 0), 70)
    lignes = len(v["gros"])
    extras["ligne"] = 1.2 + min(max(libre[2], 0) / (2 * lignes), 1.6)
    page = composer(v, extras)
    apres = mesurer(page)
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


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    jour = max(ch.lister_archives())
    v = calculer(jour)
    verifier_le_texte(v)
    ind.SORTIE_DIR.mkdir(exist_ok=True)
    page, extras, reste = mettre_en_page(v)
    print(f"Mise en page : graphique 1 +{extras['g1']:.0f} mm, graphique 2 +{extras['g2']:.0f} mm, "
          f"interligne du tableau {extras['ligne']:.1f} mm ; place pour les respirations : {reste} mm")
    fiche.controler(page, {})
    sortie_html, sortie_pdf = ind.SORTIE_DIR / f"note_{jour.isoformat()}.html", ind.SORTIE_DIR / f"note_{jour.isoformat()}.pdf"
    sortie_html.write_text(page, encoding="utf-8")
    pages = imprimer(sortie_html, sortie_pdf)
    print(f"Note des données MEF du {jour:%d/%m/%Y} ({pages} pages) -> {sortie_pdf}")


if __name__ == "__main__":
    main()
