"""Étape 0 : archiver chaque jour le Banco de Inversiones du MEF (Pérou).

Ce que fait le script, dans l'ordre :
1. Demande au serveur du MEF la date de dernière mise à jour du fichier.
2. Si le fichier n'a pas changé depuis la dernière archive, il s'arrête.
3. Sinon, il télécharge le CSV (environ 250 Mo) dans un fichier temporaire.
4. Il le lit, enlève la colonne ALTERNATIVA (longs textes techniques inutiles
   pour nous) et range les montants en nombres.
5. Il l'enregistre au format Parquet (compressé, environ 10 fois plus petit)
   sous le nom inversiones_AAAA-MM-JJ.parquet, puis supprime le CSV.
6. Il ajoute une ligne au journal snapshots.csv (date, nombre de projets...).

Lancement : python archiver.py
            pythonw archiver.py --journal <fichier>   (sans fenêtre, messages écrits dans le fichier :
                                                     c'est ainsi que la tâche planifiée le lance)
"""

import csv
import os
import sys
import tempfile
import urllib.request
from datetime import datetime
from email.utils import parsedate_to_datetime
from pathlib import Path

import pandas as pd

URL = "https://fs.datosabiertos.mef.gob.pe/datastorefiles/DETALLE_INVERSIONES.csv"

# Les données restent hors du dépôt (plusieurs centaines de Mo au bout d'un mois) : par défaut dans le dossier
# personnel de l'utilisateur, sous data/inversiones-peru, ou là où l'indique la variable INVERSIONES_DATA.
DATA_DIR = Path(os.environ.get("INVERSIONES_DATA", Path.home() / "data" / "inversiones-peru"))
SNAP_DIR = DATA_DIR / "snapshots"
JOURNAL = DATA_DIR / "snapshots.csv"

COLONNES_A_RETIRER = ["ALTERNATIVA"]

# Colonnes de montants (en soles) et de pourcentages, à convertir en nombres.
COLONNES_NUMERIQUES = [
    "MONTO_VIABLE", "COSTO_ACTUALIZADO", "CTRL_CONCURR", "MONTO_LAUDO", "MONTO_FIANZA",
    "PMI_ANIO_1", "PMI_ANIO_2", "PMI_ANIO_3", "PMI_ANIO_4",
    "DEVEN_ACUMUL_ANIO_ANT", "DEV_ANIO_ACTUAL", "PIA_ANIO_ACTUAL", "PIM_ANIO_ACTUAL",
    "CERTIF_ANIO_ACTUAL", "COMPROM_ANUAL_ANIO_ACTUAL", "SALDO_EJECUTAR",
    "AVANCE_FISICO", "AVANCE_EJECUCION", "LATITUD", "LONGITUD",
    "NUM_HABITANTES_BENEF", "MONTO_ET_F8",
]


def derniere_mise_a_jour_serveur():
    """Lit l'en-tête HTTP Last-Modified sans télécharger le fichier."""
    req = urllib.request.Request(URL, method="HEAD")
    with urllib.request.urlopen(req, timeout=60) as r:
        return parsedate_to_datetime(r.headers["Last-Modified"]), int(r.headers["Content-Length"])


def derniere_archive():
    """Renvoie la dernière ligne du journal, ou None s'il n'y a encore rien."""
    if not JOURNAL.exists():
        return None
    with open(JOURNAL, encoding="utf-8") as f:
        lignes = list(csv.DictReader(f))
    return lignes[-1] if lignes else None


def telecharger(destination: Path):
    """Télécharge le CSV par blocs de 1 Mo, pour ne pas charger 250 Mo en mémoire d'un coup."""
    with urllib.request.urlopen(URL, timeout=600) as r, open(destination, "wb") as f:
        while True:
            bloc = r.read(1024 * 1024)
            if not bloc:
                break
            f.write(bloc)


def ecrire_les_messages_dans(chemin):
    """Lancé sans fenêtre (pythonw), le script n'a pas de console : ses messages et ses erreurs
    iraient nulle part. On les envoie donc à la fin du fichier journal."""
    journal = open(chemin, "a", encoding="utf-8", buffering=1)  # buffering=1 : écrit ligne par ligne
    sys.stdout = sys.stderr = journal


def main():
    SNAP_DIR.mkdir(parents=True, exist_ok=True)
    print(f"--- {datetime.now():%d/%m/%Y %H:%M} ---")

    maj_serveur, taille = derniere_mise_a_jour_serveur()
    precedente = derniere_archive()
    if precedente and precedente["maj_serveur"] == maj_serveur.isoformat():
        print(f"Rien de nouveau : le fichier du MEF date toujours du {maj_serveur:%d/%m/%Y %H:%M}.")
        return 0

    print(f"Nouvelle version du MEF ({maj_serveur:%d/%m/%Y %H:%M}, {taille / 1e6:.0f} Mo) : téléchargement...")
    with tempfile.TemporaryDirectory(dir=DATA_DIR) as tmp:
        brut = Path(tmp) / "DETALLE_INVERSIONES.csv"
        telecharger(brut)

        # Tout est lu en texte d'abord, pour ne pas abîmer les codes (ex. UBIGEO "010101").
        df = pd.read_csv(brut, dtype=str, encoding="utf-8-sig", keep_default_na=False)

    df = df.drop(columns=[c for c in COLONNES_A_RETIRER if c in df.columns])
    for col in COLONNES_NUMERIQUES:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col].replace("", None), errors="coerce")

    # Le nom du fichier porte la date de mise à jour du MEF, pas la date du jour.
    jour = maj_serveur.date().isoformat()
    sortie = SNAP_DIR / f"inversiones_{jour}.parquet"
    df.to_parquet(sortie, index=False)

    nouveau_journal = not JOURNAL.exists()
    with open(JOURNAL, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if nouveau_journal:
            w.writerow(["archive_le", "maj_serveur", "fichier", "nb_projets", "nb_colonnes", "taille_parquet_mo"])
        w.writerow([
            datetime.now().isoformat(timespec="seconds"), maj_serveur.isoformat(), sortie.name,
            len(df), df.shape[1], round(sortie.stat().st_size / 1e6, 1),
        ])

    print(f"Archivé : {sortie.name} ({len(df):,} investissements, {sortie.stat().st_size / 1e6:.1f} Mo).")
    return 0


if __name__ == "__main__":
    if "--journal" in sys.argv:
        ecrire_les_messages_dans(sys.argv[sys.argv.index("--journal") + 1])
    sys.exit(main())
