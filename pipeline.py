"""Lance tout le pipeline d'un coup, dans l'ordre des étapes.

1. archiver.py      : archive la nouvelle version du fichier du MEF, s'il y en a une (étape 0)
2. indicateurs.py   : indicateurs des grands projets, exports/indicateurs_<date>.xlsx (étape 2)
3. changements.py   : ce qui a bougé depuis au moins 7 jours, exports/changements_<...>.xlsx (étape 3)
4. proinversion.py  : consultations de ProInversión, une fois par jour (étape 4)
5. fiche.py         : fiche de deux pages, exports/fiche_<date>.pdf (étape 5)
6. carte.py         : carte interactive, exports/carte_<date>.html (étape 6)
Avec --publier, copie ensuite la carte, la fiche (si elle n'est pas un brouillon) et deux captures d'écran dans
docs/, le dossier que GitHub Pages sert comme site web, et y écrit la page d'accueil docs/index.html.

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
import proinversion

DOCS = Path(__file__).parent / "docs"
# Adresse publique du dépôt (à adapter si le compte GitHub change).
DEPOT = "https://github.com/stanislas-sassolas/pipeline-inversiones-peru"


def capture(page, png, largeur, hauteur):
    """Capture d'écran d'une page HTML avec Chrome sans interface (le temps de charger la carte et ses tuiles)."""
    subprocess.run([str(fiche.CHROME), "--headless=new", "--disable-gpu", "--hide-scrollbars", "--virtual-time-budget=15000",
                    f"--window-size={largeur},{hauteur}", f"--screenshot={png}", page.resolve().as_uri()],
                   check=True, capture_output=True, timeout=120)


def publier():
    """Met à jour docs/ avec les dernières sorties. La fiche n'est publiée que si sa lecture est écrite."""
    jour = max(changements.lister_archives()).isoformat()
    sorties = indicateurs.SORTIE_DIR
    (DOCS / "images").mkdir(parents=True, exist_ok=True)

    carte_html = sorties / f"carte_{jour}.html"
    shutil.copyfile(carte_html, DOCS / "carte.html")
    capture(carte_html, DOCS / "images" / "carte.png", 1366, 900)
    # Sans Internet, Chrome rend une carte sans fond ni cercles : une image normale fait environ 500 ko.
    if (DOCS / "images" / "carte.png").stat().st_size < 100_000:
        print("Attention : capture de la carte suspecte (fond de carte non chargé ? Internet est nécessaire).")

    fiche_pdf = sorties / f"fiche_{jour}.pdf"
    fiche_publiee = fiche_pdf.exists()  # sinon, seule la version « _brouillon » existe
    if fiche_publiee:
        shutil.copyfile(fiche_pdf, DOCS / "fiche.pdf")
        # Capture de la page 1 : la page HTML de la fiche, à la largeur d'une feuille A4 (794 px).
        capture(sorties / f"fiche_{jour}.html", DOCS / "images" / "fiche.png", 794, 1123)
    else:
        # Une fiche publiée plus tôt ne doit pas rester en ligne à côté de données plus récentes.
        (DOCS / "fiche.pdf").unlink(missing_ok=True)
        (DOCS / "images" / "fiche.png").unlink(missing_ok=True)
    (DOCS / "index.html").write_text(page_accueil(jour, fiche_publiee), encoding="utf-8")
    print(f"docs/ mis à jour (données du {jour}{', fiche comprise' if fiche_publiee else ', sans la fiche : lecture à écrire'}).")


def page_accueil(jour, fiche_publiee):
    """Page d'accueil du site : ce que fait le projet, liens vers la carte et la fiche, méthode et limites."""
    bloc_fiche = ('<a href="fiche.pdf"><img src="images/fiche.png" alt="Page 1 de la fiche"></a>'
                  '<p><a href="fiche.pdf">Fiche de deux pages (PDF)</a></p>' if fiche_publiee
                  else "<p>La fiche de deux pages est en préparation.</p>")
    return f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Grands projets d'investissement public au Pérou</title>
<style>
  body {{ font: 16px/1.55 Arial, Helvetica, sans-serif; color: #1a1a1a; max-width: 860px; margin: 0 auto; padding: 24px 16px; }}
  h1 {{ color: #1f3a5f; font-size: 26px; margin-bottom: 4px; }}
  h2 {{ color: #1f3a5f; font-size: 19px; margin-top: 28px; }}
  .note {{ color: #555; font-size: 14px; }}
  .sorties {{ display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }}
  .sorties img {{ width: 100%; border: 1px solid #ccc; }}
  @media (max-width: 640px) {{ .sorties {{ grid-template-columns: 1fr; }} }}
</style>
</head>
<body>
<h1>Grands projets d'investissement public au Pérou</h1>
<p class="note">Projet personnel de Stanislas Sassolas, élève-ingénieur (CPE Lyon), non affilié à la DG Trésor ni à aucune administration.
Données du {jour[8:]}/{jour[5:7]}/{jour[:4]}.</p>

<p>Le ministère de l'Économie et des Finances du Pérou (MEF) publie chaque jour, en données ouvertes, la liste de ses
investissements publics actifs (environ 150 000). Ce pipeline de données en Python archive les versions successives
du fichier, calcule des indicateurs sur les projets de 100 millions de soles ou plus (secteur, mode de réalisation,
budget de l'année et exécution), repère ce qui change d'une semaine à l'autre, suit les consultations de ProInversión,
et produit une fiche de deux pages et une carte.</p>

<div class="sorties">
  <div><a href="carte.html"><img src="images/carte.png" alt="Carte des grands projets"></a>
  <p><a href="carte.html">Carte interactive des grands projets</a></p></div>
  <div>{bloc_fiche}</div>
</div>

<h2>Méthode et limites</h2>
<ul>
  <li>Le coût affiché est un coût pluriannuel indicatif, pas un engagement : l'effort de l'année se lit dans le budget
  (PIM) et la dépense exécutée (devengado).</li>
  <li>Le fichier ne couvre que les investissements publics qui ont un code : ni les projets miniers privés, ni les
  partenariats public-privé encore trop peu avancés pour avoir un code.</li>
  <li>Les contrôles de qualité (doublons, valeurs impossibles, changements de format du fichier source) et toutes les
  règles de calcul sont décrits dans le <a href="{DEPOT}">code source et sa documentation</a>.</li>
</ul>

<h2>Sources</h2>
<p>MEF, Banco de Inversiones (données ouvertes) ; BCRP, taux de change ; ProInversión, investinperu.pe.
Fond de carte : © contributeurs OpenStreetMap.</p>
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
    if "--publier" in arguments:
        publier()


if __name__ == "__main__":
    main(sys.argv[1:])
