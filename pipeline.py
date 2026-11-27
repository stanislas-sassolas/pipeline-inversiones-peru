"""Lance tout le pipeline d'un coup, dans l'ordre des étapes.

1. archiver.py      : archive la nouvelle version du fichier du MEF, s'il y en a une (étape 0)
2. indicateurs.py   : indicateurs des grands projets, exports/indicateurs_<date>.xlsx (étape 2)
3. changements.py   : ce qui a bougé depuis au moins 7 jours, exports/changements_<...>.xlsx (étape 3)
4. proinversion.py  : consultations de ProInversión, une fois par jour (étape 4)
5. fiche.py         : fiche de deux pages, exports/fiche_<date>.pdf (étape 5)
6. carte.py         : carte interactive, exports/carte_<date>.html (étape 6)
7. note.py          : note épurée de trois pages, exports/note_<date>.pdf (étape 7)
Avec --publier, copie ensuite la note, la carte, la fiche (si elle n'est pas un brouillon) et des captures
d'écran dans docs/, le dossier que GitHub Pages sert comme site web, et y écrit la page d'accueil en français
(docs/index.html) et en espagnol (docs/es.html).

Lancement : python pipeline.py                  (tout)
            python pipeline.py --sans-archivage (sans télécharger le fichier du MEF)
            python pipeline.py --publier        (tout, puis mise à jour de docs/)
"""

import shutil
import subprocess
import sys
from pathlib import Path

import archiver
import carte
import changements
import fiche
import indicateurs
import note
import proinversion

DOCS = Path(__file__).parent / "docs"
# Adresse publique du dépôt (à adapter si le compte GitHub change).
DEPOT = "https://github.com/stanislas-sassolas/pipeline-inversiones-peru"


def capture(page, png, largeur, hauteur):
    """Capture d'écran d'une page HTML avec Chrome sans interface (le temps de charger la carte et ses tuiles)."""
    subprocess.run([str(fiche.CHROME), "--headless=new", "--disable-gpu", "--hide-scrollbars", "--virtual-time-budget=15000",
                    f"--window-size={largeur},{hauteur}", f"--screenshot={png}", page.resolve().as_uri()],
                   check=True, capture_output=True, timeout=120)


def capture_note(note_html, png):
    """Aperçu de la page 1 de la note, avec ses marges, comme une feuille A4 (794 x 1123 px)."""
    page = note_html.read_text(encoding="utf-8").replace(
        "</head>", "<style>body{padding:16mm 20mm 0;background:#fff}.page~.page{display:none}</style></head>")
    temporaire = note_html.with_name("note_apercu.html")
    temporaire.write_text(page, encoding="utf-8")
    capture(temporaire, png, 794, 1123)
    temporaire.unlink(missing_ok=True)


def publier():
    """Met à jour docs/ avec les dernières sorties : la note épurée (si elle a été produite), la carte, et la fiche
    dense (seulement si son texte « À retenir » est écrit)."""
    jour = max(changements.lister_archives()).isoformat()
    sorties = indicateurs.SORTIE_DIR
    (DOCS / "images").mkdir(parents=True, exist_ok=True)

    carte_html = sorties / f"carte_{jour}.html"
    shutil.copyfile(carte_html, DOCS / "carte.html")
    capture(carte_html, DOCS / "images" / "carte.png", 1366, 900)
    # Sans Internet, Chrome rend une carte sans fond ni cercles : une image normale fait environ 500 ko.
    if (DOCS / "images" / "carte.png").stat().st_size < 100_000:
        print("Attention : capture de la carte suspecte (fond de carte non chargé ? Internet est nécessaire).")

    note_pdf = sorties / f"note_{jour}.pdf"
    note_publiee = note_pdf.exists()
    if note_publiee:
        shutil.copyfile(note_pdf, DOCS / "note.pdf")
        capture_note(sorties / f"note_{jour}.html", DOCS / "images" / "note.png")
    else:
        (DOCS / "note.pdf").unlink(missing_ok=True)
        (DOCS / "images" / "note.png").unlink(missing_ok=True)

    fiche_pdf = sorties / f"fiche_{jour}.pdf"
    fiche_publiee = fiche_pdf.exists()  # sinon, seule la version « _brouillon » existe
    if fiche_publiee:
        shutil.copyfile(fiche_pdf, DOCS / "fiche.pdf")
    else:
        # Une fiche publiée plus tôt ne doit pas rester en ligne à côté de données plus récentes.
        (DOCS / "fiche.pdf").unlink(missing_ok=True)
    (DOCS / "images" / "fiche.png").unlink(missing_ok=True)
    for langue, textes in TEXTES.items():
        (DOCS / textes["fichier"]).write_text(page_accueil(jour, note_publiee, fiche_publiee, langue), encoding="utf-8")
    print(f"docs/ mis à jour (données du {jour} ; note : {'oui' if note_publiee else 'non'} ; "
          f"fiche dense : {'oui' if fiche_publiee else 'non, texte À retenir à écrire'}).")


# Adresse du portfolio, pour le lien de retour (la version espagnole s'ouvre avec ?lang=es).
PORTFOLIO = "https://stanislas-sassolas.github.io/"

STYLE = """
  body { font: 17px/1.6 Georgia, "DejaVu Serif", "Times New Roman", serif; color: #141414; background: #fff;
         max-width: 820px; margin: 0 auto; padding: 32px 16px 48px; }
  .langues { font-size: 14px; text-align: right; margin: 0 0 18px; }
  .surtitre { font-size: 12px; letter-spacing: 0.14em; text-transform: uppercase; color: #2b3f6b; margin: 0 0 10px; }
  h1 { font-size: 38px; line-height: 1.08; font-weight: normal; margin: 0 0 14px; letter-spacing: -0.01em; }
  h2 { font-size: 24px; font-weight: normal; margin: 40px 0 14px; padding-top: 10px; border-top: 1px solid #222; }
  a { color: #2b3f6b; }
  .auteur { font-size: 15px; color: #444; margin: 0 0 18px; }
  .note-bloc { display: grid; grid-template-columns: 300px 1fr; gap: 28px; align-items: start; }
  .note-bloc img { width: 100%; border: 1px solid #ddd; box-shadow: 0 2px 10px rgba(0,0,0,0.08); }
  .but { margin: 0 0 14px; }
  .lien { font-size: 18px; margin-top: 18px; }
  .carte img { width: 100%; border: 1px solid #ddd; }
  .petit { font-size: 15px; color: #444; }
  @media (max-width: 640px) { .note-bloc { grid-template-columns: 1fr; } h1 { font-size: 30px; } }
"""

# Les textes de la page d'accueil, en français (docs/index.html) et en espagnol (docs/es.html).
TEXTES = {
    "fr": {
        "fichier": "index.html",
        "titre": "Grands projets d'investissement public au Pérou",
        "langues": '<a href="es.html" hreflang="es" lang="es">Versión en español</a>',
        "surtitre": "Investissement public au Pérou",
        "auteur": ("Projet personnel de Stanislas Sassolas, élève-ingénieur (CPE Lyon), sans lien avec aucune "
                   f'administration. <a href="{PORTFOLIO}">Retour au portfolio</a>'),
        "intro": """Le ministère de l'Économie et des Finances du Pérou (MEF) publie chaque jour, en données ouvertes, la liste de ses
investissements publics actifs, environ 150 000. Ce pipeline de données en Python archive chaque version du fichier,
calcule des indicateurs sur les projets de 100 millions de soles ou plus, repère ce qui change d'une semaine à
l'autre, suit les consultations de ProInversión, et en tire une note et une carte.""",
        "note": """
<h2>La note : deux générations de grands projets</h2>
<div class="note-bloc">
  <a href="note.pdf"><img src="images/note.png" alt="Première page de la note"></a>
  <div>
    <p class="but"><b>Le but de cette note.</b> Répondre en cinq minutes à une question simple : dans l'investissement
    public péruvien, où va l'argent aujourd'hui, et où seront les projets de demain ? Elle s'adresse aux entreprises
    et aux observateurs qui veulent une image claire du paysage, sans jargon.</p>
    <p class="but"><b>En une phrase.</b> Le budget de cette année finance surtout des chantiers déclarés viables il y a
    près de neuf ans, alors que la vague suivante, plus de la moitié du coût, est encore sur plans et tient dans une
    dizaine de très gros projets, dont plusieurs trains et métros.</p>
    <p class="but"><b>Ce qu'elle n'est pas.</b> Ni une analyse complète (elle ne dit rien des contrats, des entreprises
    ni du contexte politique), ni une recommandation, ni un document officiel. Elle s'en tient à ce que montre le
    fichier du MEF, et elle est recalculée automatiquement à chaque nouvelle version.</p>
    <p class="lien"><a href="note.pdf">Lire la note (PDF, 3 pages)</a></p>
  </div>
</div>""",
        "carte": """<h2>La carte des grands projets</h2>
<div class="carte"><a href="carte.html"><img src="images/carte.png" alt="Carte des grands projets"></a></div>
<p><a href="carte.html">Ouvrir la carte interactive</a> : chaque cercle est un projet, sa taille suit le coût, sa
couleur le secteur.</p>""",
        "fiche": '<p>Une fiche plus dense, avec tous les indicateurs : <a href="fiche.pdf">fiche de deux pages (PDF)</a>.</p>',
        "methode": f"""<h2>Méthode et limites</h2>
<ul class="petit">
  <li>Le coût affiché est un coût pluriannuel indicatif, pas un engagement : l'effort de l'année se lit dans le budget
  (PIM) et la dépense exécutée (devengado).</li>
  <li>Le fichier ne couvre que l'investissement public : ni les projets miniers privés, ni le financement privé des
  partenariats public-privé.</li>
  <li>Les contrôles de qualité (doublons, valeurs impossibles, changements de format du fichier source) et toutes les
  règles de calcul sont décrits dans le <a href="{DEPOT}">code source et sa documentation</a>.</li>
</ul>

<h2>Sources</h2>
<p class="petit">MEF, Banco de Inversiones (données ouvertes) ; BCRP, taux de change ; ProInversión, investinperu.pe.
Fond de carte : © contributeurs OpenStreetMap.</p>""",
    },
    "es": {
        "fichier": "es.html",
        "titre": "Grandes proyectos de inversión pública en el Perú",
        "langues": '<a href="index.html" hreflang="fr" lang="fr">Version française</a>',
        "surtitre": "Inversión pública en el Perú",
        "auteur": ("Proyecto personal de Stanislas Sassolas, estudiante de ingeniería (CPE Lyon), sin vínculo con "
                   f'ninguna institución. <a href="{PORTFOLIO}?lang=es">Volver al portafolio</a>'),
        "intro": """El Ministerio de Economía y Finanzas del Perú (MEF) publica cada día, en datos abiertos, la lista de sus
inversiones públicas activas, unas 150 000. Este pipeline de datos en Python archiva cada versión del archivo,
calcula indicadores sobre los proyectos de S/ 100 millones o más, detecta lo que cambia de una semana a otra,
sigue las convocatorias de ProInversión y genera una nota y un mapa.""",
        "note": """
<h2>La nota: dos generaciones de grandes proyectos</h2>
<div class="note-bloc">
  <a href="note.pdf"><img src="images/note.png" alt="Primera página de la nota (en francés)"></a>
  <div>
    <p class="but"><b>El objetivo de la nota.</b> Responder en cinco minutos a una pregunta sencilla: en la inversión
    pública peruana, ¿a dónde va el dinero hoy y dónde estarán los proyectos de mañana? Está pensada para empresas
    y observadores que buscan una visión clara del panorama, sin jerga.</p>
    <p class="but"><b>En una frase.</b> El presupuesto de este año financia sobre todo obras declaradas viables hace
    casi nueve años, mientras que la siguiente ola, más de la mitad del costo, sigue en papel y se concentra en una
    decena de proyectos muy grandes, entre ellos varios trenes y líneas de metro.</p>
    <p class="but"><b>Lo que no es.</b> Ni un análisis completo (no dice nada de los contratos, las empresas ni el
    contexto político), ni una recomendación, ni un documento oficial. Se limita a lo que muestra el archivo del MEF
    y se recalcula automáticamente con cada nueva versión.</p>
    <p class="lien"><a href="note.pdf">Leer la nota (PDF, 3 páginas)</a> (en francés)</p>
  </div>
</div>""",
        "carte": """<h2>El mapa de los grandes proyectos</h2>
<div class="carte"><a href="carte.html"><img src="images/carte.png" alt="Mapa de los grandes proyectos"></a></div>
<p><a href="carte.html">Abrir el mapa interactivo</a> (leyenda en francés): cada círculo es un proyecto, su tamaño
sigue el costo y su color, el sector.</p>""",
        "fiche": ('<p>Una ficha más densa, con todos los indicadores: <a href="fiche.pdf">ficha de dos páginas (PDF)</a> '
                  "(en francés).</p>"),
        "methode": f"""<h2>Método y límites</h2>
<ul class="petit">
  <li>El costo mostrado es un costo plurianual indicativo, no un compromiso de gasto: el esfuerzo del año se lee en
  el presupuesto (PIM) y en el gasto ejecutado (devengado).</li>
  <li>El archivo solo cubre la inversión pública: ni la minería privada ni el financiamiento privado de las
  asociaciones público-privadas (APP).</li>
  <li>Los controles de calidad (duplicados, valores imposibles, cambios de formato del archivo fuente) y todas las
  reglas de cálculo se describen en el <a href="{DEPOT}/blob/main/README.es.md">código fuente y su documentación</a>.</li>
</ul>

<h2>Fuentes</h2>
<p class="petit">MEF, Banco de Inversiones (datos abiertos); BCRP, tipo de cambio; ProInversión, investinperu.pe.
Mapa base: © colaboradores de OpenStreetMap.</p>""",
    },
}


def page_accueil(jour, note_publiee, fiche_publiee, langue="fr"):
    """Page d'accueil du site, en français ou en espagnol : la note et son but d'abord, puis la carte, la méthode et
    les sources. La note et la fiche restent en français."""
    t = TEXTES[langue]
    return f"""<!DOCTYPE html>
<html lang="{langue}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{t["titre"]}</title>
<link rel="alternate" hreflang="fr" href="index.html">
<link rel="alternate" hreflang="es" href="es.html">
<style>{STYLE}</style>
</head>
<body>
<p class="langues">{t["langues"]}</p>
<p class="surtitre">{t["surtitre"]}</p>
<h1>{t["titre"]}</h1>
<p class="auteur">{t["auteur"]}</p>

<p>{t["intro"]}</p>
{t["note"] if note_publiee else ""}

{t["carte"]}
{t["fiche"] if fiche_publiee else ""}

{t["methode"]}
</body>
</html>
"""


def main(arguments):
    sys.stdout.reconfigure(encoding="utf-8")
    if "--sans-archivage" not in arguments:
        archiver.main()
    # Comparer deux versions demande deux archives de jours différents : le premier jour, il n'y en a qu'une.
    archives = changements.lister_archives()
    if len(archives) < 2:
        raise SystemExit(f"{len(archives)} archive(s) dans {archiver.SNAP_DIR} : il en faut deux, de deux jours "
                         "différents. Lancer python archiver.py un jour, puis python pipeline.py le lendemain.")
    indicateurs.main()
    changements.main([])
    proinversion.main()
    fiche.main()
    carte.main()
    note.main()
    if "--publier" in arguments:
        publier()


if __name__ == "__main__":
    main(sys.argv[1:])
