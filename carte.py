"""Étape 6 : la carte des grands projets d'investissement public au Pérou (une page HTML interactive).

Ce que fait le script, dans l'ordre :
1. Prépare la dernière archive comme à l'étape 2 (doublons, coût harmonisé, coordonnées nettoyées) et en tire
   les grands projets, avec leur secteur et leur mode de réalisation.
2. Donne une position à chaque grand projet :
   - « déclarée » : le point du fichier, s'il est au Pérou ;
   - « approchée » : sinon, le point médian des projets localisés du même district (ou de la même province)
     dans tout le fichier du MEF, ce qui donne à peu près le centre de la localité ;
   - aucune : pour un projet déclaré sur plusieurs départements, ou sans lieu précis. Il est compté à part.
3. Dessine un cercle par projet avec folium (bibliothèque Python qui écrit une carte Leaflet) :
   taille selon le coût, couleur selon le secteur (une case à cocher par secteur), cercle creux si le projet
   n'a ni budget cette année ni dépense passée, contour en pointillé si la position est approchée.
4. Ajoute un encadré : source, date, et surtout combien de projets et quelle part du coût ne sont PAS sur la carte.
5. Écrit exports/carte_<date>.html, à ouvrir dans un navigateur connecté à Internet (Leaflet et le fond de carte
   OpenStreetMap sont chargés en ligne).

Comme la fiche, la carte ne cite aucune entreprise en dehors des intitulés officiels du MEF et ne classe aucune région.

Lancement : python carte.py
"""

import math
import re
import sys

import folium
import pandas as pd
from branca.element import MacroElement
from jinja2 import Template

import changements as ch
import fiche
import indicateurs as ind

# Couleurs lisibles aussi par les daltoniens (palette d'Okabe et Ito, plus un gris, un brun et un rouge foncé).
COULEURS = {
    "Transports et télécoms": "#0072B2",
    "Eau et assainissement": "#56B4E9",
    "Santé": "#D55E00",
    "Agriculture, irrigation et pêche": "#009E73",
    "Éducation, recherche, culture et sport": "#CC79A7",
    "Administration, justice et sécurité": "#555555",
    "Prévention des risques": "#E69F00",
    "Énergie, environnement et autres": "#8C6D31",
    "Non classé": "#7A1F3D",  # au cas où une nouvelle fonction du MEF n'est pas dans secteurs.csv
}
# Taille des cercles : rayon proportionnel à la racine carrée du coût, avec un minimum pour rester visible.
# Le coût de référence est fixe (et non le maximum du jour) pour que deux cartes de dates différentes se comparent.
RAYON_MIN, RAYON_REFERENCE, COUT_REFERENCE = 3, 28, 30e9
REPERES_TAILLE = [(0.1e9, "0,1"), (2e9, "2"), (10e9, "10"), (30e9, "30 Md S/")]
DECLAREE, APPROCHEE_DISTRICT, APPROCHEE_PROVINCE = "déclarée", "approchée (district)", "approchée (province)"


# ---------------------------------------------------------------- positions

def rayon(cout):
    """Rayon en pixels : 28 px pour 30 Md S/, proportionnel à la racine carrée du coût (la surface suit alors
    le coût), mais jamais moins de 3 px. Sous environ 350 M S/, tous les cercles ont donc la taille minimale."""
    return max(RAYON_MIN, RAYON_REFERENCE * math.sqrt(cout / COUT_REFERENCE))


def lieu_precis(ubigeo, departement):
    """Faux pour un projet déclaré sur plusieurs départements (-MUL.DEP-, code 99...) ou sans code de lieu."""
    ubigeo = str(ubigeo or "")
    return departement != "-MUL.DEP-" and len(ubigeo) == 6 and not ubigeo.startswith("99")


def points_valides(df):
    """Projets avec un point utilisable : coordonnées au Pérou (nettoyer() a vidé les autres), lieu précis, et pas
    de coordonnées rondes comme (-10, -76), une valeur bouche-trou mise faute de mieux."""
    connu = df["LATITUD"].notna() & df["LONGITUD"].notna()
    rond = (df["LATITUD"] % 1 == 0) & (df["LONGITUD"] % 1 == 0)
    precis = pd.Series([lieu_precis(u, d) for u, d in zip(df["UBIGEO"], df["DEPARTAMENTO"])], index=df.index)
    return connu & ~rond & precis


def centres(df_complet):
    """Point médian des projets localisés, par district (UBIGEO à 6 chiffres) et par province (4 premiers chiffres).
    La médiane résiste mieux qu'une moyenne à un point mal saisi."""
    valides = df_complet[points_valides(df_complet)]
    par_district = valides.groupby("UBIGEO")[["LATITUD", "LONGITUD"]].median()
    par_province = valides.groupby(valides["UBIGEO"].str[:4])[["LATITUD", "LONGITUD"]].median()
    return par_district, par_province


def positionner(grands, df_complet):
    """Ajoute LAT_CARTE, LON_CARTE et POSITION à chaque grand projet (voir la docstring du module)."""
    par_district, par_province = centres(df_complet)
    grands = grands.copy()
    valide = points_valides(grands)
    positions, lats, lons = [], [], []
    for i, p in grands.iterrows():
        ubigeo = str(p["UBIGEO"] or "")
        if valide[i]:
            point, position = (p["LATITUD"], p["LONGITUD"]), DECLAREE
        elif not lieu_precis(ubigeo, p["DEPARTAMENTO"]):
            point, position = (None, None), None
        elif not ubigeo.endswith("00") and ubigeo in par_district.index:
            point, position = tuple(par_district.loc[ubigeo]), APPROCHEE_DISTRICT
        elif not ubigeo.endswith("0000") and ubigeo[:4] in par_province.index:
            point, position = tuple(par_province.loc[ubigeo[:4]]), APPROCHEE_PROVINCE
        else:
            point, position = (None, None), None
        lats.append(point[0])
        lons.append(point[1])
        positions.append(position)
    grands["LAT_CARTE"], grands["LON_CARTE"], grands["POSITION"] = lats, lons, positions
    return grands


# ---------------------------------------------------------------- textes

def montant(soles):
    """« 350 M S/ » sous 1 milliard, « 1,7 Md S/ » au-dessus : la même unité que le seuil de 100 M."""
    return f"{fiche.fr(soles / 1e9, 1)} Md S/" if soles >= 1e9 else f"{fiche.fr(soles / 1e6, 0)} M S/"


def bulle(p, noms_courts, annee):
    """Texte qui s'ouvre quand on clique sur un cercle."""
    e = fiche.e
    nom = fiche.nom_court(p["CODIGO_UNICO"], p["NOMBRE_INVERSION"], noms_courts)
    lieu = f"{str(p['DEPARTAMENTO']).title()} / {str(p['PROVINCIA']).title()}"
    if p["POSITION"] == DECLAREE:
        precision = "point déclaré par l'entité"
    else:
        precision = f"position approchée : centre des projets du {p['POSITION'].split('(')[1].rstrip(')')}"
    situation = {"VIABLE": "déclaré viable", "APROBADO": "approuvé"}.get(p["SITUACION"], str(p["SITUACION"]).lower())
    dossier = "expediente técnico enregistré" if p["EXPEDIENTE_TECNICO"] == "SI" else "pas encore d'expediente técnico"
    credits = "" if fiche.budget_ou_depense(p) == "oui" else " ; aucun budget ni dépense à ce jour"
    return (f"<b>{e(nom)}</b><br>{e(p['SECTEUR_FICHE'])}, code MEF {e(p['CODIGO_UNICO'])}<br>"
            f"{e(lieu)} ({e(precision)})<br>{e(p['MODE_PUBLIC'])} ; {situation}, {dossier}<br>"
            f"Coût indicatif : {montant(p['COSTO_ACTUALIZADO'])}<br>"
            f"Budget {annee} : {fiche.montant_M(p['PIM_ANIO_ACTUAL'])} M S/{credits}")


def encadre(grands, jour, annee):
    """Légende fixée en bas à gauche. Elle commence par ce qui n'est PAS sur la carte."""
    cout_total = grands["COSTO_ACTUALIZADO"].sum()

    def bilan(masque):
        g = grands[masque]
        return len(g), fiche.fr(100 * g["COSTO_ACTUALIZADO"].sum() / cout_total, 0)

    n_dec, p_dec = bilan(grands["POSITION"] == DECLAREE)
    n_app, p_app = bilan(grands["POSITION"].isin([APPROCHEE_DISTRICT, APPROCHEE_PROVINCE]))
    n_abs, p_abs = bilan(grands["POSITION"].isna())
    reperes = "".join(
        f'<svg width="{2 * r + 2:.0f}" height="{2 * r + 2:.0f}" style="vertical-align:middle">'
        f'<circle cx="{r + 1:.1f}" cy="{r + 1:.1f}" r="{r:.1f}" fill="#999" fill-opacity=".35" stroke="#555"/></svg>'
        f"&nbsp;{texte}&nbsp; " for cout, texte in REPERES_TAILLE for r in [rayon(cout)])
    return f"""
    <div class="legende">
      <b>Grands projets d'investissement public au Pérou</b><br>
      Projets de 100 M S/ ou plus, fichier du MEF du {jour:%d/%m/%Y} : {fiche.fr(len(grands), 0)} projets.
      <div class="absents"><b>Absents de la carte : {fiche.fr(n_abs, 0)} projets, soit {p_abs} % du coût</b>,
      déclarés sur plusieurs départements ou sans lieu précis. Positions approchées : {fiche.fr(n_app, 0)} projets
      ({p_app} % du coût), placés au centre des projets de leur district ou de leur province (contour en pointillé).
      Points déclarés : {fiche.fr(n_dec, 0)} projets ({p_dec} % du coût). Une route ou une voie ferrée n'est
      représentée que par un point, et plusieurs projets peuvent partager le même point.</div>
      Taille selon le coût indicatif :<br>{reperes}<br>
      Cercle creux : ni budget {annee} ni dépense passée. Noms : intitulés du MEF, en espagnol, ou noms courts.
      <div class="source">Source : MEF, Banco de Inversiones (données ouvertes).</div>
    </div>"""


STYLE = """<style>
  .leaflet-tile-pane { filter: grayscale(100%) opacity(75%); }
  .legende { position: fixed; bottom: 52px; left: 12px; z-index: 1000; background: white; padding: 8px 10px;
             border: 1px solid #bbb; border-radius: 4px; font: 12px/1.4 Arial, sans-serif; max-width: 360px; }
  .legende .absents { margin: 5px 0; padding: 5px 7px; background: #fff4e0; border-left: 3px solid #A16F00; }
  .legende .source { margin-top: 5px; color: #555; }
  .leaflet-popup-content { font: 13px/1.45 Arial, sans-serif; }
  .leaflet-control-layers { font: 13px/1.5 Arial, sans-serif; }
  .pastille { display: inline-block; width: 11px; height: 11px; border-radius: 50%; margin: 0 5px 0 3px; vertical-align: -1px; }
  .leaflet-control-scale-line:nth-child(2) { display: none; }  /* on garde l'échelle en km, pas en miles */
  @media (max-width: 600px) { .legende { max-width: 62vw; font-size: 10px; } .leaflet-control-layers { font-size: 11px; } }
</style>"""


class OrdreParTaille(MacroElement):
    """Petit script exécuté dans le navigateur : remet les plus gros cercles derrière et les petits devant, tous
    secteurs confondus (folium dessine secteur par secteur), et recommence quand on recoche un secteur.
    Sans cela, des petits cercles d'un secteur restaient cachés sous les gros d'un autre secteur."""
    _template = Template("""{% macro script(this, kwargs) %}
    function ordonner_cercles() {
      var cercles = [];
      {{ this._parent.get_name() }}.eachLayer(function (couche) { if (couche instanceof L.CircleMarker) cercles.push(couche); });
      cercles.sort(function (a, b) { return b.getRadius() - a.getRadius(); });
      cercles.forEach(function (c) { c.bringToFront(); });
    }
    ordonner_cercles();
    {{ this._parent.get_name() }}.on("overlayadd", ordonner_cercles);
    {{ this._parent.get_name() }}.attributionControl.setPrefix('<a href="https://leafletjs.com">Leaflet</a>');
    {% endmacro %}""")


def contour(couleur):
    """Contour 30 % plus foncé que la couleur de remplissage, pour que les cercles creux ressortent sur le fond gris."""
    return "#" + "".join(f"{int(int(couleur[i:i + 2], 16) * 0.7):02X}" for i in (1, 3, 5))


# ---------------------------------------------------------------- carte

def dessiner(grands, df_complet, noms_courts, jour, annee):
    grands = positionner(grands, df_complet)
    sur_carte = grands[grands["POSITION"].notna()].sort_values("COSTO_ACTUALIZADO", ascending=False)
    carte = folium.Map(location=[-9.2, -75.0], zoom_start=6, tiles=None, control_scale=True)
    # Seules Leaflet et jQuery sont utiles : on retire les autres bibliothèques que folium charge par défaut.
    carte.default_js = [(nom, url) for nom, url in carte.default_js if nom in ("leaflet", "jquery")]
    carte.default_css = [(nom, url) for nom, url in carte.default_css if nom == "leaflet_css"]
    folium.TileLayer("OpenStreetMap", control=False).add_to(carte)  # fond libre, sans clé
    carte.get_root().header.add_child(folium.Element(
        f"<title>Grands projets publics au Pérou, carte du {jour:%d/%m/%Y}</title>{STYLE}"))

    groupes = {}
    for secteur, couleur in COULEURS.items():
        n = (sur_carte["SECTEUR_FICHE"] == secteur).sum()
        if n:
            nom = f'<span class="pastille" style="background:{couleur}"></span>{secteur} ({n})'
            groupes[secteur] = folium.FeatureGroup(name=nom).add_to(carte)

    for _, p in sur_carte.iterrows():
        secteur = p["SECTEUR_FICHE"] if p["SECTEUR_FICHE"] in COULEURS else "Non classé"
        couleur = COULEURS[secteur]
        sans_credits = fiche.budget_ou_depense(p) == "non"
        nom = fiche.nom_court(p["CODIGO_UNICO"], p["NOMBRE_INVERSION"], noms_courts)
        folium.CircleMarker(
            location=[p["LAT_CARTE"], p["LON_CARTE"]], radius=rayon(p["COSTO_ACTUALIZADO"]),
            color=contour(couleur), weight=2 if sans_credits else 1.5,
            dash_array=None if p["POSITION"] == DECLAREE else "4 3",
            fill=True, fill_color=couleur, fill_opacity=0.0 if sans_credits else 0.5,
            tooltip=fiche.e(f"{nom} ({p['CODIGO_UNICO']}, {p['MODE_PUBLIC']})"),
            popup=folium.Popup(bulle(p, noms_courts, annee), max_width=340),
        ).add_to(groupes.get(secteur, carte))

    folium.LayerControl(collapsed=False).add_to(carte)
    OrdreParTaille().add_to(carte)
    carte.get_root().html.add_child(folium.Element(encadre(grands, jour, annee)))
    return carte, grands


def ecrire(carte, chemin):
    """Enregistre la carte. folium donne des identifiants aléatoires à chaque élément : on les remplace par des
    numéros, pour que deux générations sur les mêmes données donnent exactement le même fichier."""
    carte.save(chemin)
    texte = chemin.read_text(encoding="utf-8")
    numeros = {}
    texte = re.sub(r"(?<=_)[0-9a-f]{32}(?![0-9a-f])", lambda m: numeros.setdefault(m.group(0), f"{len(numeros):x}"), texte)
    chemin.write_text(texte, encoding="utf-8")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    archives = ch.lister_archives()
    jour = max(archives)
    brut = pd.read_parquet(archives[jour])
    # Le taux de change ne sert pas à la carte (montants en soles) : on passe 1 pour ne pas interroger la BCRP.
    grands = ind.calculer(brut, taux=1.0)["grands"]
    df_complet, _ = ind.nettoyer(ind.harmoniser_cout(ind.retirer_doublons(brut)[0])[0])
    carte, grands = dessiner(grands, df_complet, fiche.lire_noms(fiche.NOMS_COURTS, "CODIGO_UNICO"), jour, jour.year)

    ind.SORTIE_DIR.mkdir(exist_ok=True)
    sortie = ind.SORTIE_DIR / f"carte_{jour.isoformat()}.html"
    ecrire(carte, sortie)
    print(grands["POSITION"].fillna("absent de la carte").value_counts().to_string())
    print(f"-> {sortie}")


if __name__ == "__main__":
    main()
