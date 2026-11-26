"""Étape 4 : les consultations de ProInversión (l'agence péruvienne de promotion de l'investissement privé).

ProInversión publie sur son site (investinperu.pe) deux listes, lisibles par l'API publique du site (WordPress) :
- les « concursos » : concours, publics ou sur invitation, surtout pour recruter des cabinets de conseil
  (quelques-uns portent sur d'autres services : exploitation d'un hôpital, vente d'actions de l'État...) ;
- les « expresiones de interés » : appels à manifestation d'intérêt, pour établir la liste courte d'un concours.
Ce ne sont PAS les appels d'offres des APP eux-mêmes : ce sont surtout les marchés de conseil (structuration,
études techniques, supervision) que l'agence passe pour préparer ses projets. Ils montrent quels projets
l'État prépare.

Ce que fait le script, dans l'ordre :
1. Télécharge les deux listes complètes par l'API, et vérifie qu'il a bien tout reçu.
2. Traduit les étiquettes (statut, type de concours ou secteur, année) grâce aux listes de l'API.
3. Classe chaque consultation selon sa nature, d'après les mots de son titre (classement indicatif).
4. Pour les seules consultations que le site n'affiche pas comme closes, lit leur page pour connaître la date
   de convocatoria et les documents publiés, et en déduit la phase (le statut du site est souvent en retard).
5. Relie ces consultations aux projets du MEF grâce à correspondance_proinversion.csv (table faite à la main).
6. Enregistre une copie datée et la compare à la copie précédente (nouvelles consultations, statut changé).
7. Écrit exports/proinversion_<date>.xlsx (fichier de travail).

Lancement : python proinversion.py
            python proinversion.py --forcer            (relance même si la copie du jour existe déjà)
            pythonw proinversion.py --journal <fichier> (sans fenêtre : c'est ainsi que la tâche planifiée le lance)
"""

import html
import json
import re
import sys
import urllib.parse
import urllib.request
from datetime import date, datetime
from pathlib import Path

import pandas as pd

from archiver import DATA_DIR, ecrire_les_messages_dans
from indicateurs import SORTIE_DIR, simplifier

API = "https://www.investinperu.pe/wp-json/wp/v2"
DOSSIER_COPIES = DATA_DIR / "proinversion"
CORRESPONDANCE_CSV = Path(__file__).parent / "correspondance_proinversion.csv"
ENTETES = {"User-Agent": "pipeline-inversiones-peru"}

# Pour chaque liste : le chemin dans l'API et les étiquettes (« taxonomies ») qui nous intéressent.
LISTES = {
    "concours": {"chemin": "concursos", "statut": "estado_concurso", "categorie": "tipos_concurso",
                 "annee": "anio_concursos"},
    "expression d'intérêt": {"chemin": "expresiones-interes", "statut": "estado_expresiones",
                             "categorie": "sector_expresiones", "annee": "anio_expresiones"},
}
CLOS = "Concluido"
STATUTS_CONNUS = {"Concluido", "En Proceso"}  # « Vigente » existe sur le site mais n'est utilisé par aucune consultation

# Qui peut répondre (règlement des contrats de ProInversión, Acuerdo 161-1-2025-CD, art. 9, 12 et 19).
ACCES = {
    "Concursos públicos": "public (ouvert à tous)",
    "Concursos púbico SSE": "public (supervision spécialisée d'une APP)",  # faute de frappe dans la source
    "Concursos por invitación": "sur invitation (liste fermée)",
}

# Nature de la consultation, d'après des MOTS ENTIERS du titre (sans accents, en majuscules).
# \b veut dire « bord de mot » : \bAPP\b trouve « APP » mais pas « APPLICATION ».
# L'ordre compte : la première règle qui correspond l'emporte. Classement indicatif, à ne pas citer comme un chiffre.
NATURES = [
    (r"SUPERVIS", "Supervision (travaux, exploitation ou études)"),
    (r"AUDITOR", "Audit"),
    (r"\bPREDIOS\b|SANEAMIENTO FISICO|TASACION", "Études techniques"),
    (r"ESTRUCTURACION|TRANSACCION|\bIEC\b|\bIEA\b|\bAPP\b|PUBLICO[ -]PRIVAD|CONSULTOR(IA)? INTEGRAL|\bLEGAL\b"
     r"|\bFINANCIERA\b|PROMOCION", "Structuration d'un projet (APP ou actifs)"),
    (r"TOPOGRAF|GEOLOG|CARTOGRAF|SUELOS|ARQUEOLOG|ESTUDIO|FORMULACION|INGENIERIA|TECNIC|ESPECIALIZAD",
     "Études techniques"),
]
# Beaucoup de titres ne sont qu'un nom de projet (« Proyecto Sicuani – Pucará ») : on ne devine pas.
AUTRE_NATURE = "Non classé (titre peu précis)"

# Phase d'une consultation, d'après les documents publiés sur sa page (tous les documents, pas seulement le
# dernier : une annulation compte même si une circulaire a été publiée après). L'ordre compte.
PHASES = [
    (r"CANCELACION|SIN EFECTO|NULIDAD", "annulée"),
    (r"DESIERTO", "déclarée déserte"),
    (r"BUENA PRO|COMUNICACION DE RESULTADOS", "résultats publiés"),
    (r"RECEPCION DE SOBRES|APERTURA DE SOBRE", "offres reçues, en évaluation"),
]


# ---------------------------------------------------------------- 1 et 2 : lecture de l'API

def lire_json(url):
    requete = urllib.request.Request(url, headers=ENTETES)
    with urllib.request.urlopen(requete, timeout=60) as reponse:
        return json.loads(reponse.read().decode("utf-8-sig")), reponse.headers


def lire_api(chemin, **parametres):
    """Lit toutes les pages d'une liste de l'API WordPress (100 éléments par page, triés par numéro pour que
    la pagination soit stable), puis vérifie qu'on a reçu exactement le nombre annoncé, sans doublon."""
    elements, page = [], 1
    while True:
        url = f"{API}/{chemin}?" + urllib.parse.urlencode(
            {"per_page": 100, "page": page, "orderby": "id", "order": "asc", **parametres})
        donnees, entetes = lire_json(url)
        if not isinstance(donnees, list):
            raise ValueError(f"Réponse inattendue de {url} : {str(donnees)[:200]}")
        elements += donnees
        nb_pages = int(entetes.get("X-WP-TotalPages", 0))
        # Sans l'en-tête, on continue tant que les pages sont pleines.
        if (nb_pages and page >= nb_pages) or (not nb_pages and len(donnees) < 100):
            break
        page += 1
    total = entetes.get("X-WP-Total")
    identifiants = [e["id"] for e in elements]
    if total is not None and len(elements) != int(total):
        raise ValueError(f"{chemin} : {len(elements)} éléments reçus pour {total} annoncés.")
    if len(set(identifiants)) != len(identifiants):
        raise ValueError(f"{chemin} : des éléments reçus en double (la liste a bougé pendant la lecture ?).")
    return elements


def nettoyer_titre(titre):
    """Enlève les entités HTML (&#8211;), les balises (<em>) et les espaces en trop."""
    sans_balises = re.sub(r"<[^>]+>", "", html.unescape(titre))
    return " ".join(sans_balises.split())


def nature(titre):
    """Classe une consultation d'après son titre. Exemple : « Supervisión Especializada PTAR » donne
    « Supervision (travaux, exploitation ou études) » (et pas « Études techniques », car la supervision est
    testée d'abord)."""
    texte = simplifier(titre)
    return next((nom for motif, nom in NATURES if re.search(motif, texte)), AUTRE_NATURE)


def mettre_en_tableau(elements, liste, noms_etiquettes):
    """Transforme la réponse de l'API en tableau. Les étiquettes arrivent sous forme de numéros
    (ex. 279) : on les remplace par leur nom (ex. « En Proceso »). Les numéros d'étiquettes WordPress sont
    uniques sur tout le site, on peut donc mettre les trois listes d'étiquettes dans un seul dictionnaire."""
    reglages = LISTES[liste]

    def noms(numeros):
        return ", ".join(noms_etiquettes.get(n, str(n)) for n in numeros)

    lignes = []
    for e in elements:
        titre = nettoyer_titre(e["title"]["rendered"])
        categorie = noms(e.get(reglages["categorie"], []))
        lignes.append({
            "id": e["id"],
            "liste": liste,
            "titre": titre,
            "nature": nature(titre),
            "statut_affiche": noms(e.get(reglages["statut"], [])),
            "categorie": categorie,
            "acces": ACCES.get(categorie, "liste courte à constituer" if liste != "concours" else ""),
            # L'année de l'étiquette est celle de la convocatoria. La date WordPress, elle, est souvent celle
            # de la migration du site en 2025 : on l'appelle donc « mis en ligne », pas « publiée ».
            "annee": noms(e.get(reglages["annee"], [])),
            "mis_en_ligne_le": e["date"][:10],
            "modifie_le": e["modified"][:10],
            "lien": e["link"],
        })
    return pd.DataFrame(lignes)


def telecharger_tout():
    tableaux = []
    for liste, reglages in LISTES.items():
        noms_etiquettes = {}
        for taxonomie in (reglages["statut"], reglages["categorie"], reglages["annee"]):
            noms_etiquettes |= {t["id"]: t["name"] for t in lire_api(taxonomie)}
        elements = lire_api(reglages["chemin"], _fields="id,date,modified,link,title," +
                            ",".join([reglages["statut"], reglages["categorie"], reglages["annee"]]))
        tableaux.append(mettre_en_tableau(elements, liste, noms_etiquettes))
    toutes = pd.concat(tableaux, ignore_index=True)
    return toutes.sort_values(["annee", "modifie_le"], ascending=False, ignore_index=True)


# ---------------------------------------------------------------- 4 : phase, d'après la page de la consultation

def lire_page(url):
    requete = urllib.request.Request(url, headers=ENTETES)
    with urllib.request.urlopen(requete, timeout=60) as reponse:
        return reponse.read().decode("utf-8", errors="replace")


def lire_fiche(page_html):
    """Dans la page d'une consultation : la date de convocatoria, la date limite (appels à manifestation
    d'intérêt) et la liste des documents publiés (description, date), lue dans le tableau « Documentación »."""
    def champ(etiquette):
        trouve = re.search(etiquette + r"\s*:?\s*</[^>]+>\s*(?:<[^>]+>\s*)*(\d{2}/\d{2}/\d{4})", page_html)
        return trouve.group(1) if trouve else ""

    documents = []
    for description, jour in re.findall(r'data-label="Descripci[^"]*">(.*?)</td>\s*<td data-label="Fecha:">(.*?)</td>',
                                        page_html, flags=re.S):
        documents.append((nettoyer_titre(description), jour.strip()))
    return {"convocatoria": champ("Fecha de convocatoria"),
            "date_limite": champ("Fecha de l[ií]mite de presentaci[oó]n"),
            "documents": documents}


def phase(fiche, aujourd_hui):
    """Phase d'après les documents publiés. Sans document décisif : délai dépassé (si la date limite est
    passée) ou avant le dépôt des offres."""
    tous = simplifier(" | ".join(description for description, _ in fiche["documents"]))
    for motif, nom in PHASES:
        if re.search(motif, tous):
            return nom
    if fiche["date_limite"] and datetime.strptime(fiche["date_limite"], "%d/%m/%Y").date() < aujourd_hui:
        return "délai de candidature dépassé"
    return "avant le dépôt des offres"


def completer_non_closes(non_closes, aujourd_hui, lire=lire_page):
    """Ajoute convocatoria, dernier document et phase aux consultations non closes (une page lue par consultation)."""
    lignes = []
    for c in non_closes.itertuples():
        fiche = lire_fiche(lire(c.lien))
        # Tri par date ; à date égale, sorted garde l'ordre du tableau, donc le dernier publié reste à la fin.
        par_date = sorted(fiche["documents"], key=lambda d: datetime.strptime(d[1], "%d/%m/%Y"))
        dernier = par_date[-1] if par_date else ("", "")
        lignes.append({"id": c.id, "convocatoria": fiche["convocatoria"], "date_limite": fiche["date_limite"],
                       "dernier_document": dernier[0], "date_dernier_document": dernier[1],
                       "phase_d_apres_les_documents": phase(fiche, aujourd_hui)})
    colonnes = ["id", "convocatoria", "date_limite", "dernier_document", "date_dernier_document",
                "phase_d_apres_les_documents"]
    return non_closes.merge(pd.DataFrame(lignes, columns=colonnes), on="id", how="left")


# ---------------------------------------------------------------- 5 : lien avec les projets du MEF

def ajouter_projets_mef(tableau):
    """Ajoute les codes des projets du MEF (CODIGO_UNICO) liés à chaque consultation. La table est faite à la
    main, avec une règle simple : on ne relie que si un document officiel de ProInversión cite le code."""
    if not CORRESPONDANCE_CSV.exists():
        return tableau.assign(projets_mef="")
    table = pd.read_csv(CORRESPONDANCE_CSV, sep=";", dtype=str, keep_default_na=False)
    table = table[table["CODIGO_UNICO"] != ""]
    codes = table.groupby("ID_PROINVERSION")["CODIGO_UNICO"].agg(", ".join)
    return tableau.assign(projets_mef=tableau["id"].astype(str).map(codes).fillna(""))


# ---------------------------------------------------------------- 6 : comparaison de deux copies

def comparer(avant, apres):
    """Nouvelles consultations, statuts changés et consultations retirées du site, entre deux copies (clé : id)."""
    colonnes = ["id", "changement", "titre", "statut_avant", "statut_apres", "lien"]
    if avant is None:
        return pd.DataFrame(columns=colonnes)
    avant = avant.assign(statut_affiche=avant["statut_affiche"].fillna(""))
    apres = apres.assign(statut_affiche=apres["statut_affiche"].fillna(""))
    # indicator=True ajoute la colonne _merge : « left_only » = absente de la copie d'avant.
    fusion = apres.merge(avant[["id", "statut_affiche"]], on="id", how="left", suffixes=("", "_avant"),
                         indicator=True)
    fusion = fusion.rename(columns={"statut_affiche": "statut_apres", "statut_affiche_avant": "statut_avant"})
    nouvelles = fusion[fusion["_merge"] == "left_only"].assign(changement="nouvelle consultation")
    changees = fusion[(fusion["_merge"] == "both") & (fusion["statut_avant"] != fusion["statut_apres"])]
    changees = changees.assign(changement="statut changé")
    retirees = avant[~avant["id"].isin(apres["id"])].copy()
    retirees["statut_avant"] = retirees["statut_affiche"]
    retirees["statut_apres"] = ""
    retirees["changement"] = "retirée du site"
    return pd.concat([nouvelles, changees, retirees], ignore_index=True)[colonnes]


def derniere_copie(avant_le):
    """La copie enregistrée la plus récente, d'un jour antérieur à avant_le (ou None).
    Relancer le script le même jour écrase la copie du jour : la comparaison se fait toujours avec le jour d'avant."""
    copies = {}
    for chemin in DOSSIER_COPIES.glob("consultations_*.csv"):
        trouve = re.fullmatch(r"consultations_(\d{4}-\d{2}-\d{2})\.csv", chemin.name)
        if trouve and trouve.group(1) < avant_le:
            copies[trouve.group(1)] = chemin
    if not copies:
        return None
    return pd.read_csv(copies[max(copies)], encoding="utf-8", keep_default_na=False)


# ---------------------------------------------------------------- programme principal

def main(forcer=False):
    sys.stdout.reconfigure(encoding="utf-8")
    aujourd_hui = date.today()
    print(f"--- ProInversión, {datetime.now():%d/%m/%Y %H:%M} ---")
    # La tâche planifiée tourne jusqu'à trois fois par jour : on ne lit le site qu'une fois par jour.
    if (DOSSIER_COPIES / f"consultations_{aujourd_hui.isoformat()}.csv").exists() and not forcer:
        print("Copie du jour déjà faite : rien à faire.")
        return
    toutes = telecharger_tout()
    inconnus = set(s for valeur in toutes["statut_affiche"] for s in valeur.split(", ") if s) - STATUTS_CONNUS
    if inconnus:
        print(f"Attention : statut inattendu sur le site ({inconnus}) : vérifier le classement.")

    # « Non close » = tout ce que le site n'affiche pas comme « Concluido ».
    non_closes = toutes[toutes["statut_affiche"] != CLOS]
    non_closes = ajouter_projets_mef(completer_non_closes(non_closes, aujourd_hui))
    precedente = derniere_copie(aujourd_hui.isoformat())
    changements = comparer(precedente, toutes)

    DOSSIER_COPIES.mkdir(parents=True, exist_ok=True)
    toutes.to_csv(DOSSIER_COPIES / f"consultations_{aujourd_hui.isoformat()}.csv", index=False, encoding="utf-8")

    SORTIE_DIR.mkdir(exist_ok=True)
    sortie = SORTIE_DIR / f"proinversion_{aujourd_hui.isoformat()}.xlsx"
    with pd.ExcelWriter(sortie, engine="openpyxl") as xl:
        for nom, tableau in [("non_closes", non_closes), ("changements", changements), ("toutes", toutes)]:
            tableau.to_excel(xl, sheet_name=nom, index=False)
            feuille = xl.sheets[nom]
            feuille.freeze_panes = "C2"
            for colonne in feuille.columns:
                titre = str(colonne[0].value)
                feuille.column_dimensions[colonne[0].column_letter].width = {
                    "titre": 80, "lien": 60, "dernier_document": 50}.get(titre, 18)

    print(f"{len(toutes)} consultations publiées (source : investinperu.pe, consulté le {aujourd_hui:%d/%m/%Y}).")
    print(f"{len(non_closes)} ne sont pas affichées comme closes. D'après leurs documents :\n")
    for c in non_closes.itertuples():
        print(f"  [{c.phase_d_apres_les_documents}] {c.titre} (convocatoria {c.convocatoria or 'non indiquée'})")
    if precedente is None:
        print("\nPremière copie : pas encore de comparaison possible.")
    else:
        print(f"\nDepuis la copie précédente : {len(changements)} changement(s).")
    print(f"\n-> {sortie}")


if __name__ == "__main__":
    if "--journal" in sys.argv:
        ecrire_les_messages_dans(sys.argv[sys.argv.index("--journal") + 1])
    main(forcer="--forcer" in sys.argv)
