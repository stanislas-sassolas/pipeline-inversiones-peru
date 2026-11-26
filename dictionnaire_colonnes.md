# Dictionnaire des colonnes du Banco de Inversiones (MEF)

Source : fichier `DETALLE_INVERSIONES.csv`, version du 13/11/2026 (150 633 investissements actifs, 68 colonnes dont 67 gardées). Les montants sont en soles (PEN). Les chiffres entre crochets décrivent la version du 13/11.

Le MEF publie un dictionnaire officiel, en espagnol et très court, à côté du fichier : https://datosabiertos.mef.gob.pe/dataset/detalle-de-inversiones (ressource « Detalle_Inversiones_Diccionario »). Les définitions ci-dessous le complètent avec les textes d'Invierte.pe et des tests sur les données.

## Notions à connaître avant de lire les colonnes

- **Invierte.pe** : le système qui encadre l'investissement public au Pérou depuis 2017 (décret législatif 1252). Il a remplacé le **SNIP**. Un investissement suit un cycle : programmation, formulation et évaluation (on décide s'il est viable), exécution (études détaillées puis travaux), fonctionnement.
- **Projet d'investissement** : il crée, agrandit, améliore ou récupère la capacité à rendre un service. Son nom commence d'ailleurs par CREACION, AMPLIACION, MEJORAMIENTO ou RECUPERACION.
- **IOARR** (optimisation, agrandissement marginal, réhabilitation, remplacement) : une intervention ponctuelle sur un équipement qui fonctionne déjà. Elle ne crée pas de nouvelle capacité (l'agrandissement est plafonné à 20 %). Elle n'a pas d'étude de viabilité : elle est simplement « approuvée ». Une IOARR n'est pas forcément petite en montant.
- **Le budget d'une année** :
  - le **PIA** est le budget initial de l'entité ;
  - le **PIM** est ce budget après les modifications de l'année ;
  - la **certification** réserve des crédits ;
  - l'**engagement** (compromiso) enregistre une obligation née d'un contrat ;
  - le **devengado** reconnaît qu'on doit payer, une fois les travaux ou services reçus ; le paiement vient juste après.

  Le devengado est l'indicateur standard de ce qui a été réellement exécuté.

## 1. Les 15 colonnes clés

| Colonne | Définition | Valeurs [13/11] | À savoir |
|---|---|---|---|
| `NIVEL` | Niveau de gouvernement de l'entité qui a formulé l'investissement. | GN (État central) 12 727 ; GR (régions) 13 677 ; GL (communes) 124 229 | Parmi les projets de plus de 100 M : 761 GN, 438 GR, 176 GL. Les grands projets sont surtout nationaux. |
| `SECTOR` | Ministère ou ensemble auquel appartient cette entité. | 35 valeurs, dont « GOBIERNOS LOCALES », « TRANSPORTES Y COMUNICACIONES », « SALUD » | Pour les régions et les communes, il vaut juste « GOBIERNOS REGIONALES » ou « GOBIERNOS LOCALES » : il ne dit pas le domaine. Pour le domaine, utiliser `FUNCION`. |
| `ENTIDAD` | L'entité budgétaire (« pliego ») qui a formulé et évalué l'investissement. | Ex. « AUTORIDAD DE TRANSPORTE URBANO PARA LIMA Y CALLAO - ATU » | L'exécution peut être confiée à une autre unité : voir `NOMBRE_UEI` et `NOMBRE_UEP`. |
| `FUNCION` | Le domaine d'action publique (classification budgétaire). | 32 valeurs : TRANSPORTE 36 237, EDUCACIÓN 19 755, SANEAMIENTO 19 479… | C'est la colonne à utiliser pour regrouper par secteur dans la fiche. |
| `SITUACION` | Où en est la décision sur l'investissement. | VIABLE 104 573 ; APROBADO 45 824 ; EN FORMULACION 236 | VIABLE : l'étude préalable a montré que le projet réduit un déficit d'infrastructure ou de service, qu'il est socialement rentable et durable (projets et programmes). APROBADO : IOARR et IRI, approuvées sans étude de viabilité. EN FORMULACION : pas encore déclaré viable ; ce sont surtout d'anciens projets SNIP restés à ce stade. |
| `EXPEDIENTE_TECNICO` | L'expediente técnico (ou le document équivalent) est-il enregistré ? | SI 100 942 ; NO 49 691 | L'expediente técnico (plans et devis détaillés) n'est exigé que s'il y a des travaux ; pour de l'équipement, on utilise un document équivalent. Pour un projet de travaux, passer de NO à SI est un signal fort que les travaux approchent. |
| `AVANCE_FISICO` | Avancement physique des travaux déclaré par l'entité, en %. | Rempli pour 64 481 investissements ; médiane 95 | **Données sales** : certaines valeurs dépassent largement 100 (jusqu'à plus de 200 millions). Ne garder que 0 à 100. Rempli seulement si `TIENE_AVAN_FISICO` = SI. |
| `COSTO_ACTUALIZADO` | Coût total de l'investissement, mis à jour au fil des études et des modifications. | Médiane 1,3 M ; maximum 30,5 Md (train Marcona-Andahuaylas) | Coût **pluriannuel et indicatif** : ce n'est pas de l'argent engagé. C'est la colonne du seuil des 100 M. |
| `MONTO_VIABLE` | Coût au moment de la déclaration de viabilité (ou de l'approbation). | Égal au coût actualisé pour 36 % des investissements | L'écart avec `COSTO_ACTUALIZADO` montre de combien le coût a dérivé depuis la décision. |
| `PIM_ANIO_ACTUAL` | Budget modifié (PIM) prévu pour cet investissement en 2026. | 0 pour plus de la moitié | Le meilleur indicateur de « cette année, l'État met vraiment de l'argent dessus ». Ex. ligne 3 du métro : 1,2 M de PIM pour 23,6 Md de coût. |
| `DEV_ANIO_ACTUAL` | Devengado 2026, depuis le début de l'année jusqu'à la date du fichier. | 0 pour plus de la moitié | Taux d'exécution 2026 = devengado / PIM (même calcul que la « Consulta Amigable » du MEF). Pour un groupe de projets : somme des devengados / somme des PIM, pas la moyenne des taux, et seulement là où le PIM est supérieur à 0. Au 13/11, c'est un taux partiel. |
| `DES_MODALIDAD` | Mode de réalisation. | 130 libellés. Contrata 81 491 ; administración directa 39 765 ; obras por impuestos 2 666… | **Plusieurs modes peuvent figurer dans une même case**, séparés par une virgule, et les libellés varient (« NÚCLEO EJECUTOR » / « NUCLEO EJECUTOR »). Il faut séparer et normaliser avant de compter. Voir le détail plus bas. |
| `TIPO_INVERSION` | Type d'investissement. | PROYECTO DE INVERSION 83 291 ; INVERSIONES IOARR 40 747 ; PIP MAYOR / MENOR (SNIP) ; INTERVENCIONES IRI 5 082 ; PROGRAMA DE INVERSION ; PROYECTO EMBLEMATICO 113… | IRI = interventions de reconstruction, nées après El Niño côtier de 2017 (loi 30556 et Autorité pour la reconstruction, ARCC, dissoute fin 2023 ; l'ANIN a repris son portefeuille). Elles sont approuvées sans étude de viabilité. |
| `IND_IOARR_EMERG` | L'investissement est-il une IOARR d'urgence ? | SI 3 152 ; NO 147 481 | IOARR réalisée dans une zone en état d'urgence déclaré, pour un danger imminent ou après une catastrophe. Elle peut donc être préventive. Le drapeau couvre toutes les urgences (pluies, séismes, COVID-19…). Pour isoler El Niño 2026, il faut regarder les dates récentes et les régions concernées. |
| `DEPARTAMENTO` | Département où se trouve l'investissement. | 24 départements + la province du Callao, plus « -MUL.DEP- » pour les projets sur plusieurs départements | Avec `PROVINCIA`, `DISTRITO` et `UBIGEO` (code géographique INEI à 6 chiffres). |

### Les modes de réalisation (`DES_MODALIDAD`)
- **Administración directa** : l'entité réalise les travaux elle-même, avec son personnel et son matériel.
- **Administración indirecta**, l'entité fait faire. Ses variantes :
  - **por contrata** : marché public classique ;
  - **obras por impuestos (OxI, loi 29230)** : une entreprise finance et réalise l'ouvrage, puis l'État la rembourse avec des certificats qu'elle utilise pour payer son impôt sur le revenu ;
  - **APP** : partenariat public-privé ;
  - **gobierno a gobierno (G2G)** : accord d'État à État ;
  - **núcleo ejecutor** : une organisation de bénéficiaires reçoit les fonds et fait réaliser l'ouvrage.

## 2. Les autres colonnes

### Identification
| Colonne | Définition |
|---|---|
| `CODIGO_UNICO` | Identifiant unique de l'investissement. **C'est la clé pour comparer deux archives.** |
| `CODIGO_SNIP` | Ancien code SNIP ; égal au code unique pour presque tous les investissements récents. |
| `NOMBRE_INVERSION` | Nom officiel. Il suit une formule fixe : nature de l'intervention, service, lieu. |
| `MARCO` | Cadre sous lequel l'investissement a été formulé puis déclaré viable ou approuvé : INVIERTE (depuis 2017) 129 417 ; SNIP (avant) 21 216. |
| `ESTADO` | Toujours ACTIVO : le fichier ne contient que les investissements actifs. |
| `ANIO_PROCESO` | Année budgétaire des données (2026). |

### Acteurs
| Colonne | Définition |
|---|---|
| `NOMBRE_OPMI` | Bureau de programmation (OPMI) de l'entité : il établit le programme multiannuel d'investissements, suit le portefeuille et fait l'évaluation après coup. |
| `NOMBRE_UF` | Unité formulatrice (UF) : elle prépare l'étude préalable, déclare la viabilité des projets et approuve les IOARR. |
| `NOMBRE_UEI` | Unité exécutrice des investissements (UEI) : elle prépare l'expediente técnico et exécute l'investissement. C'est elle qui remplit les formats de suivi 8 et 12-B. |
| `SEC_EJEC` | Code de l'unité exécutrice budgétaire. |
| `NOMBRE_UEP` | Unité exécutrice budgétaire (UEP) : celle qui porte les crédits et paie. |

### Dates
| Colonne | Définition |
|---|---|
| `FECHA_REGISTRO` | Date d'enregistrement dans le système. |
| `FECHA_VIABILIDAD` | Date de la déclaration de viabilité ou de l'approbation. |
| `PRIMER_DEVENGADO`, `ULTIMO_DEVENGADO` | Mois du premier et du dernier devengado, au format AAAAMM (ex. 202609). |
| `FEC_INI_EJECUCION`, `FEC_FIN_EJECUCION` | Début et fin de toute la phase d'exécution (expediente técnico compris), enregistrés dans le format 8. |
| `FEC_INI_EJEC_FISICA`, `FEC_FIN_EJEC_FISICA` | Début et fin des travaux, déclarés dans le format 12-B. Ils peuvent être prévus ou réels. |
| `ULT_FEC_DECLA_ESTIM` | Dernière mise à jour du format 12-B par l'UEI. Utile pour repérer les projets dont personne n'a rien déclaré depuis longtemps. |

### Classification
| Colonne | Définition |
|---|---|
| `PROGRAMA`, `SUBPROGRAMA` | Niveaux plus fins sous `FUNCION`. |
| `DES_TIPOLOGIA` | Type d'ouvrage (ex. CARRETERAS VECINALES, INFRAESTRUCTURA DE RIEGO). 225 valeurs, vide pour environ 1 investissement sur 5. |
| `ALTERNATIVA` | Description technique de la solution retenue. **Retirée à l'archivage.** |

### Programmation multiannuelle
| Colonne | Définition |
|---|---|
| `REGISTRADO_PMI` | L'investissement figure-t-il au programme multiannuel d'investissements (PMI) ? SI 58 644. |
| `PMI_ANIO_1` à `PMI_ANIO_4` | Montants programmés dans le PMI pour l'année en cours (année 1 = 2026) puis les trois suivantes. |

### Budget (en plus de PIM et devengado 2026)
| Colonne | Définition |
|---|---|
| `PIA_ANIO_ACTUAL` | Budget initial 2026 (PIA). Rempli pour 49 642 investissements seulement. |
| `CERTIF_ANIO_ACTUAL` | Montant certifié en 2026 : crédits réservés avant de s'engager. |
| `COMPROM_ANUAL_ANIO_ACTUAL` | Engagement 2026 : la part de l'année des obligations nées d'un contrat. Il ne peut pas dépasser le montant certifié. |
| `DEVEN_ACUMUL_ANIO_ANT` | Devengado cumulé des années précédentes. |
| `SALDO_EJECUTAR` | Solde restant à exécuter à partir de 2027 : coût actualisé moins devengado des années passées moins PIM 2026 (vérifié sur 92 % des investissements). Environ 5 % des valeurs sont négatives. |
| `AVANCE_EJECUCION` | Avancement d'exécution global, en %. Le MEF ne publie pas la formule ; il est proche du devengado cumulé divisé par le coût actualisé. **Données sales** : ne garder que 0 à 100. |
| `MONTO_ET_F8` | Coût indiqué dans l'expediente técnico, enregistré dans le format 8. |

### Formats de suivi d'Invierte.pe
| Colonne | Définition |
|---|---|
| `TIENE_F8`, `ETAPA_F8` | Le format 8 (enregistrements de la phase d'exécution) existe-t-il, et quelle section est atteinte. A : vérification de la cohérence avec l'étude de viabilité, avant l'expediente técnico. B : expediente técnico. C : exécution physique. |
| `TIENE_F12B`, `TIENE_AVAN_FISICO` | Le format 12-B (suivi mensuel de l'exécution) est-il rempli, et l'avancement physique déclaré ? |
| `TIENE_F9`, `FEC_REG_F9`, `ETAPA_F9` | Le format 9 (clôture) existe-t-il, sa date, et son étape (en attente de liquidation, clôture…). |
| `INFORME_CIERRE` | Rapport de clôture. Presque toujours NO dans ce fichier. |

### Contrôle et litiges
| Colonne | Définition |
|---|---|
| `CTRL_CONCURR` | Coût du contrôle concomitant de la Contraloría (contrôle pendant l'exécution), compris dans le coût de l'investissement. La loi l'impose pour les gros investissements et y réserve un petit pourcentage du coût (2 % au plus). Non nul pour 11 782 investissements. |
| `MONTO_LAUDO` | Coût des litiges avec les prestataires, surtout des sentences arbitrales (« laudos »). Non nul pour 1 507 investissements. |
| `MONTO_FIANZA` | Montant de la garantie bancaire (« carta fianza ») enregistrée. Non nul pour 138 investissements seulement. Garantie constituée ou exécutée : non précisé. |

### Localisation et bénéficiaires
| Colonne | Définition |
|---|---|
| `PROVINCIA`, `DISTRITO`, `UBIGEO` | Province, district, code géographique INEI. |
| `LATITUD`, `LONGITUD` | Coordonnées GPS, pour la carte. |
| `NUM_HABITANTES_BENEF` | Nombre de bénéficiaires déclaré. **Données sales** : maximum de 857 millions, pour un pays d'environ 34 millions d'habitants. |

## 3. Pièges repérés dans les données

1. `AVANCE_FISICO`, `AVANCE_EJECUCION` et `NUM_HABITANTES_BENEF` contiennent des valeurs aberrantes : filtrer avant tout calcul.
2. `DES_MODALIDAD` mélange parfois plusieurs modes dans une case et les écrit de façons différentes : séparer et normaliser avant de compter.
3. `SECTOR` ne dit pas le domaine pour les régions et les communes : utiliser `FUNCION`.
4. `COSTO_ACTUALIZADO` est un coût indicatif sur plusieurs années, pas un engagement.
5. `PIA`, `CERTIF` et `COMPROM` ne sont remplis que pour un tiers des investissements.
6. Un taux d'exécution de groupe se calcule avec des sommes (somme des devengados / somme des PIM), pas avec une moyenne de taux.

## Points non confirmés

- La formule exacte d'`AVANCE_EJECUCION`.
- Le sens précis de `MONTO_FIANZA` (garantie constituée ou exécutée).
- La signification de `PROYECTO EMBLEMATICO` (sans doute le programme des « colegios emblemáticos » du ministère de l'Éducation, à confirmer).

## Sources principales

- Dictionnaire officiel du MEF : https://datosabiertos.mef.gob.pe/dataset/detalle-de-inversiones
- Directive générale d'Invierte.pe : https://cdn.www.gob.pe/uploads/document/file/3246495/directiva01-2019.pdf.pdf
- Lignes directrices sur les IOARR (MEF, 2025) : https://www.mef.gob.pe/contenidos/inv_publica/docs/Metodologias_Generales_PI/Lineamientos_IOARR.pdf
- Glossaire budgétaire du MEF : https://www.mef.gob.pe/contenidos/presu_publ/glosario/glosario_terminologia_basica_adm_financiera.pdf
- Obras por impuestos, questions fréquentes : https://www.mef.gob.pe/es/obras-por-impuestos/preguntas-frecuentes
