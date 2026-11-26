"""Exporte les grands projets de la dernière archive dans un fichier Excel, pour les regarder à la main.

Onglet « grands_projets » : les projets dont le coût (COSTO_ACTUALIZADO + CTRL_CONCURR) atteint le seuil (100 M de soles par défaut),
du plus cher au moins cher, avec les colonnes les plus utiles en premier puis toutes les autres.
Onglet « colonnes » : pour chaque colonne, le taux de remplissage, le nombre de valeurs différentes
et trois exemples. C'est le point de départ du dictionnaire des colonnes (étape 1).

Lancement : python export_excel.py            (seuil 100 M de soles)
            python export_excel.py 500        (seuil 500 M de soles)
"""

import re
import sys
from pathlib import Path

import pandas as pd

import indicateurs
from archiver import SNAP_DIR

SORTIE_DIR = Path(__file__).parent / "exports"
DICTIONNAIRE = Path(__file__).parent / "dictionnaire_colonnes.md"


def lire_dictionnaire():
    """Récupère la définition de chaque colonne dans les tableaux de dictionnaire_colonnes.md."""
    definitions = {}
    if not DICTIONNAIRE.exists():
        return definitions
    for ligne in DICTIONNAIRE.read_text(encoding="utf-8").splitlines():
        m = re.match(r"\|\s*(`[A-Z0-9_]+`(?:\s*(?:,|à)\s*`[A-Z0-9_]+`)*)\s*\|\s*([^|]+)\|", ligne)
        if not m:
            continue
        texte = re.sub(r"\*\*|`", "", m.group(2)).strip()
        cols = re.findall(r"`([A-Z0-9_]+)`", m.group(1))
        # « `PMI_ANIO_1` à `PMI_ANIO_4` » couvre aussi les années 2 et 3.
        intervalle = re.match(r"(.*_)(\d+)$", cols[0]), re.match(r"(.*_)(\d+)$", cols[-1])
        if " à " in m.group(1) and all(intervalle) and intervalle[0].group(1) == intervalle[1].group(1):
            debut, fin = int(intervalle[0].group(2)), int(intervalle[1].group(2))
            cols = [f"{intervalle[0].group(1)}{i}" for i in range(debut, fin + 1)]
        for col in cols:
            definitions[col] = texte
    return definitions

COLONNES_CLES = [
    "CODIGO_UNICO", "NOMBRE_INVERSION", "NIVEL", "SECTOR", "ENTIDAD", "FUNCION",
    "DEPARTAMENTO", "PROVINCIA", "SITUACION", "COSTO_ACTUALIZADO", "MONTO_VIABLE",
    "EXPEDIENTE_TECNICO", "DES_MODALIDAD", "TIPO_INVERSION", "MARCO",
    "PIM_ANIO_ACTUAL", "DEV_ANIO_ACTUAL", "DEVEN_ACUMUL_ANIO_ANT", "AVANCE_FISICO",
    "AVANCE_EJECUCION", "IND_IOARR_EMERG", "FECHA_VIABILIDAD", "FEC_INI_EJECUCION",
    "FEC_FIN_EJECUCION", "LATITUD", "LONGITUD",
]
COLONNES_MONTANTS = [
    "COSTO_ACTUALIZADO", "MONTO_VIABLE", "PIM_ANIO_ACTUAL", "DEV_ANIO_ACTUAL",
    "DEVEN_ACUMUL_ANIO_ANT", "PIA_ANIO_ACTUAL", "CERTIF_ANIO_ACTUAL",
    "COMPROM_ANUAL_ANIO_ACTUAL", "SALDO_EJECUTAR", "MONTO_ET_F8", "MONTO_LAUDO",
    "MONTO_FIANZA", "CTRL_CONCURR", "PMI_ANIO_1", "PMI_ANIO_2", "PMI_ANIO_3", "PMI_ANIO_4",
]


def profil_colonnes(df):
    definitions = lire_dictionnaire()
    lignes = []
    for col in df.columns:
        s = df[col]
        remplies = s.notna() & (s.astype(str).str.strip() != "")
        exemples = s[remplies].astype(str).drop_duplicates().head(3).str.slice(0, 80).tolist()
        lignes.append({
            "colonne": col,
            "rempli_%": round(100 * remplies.mean(), 1),
            "valeurs_distinctes": s[remplies].nunique(),
            "exemple_1": exemples[0] if len(exemples) > 0 else "",
            "exemple_2": exemples[1] if len(exemples) > 1 else "",
            "exemple_3": exemples[2] if len(exemples) > 2 else "",
            "ma_definition": definitions.get(col, ""),
        })
    return pd.DataFrame(lignes)


def main(seuil_millions=100):
    archive = sorted(SNAP_DIR.glob("inversiones_*.parquet"))[-1]
    # Même préparation que le reste du pipeline : doublons retirés, contrôle concomitant ajouté au coût.
    df, _ = indicateurs.harmoniser_cout(indicateurs.retirer_doublons(pd.read_parquet(archive))[0])
    grands = df[df["COSTO_ACTUALIZADO"] >= seuil_millions * 1e6].sort_values("COSTO_ACTUALIZADO", ascending=False)
    ordre = [c for c in COLONNES_CLES if c in grands.columns] + [c for c in grands.columns if c not in COLONNES_CLES]
    grands = grands[ordre]

    SORTIE_DIR.mkdir(exist_ok=True)
    jour = archive.stem.replace("inversiones_", "")
    sortie = SORTIE_DIR / f"grands_projets_{seuil_millions}M_{jour}.xlsx"

    with pd.ExcelWriter(sortie, engine="openpyxl") as xl:
        grands.to_excel(xl, sheet_name="grands_projets", index=False)
        profil_colonnes(grands).to_excel(xl, sheet_name="colonnes", index=False)

        ws = xl.sheets["grands_projets"]
        ws.freeze_panes = "C2"
        ws.auto_filter.ref = ws.dimensions
        for i, col in enumerate(grands.columns, start=1):
            lettre = ws.cell(row=1, column=i).column_letter
            largeur = 60 if col == "NOMBRE_INVERSION" else 14
            ws.column_dimensions[lettre].width = largeur
            if col in COLONNES_MONTANTS:
                for cell in ws[lettre][1:]:
                    cell.number_format = "#,##0"
        wc = xl.sheets["colonnes"]
        wc.freeze_panes = "B2"
        for lettre, largeur in zip("ABCDEFG", [26, 9, 12, 40, 40, 40, 50]):
            wc.column_dimensions[lettre].width = largeur

    print(f"{len(grands):,} projets de plus de {seuil_millions} M de soles -> {sortie}")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 100)
