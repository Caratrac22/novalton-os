# Mission 12F — fiabilité du lancement gouverné

Base vérifiée : PR #106, `65bb50fc4c2eeda09c01f0fb64b5002b9f430fbb` ; CI
`40478544136`, Chromium `40478544110`, I-044A/B `40478544128` SUCCESS sur
ce SHA. PR brouillon #107, branche
`feature/mission12f-governed-execution-reliability`, empilée sur #106. HEAD de
code vérifié : `e08a3a589638cbfc8fe85757dce35673dbc54569` ; CI
`40495044664`, Chromium `40495044642`, I-044A/B `40495044660` SUCCESS sur
ce SHA. Un commit documentaire ultérieur requiert ses propres trois gates.

Commits de la PR : `521881a` (effets incertains et concurrence), `a67e3ec`
(Chromium et suivi), `adde603` (restauration BYOK), `140f786` (activation),
`032c4e5` (plan obsolète), `e08a3a5` (corrections des deux tests). Aucun merge,
force-push, déploiement ou appel payant.

## Registre

| Tâche | État | Preuve / limite |
|---|---|---|
| Effets incertains du run de cadrage | PASS | Crash après réservation, timeout, lease expirée et réponse tardive avec révocation/annulation/lease perdue : un seul appel, une tentative, aucun QA ni rejeu ; 28 tests ciblés PASS sur PostgreSQL dans CI `40495044664`. |
| Concurrence et révocations | PASS | Deux POST identiques : un dispatch et un audit ; clé divergente refusée ; grants, activation et budget modifiés après Manager : aucun appel supplémentaire. Réactivation avec nouvelle génération refusée. Même CI. |
| Chromium hostile | PASS | Vrais UUID du plan et de la compilation, plan supersédé, API directe, second tenant, grant et session révoqués, quatre largeurs et deux thèmes ; `40495044642` SUCCESS, huit captures. |
| I-044 intermittent | PARTIAL | Le gate installé `40495044660` est vert sans retry, avec seccomp/AppArmor, annulation et vérification gouvernée. Sur #106, un premier essai avait échoué `KeyError: state` après annulation et des refus AppArmor étaient observés ; la reprise du même SHA avait réussi. Cause non attribuée avec certitude, incident à instrumenter si récurrence. |
| Génération facturable | PARTIAL | Voir inventaire ci-dessous ; fournisseurs payants absents du registre runtime, aucune génération BYOK activée. La réservation existe mais n'est reliée à aucun chemin de génération. |
| Modèle local réel | BLOCKED | Aucun modèle joignable démontré dans ce runtime ; corpus de 11 scénarios à réutiliser si accessible. `REAL_MODEL_QUALITY_NOT_VERIFIED`. |
| BYOK/restauration PostgreSQL | PASS | `pg_dump`/`pg_restore` dans une autre base jetable, chiffrement sous ancienne keyring, échec avec la nouvelle seule, rotation et ancienne clé absente ; 28 tests ciblés et suite complète PASS. |
| UX et preuves | PASS | Le suivi efface les preuves affichées si l'accès est retiré ; frontend lint/types/build et Chromium SUCCESS, sans succès simulé dans l'interface. |

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

## Exécution et validation

Le test intégré part d'un plan approuvé, crée une autorisation humaine distincte,
un workflow atomique, un dispatch idempotent, puis avance Manager → Developer →
QA avec trois réponses déterministes du fournisseur local simulé. Le run finit
`COMPLETED`, le dispatch `DONE`, trois `ModelRun` `SUCCEEDED`, les trois étapes
`COMPLETED` et le verdict QA `PASS`. C'est `WORKFLOW_CREATED`,
`WORKFLOW_EXECUTED` et `QA_PASSED` **dans l'environnement jetable seulement**.
`PRODUCTION_ACCEPTED` n'est pas atteint et la production n'est pas activée.

La CI backend migre `novalton_test`, exécute 28 tests ciblés puis 902 tests API
dans la suite complète par fichiers, avec Ruff et audit de dépendances. La CI
web exécute lint, types, tests et build. Chromium démarre Next, FastAPI et
PostgreSQL jetables avec deux identités. I-044A/B exécute ses tests source,
fondation reproductible et acceptation installée. Ces résultats concernent le
HEAD de code ci-dessus ; vérifier les mêmes gates après tout nouveau commit.

Priorités suivantes : instrumenter la réponse inattendue du client I-044 si
l'incident revient ; brancher une réservation financière commitée et une
autorisation de génération pour chaque appel facturable avant tout fournisseur
payant ; évaluer les onze scénarios sur un véritable modèle local disponible.

## États et limites

`WORKFLOW_CREATED`, `WORKFLOW_EXECUTED` et `QA_PASSED` sont démontrés en 12E
avec un fournisseur déterministe local. `PRODUCTION_ACCEPTED` reste exclu.
Aucun fournisseur payant, Proxmox ou environnement de production n'est autorisé.
Les effets externes incertains ne doivent jamais être rejoués.
