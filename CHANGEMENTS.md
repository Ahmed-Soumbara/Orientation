# Changements du 3 novembre

Base : le dépôt d'Ahmed (data.py, engine.py, tree.py, api.py). Rien n'a changé dans la façon de lancer le projet.

## Corrections du moteur

1. **Confiance (engine.py).** Elle baissait pour une formation sur deux. Le code comparait les admis ayant une mention à *tous* les admis. Or seuls les néo-bacheliers ont une mention : sur le fichier 2025, environ un admis sur quatre n'est pas néo-bachelier. On compare maintenant à `acc_neobac`.
2. **Taux d'accès (engine.py, tree.py).** Le code utilisait admis / candidats, qui sous-estime fortement la réalité. Par exemple, une formation à 77 % de taux d'accès officiel donnait 13 %, et presque tout devenait « très sélectif ». On utilise maintenant `taux_acces_ens`, le taux officiel publié par Parcoursup. Pour un groupe d'établissements, c'est une moyenne pondérée par le nombre de candidats.
3. **Formations très demandées (engine.py).** Si moins de 20 % des candidats reçoivent une proposition, la zone ne dépasse pas « marge ». Exemple : BUT TC d'Évry, 13 % de taux d'accès, alors que la moitié des admis ont la mention assez bien. Avoir le profil des admis n'y suffit pas.
4. **Seuils alignés sur le site.** Cœur à partir de 40 % des admis, marge à partir de 12 %. Ce sont des règles de l'application, à faire valider.

## Correction des domaines (tree.py)

Les mots-clés étaient cherchés comme des morceaux de mots :

- « las » trouvait « c**las**se préparatoire », si bien que les prépas littéraires tombaient en Santé.
- « ect » trouvait « s**ect**eur », si bien que les diplômes d'infirmier tombaient en Commerce.
- Les licences de droit tombaient en Commerce, à cause de « gestion » dans « Droit-économie-gestion ».

Résultat avant correction : **1 seule formation** en Droit. On utilise maintenant des mots entiers, testés dans un ordre fixe, et Droit compte **630 formations**.

## Nouvelles colonnes lues (data.py)

`acc_neobac`, `taux_acces_ens`, `contrat_etab` (public ou privé, utile pour le budget) et `lib_for_voe_ins`.

## Site (static/index.html)

C'est la version 4 du prototype : 3 onglets, alternance, bourses, comparateur, espaces parent et établissement, et « Comment c'est calculé ? » partout.

- Servi par `api.py`, il recharge les données à jour depuis `/api/raw.csv` (fonction `loadServer`).
- Ouvert seul, il utilise les données 2025 intégrées dans la page.

## Tests

`python -m pytest test_engine.py` : 11 tests, dont 3 nouveaux (confiance, taux officiel et plafond, domaines).

## Spécialités des admis (4 novembre)

- `data.py` télécharge aussi le jeu « spécialités des bacheliers généraux » (`download_specialites`) et garde les colonnes `doublette`, `formation` et `acceptations` dans `data/specialites.csv`. L'adresse d'export est à vérifier au premier lancement, comme pour le premier jeu.
- `api.py` expose `/api/specialites.json`, qui renvoie une liste vide tant que le fichier n'est pas téléchargé.
- Le site n'a plus de zone de dépôt de fichier : il lit les deux jeux sur le serveur. Ouvert seul, sans serveur, il utilise les formations 2025 intégrées et des spécialités d'exemple signalées comme telles.
- Un nouveau test couvre `/api/specialites.json`. Au total : 12 tests.

## Ce qui reste à faire

- L'open data Parcoursup ne contient presque pas de formations en apprentissage (3 lignes en 2025). Pour l'alternance, il faut une autre source : le catalogue de l'apprentissage.
- Protéger `/api/refresh` par une clé d'administration.

## Sources publiques supplémentaires (4 novembre, nuit)

Nouveau fichier `sources.py` : un connecteur par source, testé sans réseau (`test_sources.py`, 8 tests). `python data.py` les met toutes à jour après Parcoursup. Une source qui échoue est signalée et l'application garde ses valeurs de secours.

| Source | Ce qu'elle remplace | Accès |
| --- | --- | --- |
| InserSup (ministère de l'Enseignement supérieur) | Débouchés écrits à la main : taux d'emploi à 12 et 30 mois, salaire médian, résultats des apprentis | API open data, sans clé |
| Carte des loyers 2025 (ministère du Logement) | Loyer moyen fixe : loyer au m² de la commune × 25 m² | API data.gouv.fr, sans clé |
| Fiches métiers Idéo (Onisep) | Liste de 17 métiers d'exemple | API data.gouv.fr, sans clé |
| Catalogue de l'apprentissage | Années d'alternance estimées par voie | API publique, adresse à vérifier |
| Communes (geo.api.gouv.fr) | « Même région = chez tes parents » : distance réelle, 40 km par défaut | API appelée à la demande, sans clé |
| `ref/baremes.json` | Barèmes codés dans le site (droits, bourses, apprentis, coût de la vie) | Fichier de référence, sources citées dedans |
| `ref/frais_ecoles.csv` | Ordre de grandeur unique pour les écoles privées | À remplir par l'équipe : une ligne par école, avec l'URL et la date du relevé |

Nouveaux points d'accès : `/api/sources`, `/api/insertion`, `/api/loyers`, `/api/metiers`, `/api/apprentissage`, `/api/communes`, `/api/baremes`, `/api/frais-ecoles`.

Le site affiche l'état de chaque source (Plus › Données et sources) et demande la commune de l'élève dans son profil.

**À faire au premier lancement :**
1. `python data.py`, puis `python sources.py --check` : affiche les colonnes reçues de chaque source.
2. Si une source échoue, son message d'erreur indique les colonnes réellement reçues. Il suffit d'ajouter le bon nom dans l'appel `pick(...)` correspondant de `sources.py`.

Les formats ont été écrits d'après la documentation des producteurs, mais n'ont pas pu être testés sur les vrais fichiers (pas d'accès réseau depuis l'environnement de développement).

Le rattachement des métiers à un objectif et celui des diplômes InserSup à une voie sont des règles de l'application (`METIER_RULES` et `INSERTION_RULES` dans `static/index.html`). Elles sont affichées comme telles.

## Connecteurs vérifiés sur les vraies réponses (4 novembre, 2 h)

Écrits à partir de la sortie de `explorer_api.py` lancé sur l'ordinateur de l'équipe :

- **InserJeunes** (data.education.gouv.fr, sans clé) : nouveau connecteur. On garde, par lycée et par diplôme, le dernier millésime de poursuite d'études et d'emploi à 6, 12 et 24 mois. La fiche d'un BTS en lycée affiche le devenir de ses sortants (`/api/inserjeunes`).
- **API Apprentissage** (clé gratuite, `APPRENTISSAGE_TOKEN`) : le connecteur utilise la route qui a répondu (`/api/formation/v1/search`) et la structure réelle (commune, département, UAI, coordonnées). L'intitulé est cherché sous la clé `intitule`.
- **Onisep** : son portail est en maintenance (page « Site en maintenance », API en 403). La source est signalée comme telle et relancée automatiquement à chaque `python data.py`.
- **Clés d'accès** : le code lit maintenant le fichier `.env` tout seul (`load_env` dans `sources.py`). Le nouveau `.gitignore` empêche de l'envoyer sur GitHub.
- **Les dépôts de fichiers manuels sont supprimés.**

Tests : 23.

## Résultats réels et métiers France Travail (4 novembre, 3 h)

Premier lancement complet sur l'ordinateur de l'équipe : InserSup (filtré côté serveur) 1 613 lignes en 6 s ; loyers OK ; API Apprentissage 60 031 formations en 113 s ; InserJeunes OK ; Onisep en maintenance.

- **Apprentissage** : le connecteur lit maintenant le lieu réel de la formation (`lieu.adresse`), le niveau, la durée et les **codes métiers ROME** visés (`certification.valeur.domaines.rome.rncp`). Structure vérifiée sur la vraie réponse.
- **Métiers** : nouvelle source « Métiers ROME 4.0 » (France Travail, clés `FT_CLIENT_ID` et `FT_CLIENT_SECRET`). Elle prend le relais de l'Onisep. `/api/metiers` relie chaque métier aux formations en apprentissage qui y mènent, grâce au code ROME : c'est un lien officiel, pas une règle de l'application.

Tests : 26.

## Moins de « fait main » (4 novembre, 3 h 30)

| Avant (écrit par l'équipe) | Maintenant (donnée réelle) | Source |
| --- | --- | --- |
| Poids de chaque voie de bac par voie | Part réelle d'admis par type de bac, voie par voie (ex. BUT TC : 52 % de bacs techno) | Parcoursup `acc_bg`, `acc_bt`, `acc_bp` |
| Année de début de l'alternance estimée | Année la plus fréquente de début du contrat et nombre de formations en apprentissage | API Apprentissage `modalite.annee_cycle` |
| Débouchés en texte | Métiers visés par les formations de la voie, avec un lien vers la fiche France Travail | API Apprentissage (codes ROME) + France Travail |
| Matières clés par domaine | Spécialités suivies par au moins 40 % des admis | Open data Parcoursup, spécialités |
| Calendrier « mi-janvier, mi-mars… » | Dates officielles Parcoursup 2027 | parcoursup.gouv.fr |

Les anciennes valeurs restent en secours, affichées comme « estimation de l'équipe » quand la donnée manque.

À faire : relancer `python sources.py apprentissage`, qui récupère maintenant l'année de début.

Tests : 27.

## Passerelles et plan d'action sourcés (4 novembre, v13)

Règle appliquée : ce qui ne peut pas être sourcé est retiré, pas maquillé.

**Passerelles.** Chaque passerelle affiche maintenant le texte qui la décrit, avec un lien.

| Passerelle | Source |
| --- | --- |
| BUT ou BTS → prépa ATS → école d'ingénieurs | Communiqué Arts et Métiers sur le concours ATS (déc. 2025) |
| BUT → cycle ingénieur sur dossier | Université de Reims (fév. 2025) ; chiffres CDEFI via L'Étudiant (déc. 2024) |
| BUT → master | Ministère : le BUT confère le grade de licence |
| Licence → école d'ingénieurs | L'Étudiant (déc. 2024) |
| BUT TC/GEA, BTS, licence éco → école de commerce | Règlement 2025 du concours Passerelle (BSB, EM Normandie, IMT-BS) |
| LAS → MMOPK, PASS → L2 | Pages Parcoursup sur les études de santé |
| Licence ou khâgne → master en IEP | Règlements 2025-2026 de Sciences Po Lille |
| Licence → ENS | Onisep |
| Licence de droit → CRFPA | IEJ de l'UVSQ |

Retiré : « avocat via Sciences Po ». La liste des diplômes équivalents au master 1 de droit date de 1998 et le CNB demande sa révision : on ne peut pas affirmer cette voie. Les durées et les « moins cher », « moins de risque » non sourcés sont aussi retirés.

**Plan d'action.** Les objectifs du type « passer de 11 à 12,5 au prochain trimestre » sont supprimés : aucune source ne permet de prédire l'évolution des notes. Le plan montre maintenant :

- le repère : la mention d'au moins 40 % des admis (open data Parcoursup ; le seuil de 40 % reste une règle de l'application), et l'écart, sans calendrier ;
- ce que la formation verra : bulletins de première et de terminale (instruction DGER/SDES/2024-644), contenu de la fiche Avenir (Éduscol) ;
- les spécialités des admis, seulement avec les vraies données ;
- une méthode de travail tirée de Dunlosky et al. (2013) : se tester et étaler ses révisions ;
- le rôle du professeur principal dans la fiche Avenir ;
- l'année de début de l'alternance, seulement si l'API Apprentissage l'a fournie.

Les éléments communs à toutes les cibles sont regroupés dans une seule carte.

**Frais des écoles privées : retirés.** `ref/frais_ecoles.csv`, `load_frais` et `/api/frais-ecoles` sont supprimés. Pour un établissement privé, le budget indique que ses frais ne sont pas publiés en open data et ne les compte pas.

Tests : 28, dont un qui vérifie que chaque passerelle cite une source.

## Critères d'examen des vœux (4 novembre, 4 h, v15)

Chaque formation publie sur sa fiche Parcoursup sa grille d'examen : le poids de chaque catégorie (résultats, méthodes, savoir-être, motivation) et, pour chaque critère, les éléments évalués et leur importance (complémentaire, important, très important, essentiel). Ces critères ne sont pas dans l'open data : la méthodologie 2025 le confirme.

- `explorer_parcoursup.py` a montré que les critères sont dans la page elle-même, sans JavaScript, en 0,6 s.
- `sources.py` : `parse_fiche_criteres` lit la grille et les critères ; `criteres(g_ta_cod)` lit une fiche à la demande puis la garde dans `data/criteres/`. Pas d'attente de plusieurs heures : une fiche n'est lue que quand quelqu'un l'ouvre. Le catalogue complet reste possible, par tranches et avec reprise : `python sources.py criteres --tout --budget 3600`.
- `api.py` : `/api/criteres/{g_ta_cod}`.
- Site : nouvelle carte « Ce que la commission regarde » sur la fiche de chaque formation. Le plan d'action part de ces critères, du plus au moins important, relie les matières citées aux notes de l'élève et reprend les conseils de la formation pour le projet motivé. Les textes de la formation sont reproduits tels quels, avec le lien et la date de relevé.
- Ouvert seul, le site contient une fiche réelle d'exemple : la licence de droit d'Évry (`fixtures/fiche_10945.html`).

Constat utile pour l'oral : cette formation dit regarder la « moyenne des notes obtenues, progression, moyenne de la classe ». La comparaison d'une note à la moyenne de la classe vient donc de la formation elle-même.

Licence : contenus Parcoursup sous Licence Ouverte Etalab 2.0 sauf mention contraire. Les critères étant rédigés par chaque formation, la réutilisation reste à confirmer avec le ministère.

Tests : 30.

## Vérification du décodage sur toutes les filières (v16)

`python sources.py criteres --verifier 30` lit environ 30 fiches tirées au hasard dans les 11 filières (CPGE, BTS, BUT, licences, LAS, PASS, IFSI, travail social, écoles d'ingénieurs, écoles de commerce, autres), à une seconde d'intervalle. Il affiche pour chacune si la grille et les critères ont été lus. Une fiche non décodée est enregistrée dans `explore_parcoursup/` pour qu'on adapte le décodage.

## Contrôles, chapitres et épreuves anticipées (4 novembre, 5 h, v18)

Le plan d'action a maintenant son étage « ce que tu fais », à partir des contrôles de l'élève.

- **`ref/programmes.json`** : chapitres et types d'exercice transcrits des textes officiels, chacun avec sa source. Rien n'est écrit de mémoire.
  - Maths, première : nouveau programme de spécialité (arrêté du 26 février 2026, BO n° 14 du 2 avril 2026), en vigueur à la rentrée 2026.
  - Maths, terminale : laissé vide. En 2026-2027 la terminale suit encore le programme de 2019, que je n'ai pas pu récupérer. Le fichier le dit (`a_completer`).
  - Français, première : types d'exercice de l'épreuve anticipée (note de service du 23 juillet 2020).
  - Épreuves anticipées de français et de maths (format, coefficient, barème), avec leurs réserves.
  - Servi par `/api/programmes`.
- **Site, « Où j'en suis » › Mes contrôles** :
  - l'élève saisit un contrôle (date, note, moyenne de la classe si elle est donnée, chapitres cochés), ou un contrôle à venir ;
  - pour un contrôle à venir, l'application propose des séances de test 5, 3 et 1 jours avant ;
  - un tableau donne, par chapitre, l'écart à la moyenne de la classe (le contrôle le plus récent compte pour 1, le précédent pour ½…), avec « peu de données » quand il n'y a qu'un contrôle.
- **Plan d'action**, carte « Pour toutes tes cibles » :
  - les prochains contrôles avec leurs séances ;
  - le chapitre le plus fragile de chaque matière et l'action proposée ;
  - les épreuves anticipées de l'année.
  Quand une formation cite une matière dans ses critères, le plan indique le point le plus fragile de l'élève dans cette matière.
- Le persona a quatre contrôles d'exemple et un contrôle à venir, fictifs comme ses notes.

Règles de l'application, affichées comme telles : les poids 1, ½, ¼ et les séances 5, 3 et 1 jours avant. Aucune note n'est prédite.

Tests : 31, dont un qui vérifie que chaque chapitre a une source et que le site embarque la même version du fichier.

## Maths de terminale (v19)

Chapitres de la spécialité maths de terminale ajoutés à `ref/programmes.json`, à partir de l'annexe officielle de l'arrêté du 26 février 2026 (BO n° 14 du 2 avril 2026, fichier daté du 19 mars 2026). Ce programme s'applique à la **rentrée 2027**. En 2026-2027, les terminales suivent encore le programme de 2019 : le site l'indique dans un encadré, sous le formulaire.

## Graphique « Ta moyenne de la 2nde au bac » (v20)

L'ancien graphique plaçait les points en zigzag à des hauteurs fixes : la hauteur ne correspondait pas à la note, et les trimestres à venir avaient des « ? » placés au hasard. Il est remplacé par un vrai graphique :

- la hauteur de chaque point correspond à la moyenne du trimestre, sur une échelle graduée ;
- une zone surlignée montre les trimestres dont les notes remontent dans Parcoursup (toute la première, terminale T1 et T2 ; instruction DGER/SDES/2024-644) ;
- une ligne pointillée donne le repère de la première cible ;
- les trimestres à venir restent vides : rien n'est prédit.

## Refonte visuelle et rédactionnelle (v21)

Seul `static/index.html` change. Le moteur, les calculs, les données et les attributs `data-*` sont intacts : 31 tests sur 31.

- **Direction** : le matériel scolaire. Texte à l'encre bleue, repères au stylo rouge, trois surligneurs pour les zones (vert : dans le cœur, jaune : à la marge, rose : en dessous).
- **Police** : Schibsted Grotesk, intégrée au fichier. Le site s'affiche pareil sans connexion.
- **Courbe « De la seconde au bac »** : tracée sur un quadrillage Seyès, avec la marge rouge comme axe. Une accolade montre les bulletins qui partent dans Parcoursup.
- **Où tu te situes** : les admis sont rangés par mention sur une seule barre, et la part qui avait la mention de l'élève est surlignée. C'est le calcul de la zone, rendu visible.
- **Matière par matière** : des points autour de la moyenne du trimestre, au lieu de barres.
- **Carte des voies** : le chemin choisi est surligné au fluo, comme sur un plan papier.
- **Élève de démonstration** : Nour, 1re générale à Évry. Ses notes de seconde suivent les matières de seconde (plus d'enseignement scientifique), et les valeurs ne sont plus arrondies au demi-point. Son histoire : une chute en maths en 1re, alors que les maths comptent pour ECG.
- **Textes** : phrases plus courtes, tutoiement constant. Plus de « · », de flèches ni d'étiquettes en majuscules. Les avertissements ne sont plus répétés dans chaque bloc, ils sont regroupés dans « Comment c'est calculé ? ».
- **Bilan financier** : une dépense s'écrit −, un gain s'écrit +. Corrige « coût estimé gain de… ».
- **Nom de travail** : « tracé », dans la constante `APP_NAME`, à remplacer quand l'équipe aura choisi.
- Clés de stockage renommées (`orient5.`) pour qu'un ancien profil enregistré ne réaffiche pas l'ancienne élève.

## « Comment j'y arrive » devient une semaine de missions (v22)

- **Ma semaine** : cinq missions au plus, tirées des données de l'élève. Préparer le prochain contrôle (trois séances), reprendre le chapitre le plus fragile face à la classe, écrire une phrase pour le projet motivé, lire ce que regarde une cible, parler à son prof principal.
- **Aucune date imposée** : l'élève choisit « Quand ? » pour chaque mission. Les séances de contrôle se cochent une par une, quand il veut.
- **Chaque mission dit ce qu'elle nourrit** dans la grille d'examen Parcoursup : résultats, méthode, savoir-être, motivation.
- **Retours** : une mission faite est surlignée, la barre de la semaine se remplit, une semaine complète est marquée « Semaine bouclée ».
- **Mon année** : une case par semaine, de la rentrée à juin. Pas de série à ne pas casser : une semaine ratée n'efface rien.
- **Ce qui marche pour toi** : l'écart à la classe des contrôles préparés en deux séances ou plus, contre les autres. C'est le chiffre de l'élève, avec la réserve sur le petit nombre.
- **Mon dossier se construit** : bulletins envoyés à Parcoursup, carnet de projet (la matière de la future lettre), découvertes.
- La science est expliquée en mots d'élève dans les missions. Les références restent dans « Pourquoi c'est construit comme ça », pour le jury : Dunlosky et al. 2013, Ryan et Deci 2000, Gollwitzer 1999.
- Le détail par cible (repère, critères, spécialités) est replié dans « Ce que regarde chaque cible ».
- Les tirets sont supprimés partout. Les étapes des passerelles s'affichent en colonne.

## Missions refaites à partir du quotidien d'un lycéen (v23)

Remplace les missions de la v22. Le prof principal chaque mois, la phrase hebdomadaire pour le projet motivé et la lecture hebdomadaire d'une fiche sont retirés.

**Chaque semaine** (fonction `missions()`, mêmes règles pour tous les élèves) :
- les devoirs de la semaine, et ceux en retard, saisis par l'élève (à terme, importés du cahier de textes de l'ENT) ;
- les contrôles annoncés dans les deux semaines : trois séances de préparation, cochées quand l'élève veut ;
- la correction d'un contrôle sous la moyenne de la classe, pendant les deux semaines qui suivent ;
- la plus grosse lacune : un chapitre à au moins un point sous la classe, s'il n'est pas déjà couvert par un contrôle à venir.

**Seulement quand c'est le moment** (tableau `SITUATIONS`, une fenêtre de dates par étape) :
- saisie des moyennes en fin de trimestre ;
- choix des spécialités : celles de première en seconde, celle à arrêter en première ;
- portes ouvertes, de mi-janvier à fin mars ;
- épreuves anticipées en mai et juin ;
- en terminale, le calendrier Parcoursup 2027 : catalogue, vœux avant le 11 mars, projet motivé et confirmation avant le 1er avril, réponses à partir du 1er juin.

**Autres changements :**
- Une semaine sans devoir ni contrôle reste vide. Rien n'est inventé pour remplir.
- La seconde peut saisir des contrôles : ils sont suivis sans le détail par chapitre, puisque seuls les programmes de maths et de français de première et de terminale sont transcrits (choix du prototype).
- « Voir une autre semaine de l'année » montre au jury la même élève en terminale fin janvier ou fin mars, en première en février ou en mai, ou en seconde en mars. Rien n'est enregistré pendant la simulation.
- Les zones s'écrivent en entier : « dans le cœur des admis », « à la marge des admis », « en dessous des admis ».

## Cases à cocher et fluo plus sobre (v24)

- Les boutons « C'est fait » et « Fait » sont remplacés par un rond à cocher, à gauche de chaque mission. Pour un contrôle, le rond coche les trois séances d'un coup, et les ronds des séances restent sous le titre.
- Une mission faite est rayée d'un trait fin qui se trace quand on coche, et son texte passe en gris. Le fluo reste réservé à ce qui doit attirer l'œil.
- La barre de la semaine et « Mon année » passent à l'encre bleue.
- Correction : un contrôle corrigé restait invisible au lieu d'apparaître coché, ce qui faisait baisser le total de la semaine.
