"""Tests de l'étape 4 (consultations de ProInversión), sans appel réseau.

Lancement, depuis le dossier du projet : python -m pytest
"""

import json
import urllib.parse
from datetime import date

import pandas as pd
import pytest

import proinversion as pi

STRUCTURATION = "Structuration d'un projet (APP ou actifs)"
ETUDES = "Études techniques"
SUPERVISION = "Supervision (travaux, exploitation ou études)"


# ---------------------------------------------------------------- nature d'après le titre (titres réels)

@pytest.mark.parametrize("titre, attendu", [
    ("Supervisión Especializada PTAR CAJAMARCA", SUPERVISION),  # avant « Études » (ESPECIALIZADA)
    ("Consultoría Técnica APP para Nuevos Terminales Portuarios de Loreto", STRUCTURATION),
    ("Segunda convocatoria – Consultoría Integral Estructuración y Transacción IEC Agua y Saneamiento Tumbes",
     STRUCTURATION),
    ("Consultoría Levantamiento Topográfico – VEC Cusco", ETUDES),
    ("Auditoría Proyecto Minero Magistral", "Audit"),
    ("Contratación del servicio de consultoría especializada en materia de asociaciones público privadas", STRUCTURATION),
    ("Servicio de identificación de predios y conformación de expedientes técnico-legales", ETUDES),
    ("Asesoría Social-Comunicacional", pi.AUTRE_NATURE),
    ("Proyecto Sicuani – Pucará – Calapuja", pi.AUTRE_NATURE),
])
def test_nature(titre, attendu):
    assert pi.nature(titre) == attendu


@pytest.mark.parametrize("titre", ["Proyecto IECOS Lima", "Programa de aplicaciones"])
def test_sigles_cherches_en_mots_entiers(titre):
    # \bIEC\b et \bAPP\b ne trouvent pas « IECOS » ni « APPlicaciones ».
    assert pi.nature(titre) == pi.AUTRE_NATURE


def test_sigle_entre_parentheses_reconnu():
    assert pi.nature("Consultoría para la (IEC) del proyecto") == STRUCTURATION


def test_nettoyer_titre():
    assert pi.nettoyer_titre("Consultoría  <em>Legal</em> &#8211; Sechura ") == "Consultoría Legal – Sechura"


# ---------------------------------------------------------------- mise en tableau

def element(identifiant, titre, statut, categorie=276, date_wp="2025-07-22T10:00:00"):
    return {"id": identifiant, "date": date_wp, "modified": date_wp, "link": f"https://x/{identifiant}",
            "title": {"rendered": titre}, "estado_concurso": [statut], "tipos_concurso": [categorie],
            "anio_concursos": [593]}


def test_mise_en_tableau_traduit_les_etiquettes():
    noms = {279: "En Proceso", 276: "Concursos por invitación", 593: "2026"}
    ligne = pi.mettre_en_tableau([element(1, "Estudio", 279)], "concours", noms).iloc[0]
    assert (ligne["statut_affiche"], ligne["categorie"], ligne["annee"]) == ("En Proceso", "Concursos por invitación", "2026")
    assert ligne["acces"] == "sur invitation (liste fermée)"
    assert ligne["mis_en_ligne_le"] == "2025-07-22"  # date WordPress, pas la date de convocatoria


def test_etiquette_inconnue_gardee_en_numero():
    assert pi.mettre_en_tableau([element(1, "Estudio", 999)], "concours", {}).iloc[0]["statut_affiche"] == "999"


# ---------------------------------------------------------------- lecture de l'API (sans réseau)

class FausseReponse:
    def __init__(self, donnees, entetes):
        self.donnees, self.headers = donnees, entetes

    def read(self):
        return json.dumps(self.donnees).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def faux_site(monkeypatch, pages, entetes):
    """Remplace urlopen : la page n renvoie pages[n-1], avec les en-têtes donnés."""
    def faux_urlopen(requete, timeout):
        numero = int(urllib.parse.parse_qs(urllib.parse.urlparse(requete.full_url).query)["page"][0])
        return FausseReponse(pages[numero - 1], entetes)
    monkeypatch.setattr(pi.urllib.request, "urlopen", faux_urlopen)


def test_lire_api_parcourt_toutes_les_pages(monkeypatch):
    faux_site(monkeypatch, [[{"id": 1}], [{"id": 2}], [{"id": 3}]], {"X-WP-TotalPages": "3", "X-WP-Total": "3"})
    assert [e["id"] for e in pi.lire_api("concursos")] == [1, 2, 3]


def test_lire_api_refuse_un_compte_incomplet(monkeypatch):
    faux_site(monkeypatch, [[{"id": 1}]], {"X-WP-TotalPages": "1", "X-WP-Total": "120"})
    with pytest.raises(ValueError):
        pi.lire_api("concursos")


def test_lire_api_refuse_les_doublons(monkeypatch):
    faux_site(monkeypatch, [[{"id": 1}], [{"id": 1}]], {"X-WP-TotalPages": "2"})
    with pytest.raises(ValueError):
        pi.lire_api("concursos")


def test_lire_api_refuse_une_reponse_qui_n_est_pas_une_liste(monkeypatch):
    faux_site(monkeypatch, [{"code": "erreur"}], {})
    with pytest.raises(ValueError):
        pi.lire_api("concursos")


def test_lire_api_sans_entete_continue_tant_que_les_pages_sont_pleines(monkeypatch):
    pleine = [{"id": i} for i in range(100)]
    faux_site(monkeypatch, [pleine, [{"id": 100}]], {})
    assert len(pi.lire_api("concursos")) == 101


# ---------------------------------------------------------------- phase, d'après la page de la consultation

PAGE = """
<h3>Fecha de convocatoria:</h3> <div><span>27/04/2026</span></div>
<table><tr><th>Descripción</th><th>Fecha</th></tr>
<tr><td data-label="Descripción:">Bases del concurso</td>
<td data-label="Fecha:">27/04/2026</td><td></td></tr>
<tr><td data-label="Descripción:">Acta Comunicación de Resultados</td>
<td data-label="Fecha:">21/05/2026</td><td></td></tr>
<tr><td data-label="Descripción:">Circular 3 - Cancelación del concurso</td>
<td data-label="Fecha:">28/09/2026</td><td></td></tr></table>
"""


def test_lire_fiche():
    fiche = pi.lire_fiche(PAGE)
    assert fiche["convocatoria"] == "27/04/2026"
    assert fiche["date_limite"] == ""
    assert fiche["documents"][-1] == ("Circular 3 - Cancelación del concurso", "28/09/2026")


def fiche(*descriptions, date_limite=""):
    return {"convocatoria": "", "date_limite": date_limite, "documents": [(d, "01/01/2026") for d in descriptions]}


AUJOURD_HUI = date(2026, 11, 25)


@pytest.mark.parametrize("la_fiche, attendu", [
    # Les 6 cas réels du 25/11/2026.
    (fiche("Bases del concurso", "Acta Comunicación de Resultados", "Circular 3 - Cancelación del concurso"), "annulée"),
    (fiche("Acta de Recepción de Sobres N° 1 y N° 2", "Acta de Comunicación de Resultados",
           "Circular N° 5 - Consentimiento de Buena Pro"), "résultats publiés"),
    (fiche("Circular N° 8 - Absolución de Consultas", "Acta de Recepción de Sobres N° 1 y N° 2 y Apertura del Sobre N° 1",
           "Circular N° 9 - Modificación de Cronograma"), "offres reçues, en évaluation"),
    (fiche("Comunicado N° 4 - Actualización de la Solicitud", date_limite="10/12/2025"), "délai de candidature dépassé"),
    (fiche("Bases del concurso", "Circular N° 2 - Modificación de Cronograma"), "avant le dépôt des offres"),
    (fiche("Bases del concurso"), "avant le dépôt des offres"),
])
def test_phase(la_fiche, attendu):
    assert pi.phase(la_fiche, AUJOURD_HUI) == attendu


def test_completer_non_closes_sans_reseau():
    non_closes = pd.DataFrame([{"id": 7, "lien": "https://x/7"}])
    resultat = pi.completer_non_closes(non_closes, AUJOURD_HUI, lire=lambda url: PAGE).iloc[0]
    assert resultat["phase_d_apres_les_documents"] == "annulée"
    assert (resultat["dernier_document"], resultat["date_dernier_document"]) == ("Circular 3 - Cancelación del concurso",
                                                                                  "28/09/2026")


# ---------------------------------------------------------------- lien avec le MEF

def test_ajouter_projets_mef(monkeypatch, tmp_path):
    table = tmp_path / "correspondance.csv"
    table.write_text("ID_PROINVERSION;CODIGO_UNICO;CERTITUDE;NOTE;SOURCE\n"
                     "43087;2481025;certaine;a;https://x\n43087;2391857;certaine;b;https://x\n"
                     "38863;;aucune;c;https://x\n", encoding="utf-8")
    monkeypatch.setattr(pi, "CORRESPONDANCE_CSV", table)
    resultat = pi.ajouter_projets_mef(pd.DataFrame({"id": [43087, 38863, 1]}))
    assert resultat["projets_mef"].tolist() == ["2481025, 2391857", "", ""]


# ---------------------------------------------------------------- comparaison de deux copies

def copie(*lignes):
    return pd.DataFrame(lignes, columns=["id", "titre", "statut_affiche", "lien"])


def test_premiere_copie_pas_de_changement():
    assert pi.comparer(None, copie((1, "A", "En Proceso", "l1"))).empty


def test_changements_entre_deux_copies():
    avant = copie((1, "A", "En Proceso", "l1"), (2, "B", "En Proceso", "l2"), (3, "C", "Concluido", "l3"))
    apres = copie((1, "A", "En Proceso", "l1"), (2, "B", "Concluido", "l2"), (4, "D", "En Proceso", "l4"))
    resultat = pi.comparer(avant, apres).set_index("id")
    assert resultat.loc[4, "changement"] == "nouvelle consultation"
    assert (resultat.loc[2, "statut_avant"], resultat.loc[2, "statut_apres"]) == ("En Proceso", "Concluido")
    assert resultat.loc[3, "changement"] == "retirée du site"
    assert 1 not in resultat.index


def test_statut_vide_relu_depuis_un_csv_n_est_pas_une_nouveaute(monkeypatch, tmp_path):
    # Un statut vide devient NaN si on relit le CSV sans précaution : il ne doit pas passer pour « nouveau ».
    monkeypatch.setattr(pi, "DOSSIER_COPIES", tmp_path)
    copie((1, "A", "", "l1")).to_csv(tmp_path / "consultations_2026-11-24.csv", index=False)
    avant = pi.derniere_copie("2026-11-25")
    assert pi.comparer(avant, copie((1, "A", "", "l1"))).empty


def test_derniere_copie_ignore_celle_du_jour_et_les_noms_inattendus(monkeypatch, tmp_path):
    monkeypatch.setattr(pi, "DOSSIER_COPIES", tmp_path)
    copie((1, "A", "En Proceso", "l")).to_csv(tmp_path / "consultations_2026-11-20.csv", index=False)
    copie((2, "B", "En Proceso", "l")).to_csv(tmp_path / "consultations_2026-11-25.csv", index=False)
    copie((3, "C", "En Proceso", "l")).to_csv(tmp_path / "consultations_2026-11-25_bis.csv", index=False)
    assert pi.derniere_copie("2026-11-25")["id"].tolist() == [1]
    assert pi.derniere_copie("2026-11-20") is None


def test_dernier_document_a_date_egale_est_le_dernier_du_tableau():
    page = PAGE.replace("21/05/2026", "28/09/2026")  # deux documents le 28/09 : le 2e publié doit gagner
    resultat = pi.completer_non_closes(pd.DataFrame([{"id": 7, "lien": "x"}]), AUJOURD_HUI, lire=lambda url: page)
    assert resultat.iloc[0]["dernier_document"] == "Circular 3 - Cancelación del concurso"


def test_une_seule_lecture_du_site_par_jour(monkeypatch, tmp_path):
    monkeypatch.setattr(pi, "DOSSIER_COPIES", tmp_path)
    (tmp_path / f"consultations_{date.today().isoformat()}.csv").write_text("id\n", encoding="utf-8")

    def interdit():
        raise AssertionError("le site ne doit pas être relu le même jour")

    monkeypatch.setattr(pi, "telecharger_tout", interdit)
    pi.main()  # ne doit rien télécharger
    with pytest.raises(AssertionError):
        pi.main(forcer=True)  # --forcer relit le site
