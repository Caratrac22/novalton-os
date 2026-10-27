# Mission 12F — fiabilité du lancement gouverné

Base vérifiée : PR #106, `65bb50fc4c2eeda09c01f0fb64b5002b9f430fbb` ; CI
`40478544136`, Chromium `40478544110`, I-044A/B `40478544128` SUCCESS sur
ce SHA. Branche empilée `feature/mission12f-governed-execution-reliability`.
La PR, les commits et les gates du HEAD 12F seront consignés après validation.

## Registre

| Tâche | État | Preuve / limite |
|---|---|---|
| Effets incertains du run de cadrage | IN_PROGRESS | Crash après réservation, timeout, lease expirée et réponse tardive avec révocation/annulation/lease perdue ; appels uniques et aucun QA indu. Gate PostgreSQL final en cours. |
| Concurrence et révocations | IN_PROGRESS | Deux POST identiques, clé divergente, audit unique, grants, activation et budget modifiés après Manager ; gate final en cours. |
| Chromium hostile | IN_PROGRESS | Vrais UUID du plan et de sa compilation, routes directes, second tenant et session révoquée, 1440/768/390/320 px en deux thèmes ; gate final en cours. |
| I-044 intermittent | IN_PROGRESS | Sur #106, premier job installé échoué `KeyError: state` à l'annulation avec refus AppArmor observés, reprise même SHA réussie. Cause à isoler sans affaiblir la politique. |
| Génération facturable | PARTIAL | Voir inventaire ci-dessous ; fournisseurs payants absents du registre runtime, aucune génération BYOK activée. La réservation existe mais n'est reliée à aucun chemin de génération. |
| Modèle local réel | BLOCKED | Aucun modèle joignable démontré dans ce runtime ; corpus de 11 scénarios à réutiliser si accessible. `REAL_MODEL_QUALITY_NOT_VERIFIED`. |
| BYOK/restauration PostgreSQL | IN_PROGRESS | Nouveau test `pg_dump`/`pg_restore` de base jetable distincte, keyring séparée, rotation et ancienne clé absente ; gate final en cours. |
| UX et preuves | IN_PROGRESS | Le suivi masque ses anciennes preuves quand l'accès est perdu ; lint/types/build et Chromium en cours. |

## Inventaire des appels de génération

`cadrage/generation.py:generate_reply` appelle exclusivement `local_cadrage` ; le
paramètre de configuration n'accepte que HTTP loopback `/v1` aux ports 1234 ou
11434. Dans `agents/execution.py`, les appels initiaux, de continuation, de
récupération et de validation passent par le registre de fournisseurs. Le
registre de l'application (`main.py:lifespan`) ne contient que le modèle local
configuré ; la clé BYOK n'est jamais déchiffrée pour ces appels. Le catalogue
OpenRouter est un accès de métadonnées séparé et ne doit pas être considéré
comme une autorisation de génération. `financial/service.py:reserve` verrouille
les quotas et la portée, mais aucun chemin de génération ne l'invoque encore.
Tout raccordement payant exige une réservation commitée avant I/O, des
autorisations humaines de génération et de finance distinctes, et un traitement
irréversible des réponses incertaines. Les chemins payants restent fermés.

## Résultat du modèle réel

Les ports locaux 1234 et 11434 ne répondent pas dans le runtime Work. Les onze
scénarios de `apps/api/scripts/evaluate_cadrage.py` ne constituent donc pas une
preuve de qualité sur modèle réel : `REAL_MODEL_QUALITY_NOT_VERIFIED`.

## États et limites

`WORKFLOW_CREATED`, `WORKFLOW_EXECUTED` et `QA_PASSED` sont démontrés en 12E
avec un fournisseur déterministe local. `PRODUCTION_ACCEPTED` reste exclu.
Aucun fournisseur payant, Proxmox ou environnement de production n'est autorisé.
Les effets externes incertains ne doivent jamais être rejoués.
