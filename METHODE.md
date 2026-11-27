# Méthode, étape par étape

Ce document détaille les règles de calcul et les limites de chaque étape du pipeline. Pour une présentation rapide, voir le [README](README.md).

## Étape 0 : archivage du fichier du MEF

`archiver.py` télécharge le fichier du MEF quand il a été mis à jour, retire la colonne de textes longs `ALTERNATIVA`, convertit les montants en nombres et enregistre une copie datée au format Parquet (environ 30 Mo par jour). Le journal `snapshots.csv` garde la trace de chaque archive. La date d'une archive est celle de la mise à jour du fichier par le MEF, pas celle du téléchargement.

Pourquoi archiver : le MEF ne publie que l'état du jour. Pour savoir ce qui a bougé, il faut garder soi-même les versions successives.

```
python archiver.py
python archiver.py --journal <fichier>   # sans fenêtre (pythonw), messages écrits dans le fichier
```

Une tâche planifiée peut lancer `archiver.py` puis `proinversion.py` plusieurs fois par jour, dont une fois après la publication du MEF (vers 19 h UTC, soit 14 h à Lima), et rattraper au démarrage un lancement manqué. Sous Windows, `archiver.bat` lance l'archivage d'un double-clic. Le MEF ne garde que la version du jour : une version publiée pendant que l'ordinateur reste éteint est perdue.

Les données sont stockées hors du dépôt, dans `~/data/inversiones-peru` (modifiable avec la variable d'environnement `INVERSIONES_DATA`).

## Étape 1 : dictionnaire des colonnes

`dictionnaire_colonnes.md` décrit les colonnes du fichier du MEF utilisées par le pipeline, à partir du dictionnaire officiel, des textes d'Invierte.pe et de tests sur les données. `export_excel.py` produit un Excel des grands projets, avec un onglet qui reprend ces définitions, pour les regarder à la main.

## Étape 2 : indicateurs des grands projets

`indicateurs.py` lit la dernière archive et produit `exports/indicateurs_<date>.xlsx`, un fichier de travail détaillé projet par projet.

- **Périmètre** : investissements dont le coût atteint 100 millions de soles, après retrait des lignes en double sur `CODIGO_UNICO`. Le coût est `COSTO_ACTUALIZADO + CTRL_CONCURR` (voir « Changement de format du MEF », étape 3).
- **Secteurs** : `FUNCION` regroupée en 8 secteurs dans `secteurs.csv`. Un `PROGRAMA` peut passer avant la fonction : les protections contre les crues (programme « Gestión de riesgos y emergencias ») sont rangées en prévention des risques, alors que le MEF les classe en ordre public.
- **Modes de réalisation** : une case de `DES_MODALIDAD` peut contenir plusieurs modes. On les sépare et on les normalise. Chaque projet reçoit un seul « mode principal », le montage le plus structurant déclaré, selon un ordre fixé dans `indicateurs.py` (APP en premier, régie en dernier). Ainsi, chaque projet ne compte qu'une fois. L'onglet `modes_mentions` donne l'autre vue, où un projet à deux modes compte deux fois. Dans la fiche et la carte, seuls l'APP, les travaux contre impôts, le marché public et la régie sont détaillés ; les autres montages sont regroupés dans « Autres montages ».
- **Exécution de l'année** : somme des devengados / somme des PIM, sur les projets qui ont un PIM, comme dans la Consulta Amigable du MEF. Les données sont celles du jour du fichier : le taux est partiel jusqu'en décembre.
- **Dollars** : conversion indicative au taux moyen de l'année (BCRP, série PN01207PM, moyenne des mois publiés).
- **Contrôles** : les valeurs impossibles sont mises à vide (avancement hors de 0-100 %, bénéficiaires plus nombreux que la population, coordonnées hors d'un rectangle qui englobe le Pérou) ; les latitudes et longitudes inversées sont remises dans l'ordre. Les cas douteux (doublon probable sous deux codes, coût communal sans rapport avec le budget de la commune) sont signalés mais pas retirés.
- **Corrections à la main** : `corrections_projets.csv` permet, projet par projet, de corriger le mode de réalisation (`MODE_CORRIGE`) ou d'ajouter une note (`NOTE`), toujours avec une source (`SOURCE`). Exemple : Majes-Siguas II et Chavimochic III, deux anciennes concessions sans mode renseigné, gardent le mode déclaré par le MEF, avec une note : leurs ouvrages sont aujourd'hui portés par le ministère de l'Agriculture, et aucune n'est une APP en cours.

Limites :
- Le coût total est un portefeuille d'intentions, pas un effort budgétaire : au 25/11/2026, 38 % de ce coût correspond à des projets qui n'ont ni budget de l'année ni dépense passée (crédits publics seulement : le financement privé des APP n'apparaît pas dans ce fichier). L'effort de l'année se lit dans le PIM.
- 100 grands projets, surtout d'anciens projets SNIP, n'ont pas de mode de réalisation renseigné.
- Le fichier ne relie pas les programmes d'investissement à leurs projets : 16 lignes de programme (0,6 % du coût) peuvent recouper des projets comptés à part.

## Étape 3 : ce qui a bougé d'une archive à l'autre

`changements.py` compare deux archives et produit `exports/changements_<ancienne>_<recente>.xlsx`, un fichier de travail.

```
python changements.py                          # la plus récente, et la plus récente datant d'au moins 7 jours avant
python changements.py 2026-11-14               # cette date, comparée à la plus récente
python changements.py 2026-11-14 2026-11-23    # deux dates au choix
```

- **Préparation** : chaque archive est préparée comme à l'étape 2. Un projet est suivi d'une archive à l'autre grâce à son `CODIGO_UNICO`.
- **Périmètre** : les projets d'au moins 100 millions de soles dans l'une ou l'autre archive, pour voir aussi ceux qui franchissent le seuil.
- **Signaux** : nouveau grand projet ; projet qui ne figure plus parmi les investissements actifs ; seuil de 100 M franchi (seulement si le coût bouge d'au moins 5 %, sinon c'est une petite réévaluation) ; situation ou expediente técnico changés ; avancement physique en hausse d'au moins 10 points ; PIM de l'année en hausse ou en baisse d'au moins 5 M de soles ; coût en hausse ou en baisse d'au moins 10 % ; modes de réalisation changés. Les modes sont comparés comme des ensembles : le MEF change souvent l'ordre du texte sans que rien ne change.
- **Transferts probables** : quand deux projets voient leur PIM bouger du même montant exact, en sens inverse, le fichier le note. On compare l'unité exécutrice (`SEC_EJEC`), qui porte les crédits : même unité, réaffectation interne probable ; unités différentes, transfert possible, à vérifier. Le fichier du MEF ne contient pas les modifications budgétaires elles-mêmes : c'est une piste, pas un constat.
- **Ruptures de format** : pour chaque colonne, le script compare la part de cases remplies entre les deux archives. Un écart de 5 points ou plus est signalé, car il veut dire que le MEF a changé son fichier.

Limites :
- **Changement de format du MEF du 20 au 23/11/2026** : d'habitude, le coût du contrôle concomitant de la Contraloría est dans une colonne à part (`CTRL_CONCURR`) et pas dans `COSTO_ACTUALIZADO`. Dans ses fichiers des 20 et 23/11, le MEF l'avait ajouté au coût et mis la colonne à zéro, puis il est revenu à l'ancien format le 24/11. Le coût utilisé partout est `COSTO_ACTUALIZADO + CTRL_CONCURR`, juste dans les deux formats. Sans cette correction, 12 projets semblaient passer au-dessus de 100 M entre le 14 et le 23/11 sans aucun changement réel. Pendant les mêmes jours, la colonne `ETAPA_F8` avait été vidée et les dates d'exécution venaient d'une autre source : aucun signal ne les utilise. Une comparaison entre deux dates qui encadrent cet aller-retour (par exemple le 14 et le 25/11) ne voit aucune rupture : il faut regarder aussi les archives intermédiaires.
- **Sortie de la liste** : le MEF ne publie que les investissements actifs. Un projet qui disparaît a pu être clôturé (format 9) ou désactivé. Le fichier ne dit pas lequel ; le fichier de travail donne un profil probable. Un projet sorti peut revenir.
- **Période courte** : du 14 au 23/11/2026, une centaine de grands projets ont vu leur PIM bouger. Les seuils retiennent les mouvements les plus nets, pas une tendance.
- **PIM de fin d'année** : en novembre, les entités réaffectent les crédits qu'elles ne pourront pas dépenser avant le 31 décembre. Une baisse de PIM n'est ni une baisse du coût, ni un abandon du projet. Entre deux années budgétaires, PIM et devengado ne sont pas comparés.
- **Usage** : le fichier de sortie est un fichier de travail, détaillé projet par projet. La fiche n'en reprend que des totaux.

## Étape 4 : consultations de ProInversión

`proinversion.py` lit les consultations publiées par ProInversión sur investinperu.pe et produit `exports/proinversion_<date>.xlsx`, un fichier de travail. Une copie datée est gardée dans le dossier des données (`proinversion/`). Le site n'est lu qu'une fois par jour (`--forcer` pour relire).

Ce que sont ces consultations : surtout les marchés de conseil que ProInversión passe pour préparer ses projets (structuration d'APP, études techniques, supervision, audit), et quelques autres services. Ce ne sont pas les appels d'offres des APP eux-mêmes. Elles montrent quels projets l'État prépare.

- **Source** : l'API publique du site, listes `concursos` et `expresiones-interes`. Le script vérifie qu'il a reçu exactement le nombre d'éléments annoncé, sans doublon. Le 25/11/2026, l'API donnait les mêmes 155 consultations que les pages du site, avec les mêmes statuts.
- **Accès** : un concours sur invitation (de 30 à 700 UIT, soit 165 000 à 3,85 millions de soles en 2026) n'est ouvert qu'aux entreprises invitées par ProInversión, ou à une entreprise en consortium avec l'une d'elles. Un concours public (plus de 700 UIT) est ouvert à tous. Les concours « SSE » recrutent la supervision spécialisée d'un projet APP. Un appel à manifestation d'intérêt sert à établir une liste courte avant un concours. Source : règlement des contrats de ProInversión (Acuerdo 161-1-2025-CD, en vigueur depuis le 1er janvier 2026).
- **Phase** : le statut affiché par le site (« En Proceso ») n'est pas toujours à jour. Pour les seules consultations qui ne sont pas affichées comme closes, le script lit leur page : date de convocatoria, date limite, et documents publiés. Il en déduit la phase : annulée, déclarée déserte, résultats publiés, offres reçues, délai dépassé, ou avant le dépôt des offres.
- **Nature** : chaque consultation est classée d'après des mots entiers de son titre (structuration, études, supervision, audit). C'est un classement indicatif : un titre qui ne contient qu'un nom de projet reste « non classé ».
- **Lien avec le MEF** : `correspondance_proinversion.csv`, une table faite à la main. Règle : une consultation n'est reliée à un projet du Banco de Inversiones que si un document officiel de ProInversión cite son code (CUI). Un rapprochement automatique par le titre ne marche pas (sigles, faux amis, projets sans code).
- **Suivi** : chaque copie est comparée à la précédente (nouvelles consultations, statut changé, consultation retirée), grâce au numéro de la consultation dans l'API.

Limites :
- **Dates** : la date donnée par l'API est celle de la mise en ligne de la fiche, pas celle de la convocatoria. L'année officielle est celle de l'étiquette « año ».
- **Ce que le script ne lit pas** : les PDF (bases, actes), donc ni les montants, ni le calendrier détaillé, ni le nom des entreprises candidates ou retenues.
- **Statuts** : « Concluido » ne distingue pas un concours attribué d'un concours annulé ou désert.
- **Usage** : le script fait une quinzaine de requêtes, au plus une fois par jour, et ne télécharge ni ne rediffuse les documents. Source à citer : investinperu.pe (ProInversión), avec la date de consultation.

## Étape 5 : fiche de deux pages

`fiche.py` rassemble les étapes 2 et 4 dans une fiche PDF de deux pages, `exports/fiche_<date>.pdf`, imprimée par Chrome à partir du modèle `fiche/modele.html`. Lecteur visé : une entreprise qui veut savoir quels grands projets publics existent, à quel stade, dans quels secteurs, par quel montage, et lesquels suivre.

La forme suit des règles observées dans des notes publiées par des cabinets de conseil et des institutions (Banque mondiale, OCDE, FMI, McKinsey, BCG, guides de graphiques de l'ONS et de la Banque mondiale) : chaque titre est un constat chiffré d'une phrase ; graphiques et tableaux numérotés, avec note et source dessous ; une couleur par stade, la même partout ; une seule police, une couleur d'accent et des gris.

Contenu :
- page 1 : titre-thèse, « À retenir », 4 chiffres clés, coût et budget par stade (graphique 1), secteurs et modes de réalisation découpés par stade (graphiques 2 et 3) ;
- page 2 : date de début inscrite des projets en études détaillées (graphique 4), taille des projets (graphique 5), les 10 plus gros projets pas encore en travaux (tableau 1), les 10 projets en travaux au plus gros budget de l'année (tableau 2), niveaux de gouvernement (graphique 6), comment suivre un projet, sources, méthode et mots du MEF.

**Stade d'un projet** (fonction `stade`), d'après les phases déclarées au MEF :
- avant exécution : pas de formato 8, la phase d'exécution n'est pas ouverte ;
- études détaillées : formato 8, parties A ou B (études détaillées, terrains), travaux pas lancés ;
- travaux : formato 8, partie C. Elle s'ouvre quand les études détaillées sont validées : le chantier peut être lancé ou encore à lancer ;
- clôture : formato 9 enregistré, travaux déclarés finis, contrats en liquidation. Un formato 9 « en attente de fin des travaux » reste en travaux.
La colonne ETAPA_F8 était vide dans les fichiers des 20 et 23/11/2026 : si plus de la moitié des grands projets n'ont pas de phase, le script s'arrête.

**Date de début inscrite** (graphique 4, tableau 1) : colonne FEC_INI_EJEC_FISICA, au format ISO. Pour un projet en études détaillées, c'est le plus souvent la date de début de toute la phase d'exécution, pas celle du chantier : la note dit « date de début inscrite », jamais « début des travaux ».

Ce qui est fait à la main :
- **`fiche/lecture.txt`** (à créer) : le texte « À retenir », la seule interprétation de la note, écrit par l'auteur (900 caractères au plus ; une ligne vide entre deux paragraphes). Tant qu'il manque ou est vide, le PDF s'appelle `fiche_<date>_brouillon.pdf`, porte la mention « brouillon » et n'est pas publié.
- **`fiche/noms_courts.csv`** et **`fiche/noms_consultations.csv`** : des noms courts en français pour les projets et les consultations affichés (les intitulés du MEF font souvent plus de 200 caractères). Un projet absent du fichier garde son nom du MEF, coupé avant le lieu.

Règles de présentation :
- aucune entreprise citée en dehors des intitulés officiels du MEF, aucune région classée (seulement les trois niveaux de gouvernement), pas de politique intérieure ;
- les titres sont des constats chiffrés, recalculés à chaque lancement : aucun chiffre n'y est écrit en dur ;
- les modes autres que le PPP (APP en espagnol), les travaux contre impôts, le marché public et la régie sont regroupés dans « Autres montages » ;
- budget et dépense ne parlent que des crédits publics : le coût d'un PPP comprend la part privée, son budget non ;
- avant l'impression, le script refuse la fiche si elle contient un nom de département brut du MEF (non raccourci), une valeur non calculée (nan) ou un mot de jugement dans un titre ;
- le script vérifie que le PDF fait exactement deux pages.

## Étape 6 : carte des grands projets

`carte.py` produit `exports/carte_<date>.html`, une carte interactive (folium, Leaflet) à ouvrir dans un navigateur connecté à Internet : Leaflet et le fond OpenStreetMap sont chargés en ligne. Deux générations sur les mêmes données donnent exactement le même fichier.

- **Un cercle par grand projet** : taille selon le coût (rayon proportionnel à la racine carrée du coût, donc surface proportionnelle au coût, avec un minimum de 3 px pour rester visible ; l'échelle est fixe, 28 px pour 30 Md S/, pour comparer deux dates) ; couleur selon le secteur, avec une case à cocher par secteur ; cercle creux si le projet n'a ni budget de l'année ni dépense passée. Un petit script remet les gros cercles derrière les petits, tous secteurs confondus, pour que chaque cercle reste cliquable.
- **Position** :
  - « déclarée » : le point du fichier du MEF, s'il est au Pérou. Les coordonnées rondes comme (-10, -76), mises faute de mieux, sont écartées.
  - « approchée » (contour en pointillé) : sinon, le point médian des projets localisés du même district dans tout le fichier, à défaut de la même province. Cela donne à peu près le centre de la localité, sans aucune donnée externe.
  - aucune : un projet déclaré sur plusieurs départements (-MUL.DEP-) ou sans lieu précis n'a pas de point. La légende commence par le nombre de projets absents et leur part du coût.
- Le 25/11/2026 : 838 points déclarés (62 % du coût), 489 positions approchées (36 %), 62 projets absents (3 %).

Limites : une route ou une voie ferrée n'est qu'un point (souvent le début du tracé) ; plusieurs projets peuvent partager le même point ; le fond OpenStreetMap est fourni sans garantie (politique d'usage des tuiles d'OpenStreetMap).

## Étape 7 : note de trois pages

`note.py` produit `exports/note_<date>.pdf`, la note publiée sur la page du projet, imprimée par Chrome à partir du modèle `note/modele.html` et de la feuille de style `note/style.css`. C'est une version plus courte et plus lisible que la fiche : un court essai en prose, avec deux graphiques et un tableau, chacun commenté. Elle reprend les calculs de l'étape 2 et le classement par stade de l'étape 5.

La ligne directrice : les grands projets réunissent deux générations. Les chantiers en cours, déclarés viables il y a près de neuf ans en médiane (au 25/11/2026), reçoivent l'essentiel du budget de l'année ; la vague suivante, pas encore en travaux, pèse plus de la moitié du coût, et onze projets de 5 milliards de soles ou plus en font près de la moitié.

Contenu :
- page 1 : chapeau, 3 chiffres clés, coût prévu, budget de l'année et programme multiannuel répartis par stade (graphique 1) ;
- page 2 : coût selon l'année de déclaration de viabilité (graphique 2), marché public et PPP dans chaque génération ;
- page 3 : les projets de la vague à venir qui coûtent 5 milliards de soles ou plus (tableau), « À retenir », sources et méthode.

Règles :
- le texte est écrit à la main dans `note/modele.html`, mais chaque chiffre est recalculé à chaque lancement ;
- les phrases qui comparent (« plus de la moitié », « près de neuf ans », « onze projets »...) sont protégées par des garde-fous (fonction `verifier_le_texte`) : si les données ne les confirment plus, le script s'arrête et demande de relire le texte ;
- **âge d'un projet** : temps écoulé depuis sa déclaration de viabilité (colonne `FECHA_VIABILIDAD`, au format ISO), en médiane sur un groupe de projets ;
- **arrondis** : à la française, arrondi commercial (726,5 donne 727, fonction `fr` de `fiche.py`) ; les milliards de soles sont entiers au-delà de 100, avec une décimale en dessous ;
- mise en page : le script mesure la place libre sur chaque page (Chrome sans interface), la donne aux graphiques et à l'interligne du tableau, et s'arrête si une page déborde ; le PDF fait au plus trois pages ;
- mêmes contrôles que la fiche avant l'impression (nom de département brut, valeur non calculée).

Limites : la note ne dit rien des contrats, des entreprises ni du contexte politique ; elle s'en tient à ce que montre le fichier du MEF.
