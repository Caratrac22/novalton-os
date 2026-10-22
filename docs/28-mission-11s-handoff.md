# Mission Work 11S — transmission technique

Date : 22 octobre 2026. Dépôt `Caratrac22/novalton-os`, PR [#101](https://github.com/Caratrac22/novalton-os/pull/101), branche `feature/mission11-saas-foundation`, base #100 `feature/mission10-integrated-acceptance` à `9a787d48c2756e05485dbe4ad740ae3a2f68e6d1`. HEAD initial vérifié `aed19a3bb1a1d3b0913a508d9302762372a881a7`, CI initiale [39752537320](https://github.com/Caratrac22/novalton-os/actions/runs/39752537320) SUCCESS. #99 n'est pas ancêtre de #101. PR ouverte, brouillon, non fusionnée ; aucun changement de base, force-push, rebase ou fusion main.

## Registre des tâches et dépendances

| ID | Priorité | Dépendance | État | Critère et preuve | Blocage |
|---|---|---|---|---|---|
| 11S-A | P0 | aucune | PASS | Inventaire des routes FastAPI/Next, sessions, SSE et commandes internes ; matrice ci-dessous. | — |
| 11S-B | P0 | A | PASS | Dépendance commune FastAPI, JWT OIDC, grants SQL, Origin Next ; CI 39779032572 SUCCESS, 870 tests API. | Provisionnement de grants requis avant usage réel. |
| 11S-C | P0 | B | PASS | Test PostgreSQL A/B, deux tenants, workspace sans grant, tâche étrangère, mutation, 106 projets, rôle lecteur et révocation ; CI 39779032572 SUCCESS. | Régression identité fédérée ajoutée au dernier commit, CI finale à contrôler. |
| 11S-D | P1 | navigateur/IdP local | BLOCKED | `GRAPHICAL_ACCEPTANCE_NOT_VERIFIED`. Recherche de moteurs système et cache Playwright ; `npx playwright install chromium` tenté. | Téléchargement répété d'une archive Chrome 0 MiB invalide ; PostgreSQL local absent. |
| 11S-E | P1 | API paginée | PASS | Projets, tâches, runs : `limit/offset`, liens précédent/suivant, bornes et test page 6 sur 106 projets en PostgreSQL ; CI 39779032572 et 25 tests web. | Décalage possible si insertion concurrente entre pages. |
| 11S-F | P1 | accès ciblé | PASS | Lecture ciblée projet/tâche, filtre serveur `task_id` pour runs, aucune substitution d'ID étranger ; choix d'espace revérifié côté API depuis Paramètres ; CI 39779032572. | — |
| 11S-G | P2 | frontend | PARTIAL | Erreurs de connexion/permission, texte français et compteur `≥ 100` ; navigation graphique et audit de contraste non vérifiés. | Navigateur indisponible. |
| 11S-H | P0 | continu | PARTIAL | Ruff, 25 tests web, ESLint, TypeScript, build, audits ; CI 39779032572 et I-044A/B 39779032579 SUCCESS sur le commit de code. | Navigateur absent ; CI du dernier commit à contrôler. |

## Matrice d'autorisation des routes

**Avant** : tous les chemins ci-dessous sauf `dispatch` exigeaient un tenant/workspace dans l'URL et contrôlaient leur appartenance SQL, mais n'exigeaient aucune identité humaine. Un UUID connu suffisait pour lire ou muter dans ce périmètre. `dispatch` vérifiait déjà une session ou une capacité opérateur explicite. **Après** : la dépendance `require_saas_access` s'applique côté FastAPI à tous les routeurs de workspace hors `dispatch` : JWT RS256 OIDC signé, sujet fédéré lié à un humain actif, membership tenant actif, grant `workspace.read` pour GET/HEAD ou `workspace.write` pour POST/PATCH/DELETE, scope exact, expiration et révocation. Un membre `VIEWER` ne peut pas écrire, même s'il reçoit un grant erroné. Refus 401 sans session, 403 sans grant ; les objets étrangers d'un workspace autorisé restent 404. `dispatch` conserve ses permissions spécifiques et sa révocation existantes. Une clé de dispatch n'est pas une session SaaS.

| Route FastAPI `/api/v1/tenants/{tenant}/workspaces/{workspace}/…` | Méthodes | Accès après 11S | Client Next |
|---|---|---|---|
| `projects`, `projects/{id}` | GET / POST / PATCH / DELETE | read / write | `/projects`, `/tasks`, `POST /api/projects` |
| `projects/{id}/tasks`, `…/tasks/{id}` | GET / POST / PATCH / DELETE | read / write | `/tasks`, `POST /api/projects/{id}/tasks` |
| `tasks/{id}/workflow-plans`, `…/versions` | GET / POST | read / write | workflow existant |
| `workflow-plans/{id}`, `…/runs` | GET / POST | read / write | workflow existant |
| `projects/{id}/tasks/{id}/development-workflows` | POST | write | `POST /api/workflows/development` |
| `workflow-runs`, `workflow-runs/{id}`, `…/operator-view`, `…/cancel`, `…/advance`, `…/steps/{id}/challenge-resolution` | GET / POST | read / write | Centre, tâche et API workflow |
| `workflow-runs/{id}/git-commit-actions`, `git-commit-actions/{id}/github-publications` | GET / POST | read / write | API commit/publication |
| `approvals`, `approvals/{id}`, `…/approve`, `…/reject` | GET / POST | read / write | API approbations |
| `events/stream` | GET SSE | read à l'ouverture et avant chaque lot/poll | `/api/activity/stream` avec session transmise |
| `agents`, `agent-runs`, `memories`, `model-runs`, `models`, `models/route`, `policy`, `developer-manager`, `developer-worker`, `qa-worker` | GET / POST selon route | read / write | principalement API interne et scripts ; HTTP direct nécessite session humaine |
| `dispatch/activation`, `dispatch/requests`, détails/attempts/workflow/cost/cancel/resolve` | GET / POST | permissions opérateur propres (`activation.configure`, `dispatch.*`) | `/operator` et API opérateur |
| `/api/v1/health` et documentation OpenAPI | GET | public, sans donnée tenant | `/environments` affiche la santé réelle |

Les traitements et workers existants invoquent des services Python internes, non les routes HTTP historiques ; aucune identité de service HTTP implicite n'est ajoutée. Pour conserver les anciens tests HTTP, **le seul contournement** `NOVALTON_TEST_LEGACY_API_AUTH_BYPASS=true` est injecté par `apps/api/tests/conftest.py` après vérification stricte de `NOVALTON_ENV=test` et de l'identité de `novalton_test`. En dehors du profil `test`, cette valeur refuse la requête. Les nouveaux tests de sécurité la désactivent explicitement et passent par les tables PostgreSQL et la signature RS256. Elle ne doit jamais être configurée pour un déploiement. Aucune permission `workspace.*` n'est attribuée automatiquement par migration : l'administrateur du déploiement doit provisionner explicitement les grants des utilisateurs autorisés, dans le bon tenant/workspace, via sa procédure de confiance avant de rendre l'interface opérationnelle.

### Frontière Next.js et CSRF

`scopedSessionFetch` lit le cookie HTTPOnly `__Host-novalton-operator-session` côté serveur, refuse un jeton absent/malformé et un cookie de workspace hors de la liste configurée, puis transmet le Bearer uniquement à l'API configurée. FastAPI valide toujours signature, scope et droits SQL. Les Server Components Accueil, Projets, Tâches et Centre chargent les données par ce chemin. Les routes mutantes Next.js Projets/Tâches/Workflows/Approvals/Git vérifient l'Origin HTTPS exacte avant mutation ; le backend exige indépendamment un Bearer et n'accepte aucun cookie de navigateur directement. Les routes opérateur préexistantes conservent leur Origin et leurs contrôles de session. Le flux SSE ne transmet pas d'événements privés sans autorisation ; la révocation d'un grant termine le flux avant le lot suivant. Le shell public et la santé système restent visibles sans session, sans données de workspace.

## Scénarios d'isolation et validation

| Scénario | Preuve attendue dans `test_durable_dispatch_sessions.py` | État |
|---|---|---|
| A lit ses 106 projets à travers les pages 1 et 6 | `limit=100` et `offset=100`, ensembles disjoints | PASS, CI 39779032572 |
| B lit son projet et sa tâche | Bearer B et tenant/workspace B | PASS |
| A connaît le projet/tâche de B | 403 sur scope B, 404 sur ID B sous scope A | PASS |
| A mute sous B ou forge `X-Workspace-ID` | 403 | PASS |
| Pas de session / expirée | 401, y compris SSE | PASS |
| Grant retiré entre lecture et PATCH | 403 sur PATCH et GET suivant | PASS |
| SSE après révocation en cours de flux | autorisation retestée avant le poll suivant, plus de frame | PASS |
| Identité fédérée B révoquée après lecture | 401 sur nouvelle lecture avec le même JWT | Test ajouté au dernier commit ; CI finale à contrôler |
| Opérateur OIDC existant et protections I-044 | suites historiques et gate I-044A/B | PASS, 39779032579 |

Le test utilise deux humains, deux tenants, des projets/tâches persistés et un troisième workspace sans grant. Les anciennes suites I-044 restent inchangées. Une session révoquée par la table d'identité est déjà testée dans les suites de sessions opérateur ; le nouveau test cible en plus les grants SaaS et une identité fédérée révoquée. Le filtre `task_id` s'applique dans la requête SQL des runs avec le scope tenant/workspace et ordre décroissant, permettant de lire la dernière exécution même après la première page globale. Les pages `limit/offset` ont un ordre stable `created_at,id` ; l'insertion concurrente entre deux requêtes peut déplacer une ligne, ce qui demanderait une pagination par curseur pour un inventaire transactionnel strict. Aucun total n'est inventé.

## Interface et limites

- Accueil : shell public, projet réel seulement avec session autorisée ; état indisponible et lien de connexion sinon ; santé API publique distincte du nombre de projets.
- Projets : liste paginée de 20, création autorisée, accès par ID et erreurs explicites. Tâches : projet sélectionné, liste paginée de 20, tâche par ID contrôlé dans son projet, lien de retour et formulaire. Une URL invalide n'ouvre aucun autre projet.
- Centre de contrôle : page de 20 runs, statuts calculés **sur la page chargée**, précédent/suivant, flux d'activité et lien opérateur. Aucun total global ni progression inventés.
- Environnements : santé API/PostgreSQL seulement. Paramètres : préférence locale d'apparence, choix parmi les espaces vérifiés par le backend et rubriques non configurées explicites. Navigation en cinq rubriques conservée.
- Le workflow d'une tâche est récupéré par filtre `task_id`, dernière exécution persistée ; aucun nouveau moteur, modèle adaptatif ou chat n'est ajouté.
- Les routes de connexion OIDC et de sortie opèrent toujours via HTTPS et le proxy de confiance. La déconnexion efface le cookie ; une copie déjà exfiltrée du JWT reste valable jusqu'à expiration ou révocation serveur : le déploiement doit protéger le cookie et prévoir une révocation effective.

## Tests et sécurité

Locaux : `npm run typecheck -w apps/web`, `npm run lint -w apps/web`, `npm test -w apps/web` : 25/25 ; `npm run build -w apps/web` : PASS après déplacement d'un ancien cache `.next` corrompu ; `uv run --project apps/api --extra dev ruff check apps/api/src apps/api/tests …` et `ruff format --check` sur ces chemins : PASS ; `npm audit --omit=dev --audit-level=high` : zéro vulnérabilité ; `pip-audit` sur le venv local : aucune vulnérabilité connue, paquet local non audité sur PyPI ; `git diff --check` : PASS. L'essai `pip-audit -r apps/api/uv.lock` a échoué car `uv.lock` n'est pas un fichier requirements, puis l'audit correct a réussi. La tentative initiale de build Next a échoué en lisant un cache Turbopack corrompu ; un build à cache neuf a réussi. Aucun test destructif sur base réelle. PostgreSQL local et Playwright graphique : NOT_VERIFIED ici.

La CI [39779032572](https://github.com/Caratrac22/novalton-os/actions/runs/39779032572) du commit de code `e617e9c566303f7859db0af0802b2f30758201d8` est SUCCESS : migrations PostgreSQL jetables, Ruff, 870 tests API sur 55 fichiers, 25 tests web, lint/type/build Next, smoke HTTPS OIDC local et audits de dépendances. Le gate [I-044A/B 39779032579](https://github.com/Caratrac22/novalton-os/actions/runs/39779032579) est SUCCESS sur ce même SHA. La CI du commit final contenant le test additionnel et le présent rapport reste à vérifier sur son **HEAD exact** ; les liens de validation finale seront consignés dans la PR. Aucun secret, pouvoir shell d'agent, contournement I-044, appel payant ou replay d'effet incertain n'a été ajouté.

## Acceptation graphique

`GRAPHICAL_ACCEPTANCE_NOT_VERIFIED`. Ni Chromium, ni Firefox, ni cache Playwright système n'étaient disponibles. `npx --yes playwright --version` a fonctionné (1.64.1), mais `npx --yes playwright install chromium` a échoué après plusieurs réponses de 0 MiB depuis le CDN et une archive ZIP invalide. Sans moteur et sans PostgreSQL local, il serait trompeur de qualifier un parcours HTTP de test visuel. À reprendre dans un environnement jetable avec navigateur, IdP OIDC HTTPS local, API et PostgreSQL : 1440/768/390/320 px, clair/sombre, clavier, création, SSE, décisions, refus et révocation.

## Transmission priorisée

1. Vérifier les runs du HEAD final et corriger tout échec de migration ou d'isolation avant de qualifier P0 de PASS ; la PR reste en brouillon tant que l'acceptation graphique manque.
2. Provisionner explicitement `workspace.read`/`workspace.write` pour les humains autorisés, selon le tenant et le workspace, puis tester l'accès réel et le retrait de grant sur un déploiement jetable. Aucun grant n'est créé implicitement pour les anciens opérateurs.
3. Refaire l'acceptation navigateur complète ; mesurer contrastes, focus, navigation et débordements à 320 px. Vérifier une connexion, déconnexion et expiration avec IdP local.
4. Étudier pagination par curseur si l'inventaire est fortement modifié pendant la navigation et ajouter une UX de choix de workspace plus riche lorsque plusieurs scopes sont configurés.
5. Mission 12 uniquement sur nouveau mandat : assistant de cadrage, mémoire projet et approbation humaine avant lancement. Le présent travail ne prétend pas les livrer.

### Journal de diagnostic CI et révision de sécurité

Le premier run du lot [39777268413](https://github.com/Caratrac22/novalton-os/actions/runs/39777268413) a échoué à `alembic upgrade head` avant Pytest : la nouvelle migration partait de `0038` alors que `20261021_0039_provider_cost_observation.py` existait. Correction publiée par le commit `e81ef435b9a8706e0ca46790d48990819a9df390` : migration `20261022_0040` descendante de `20261021_0039` ; `alembic heads` donne une seule tête. Le frontend du run initial a réussi, y compris le smoke OIDC, mais ce run n'est pas une preuve backend. Un examen ultérieur a identifié que la dépendance d'autorisation initiale du SSE pouvait conserver un verrou partagé pendant toute la réponse ; elle effectue maintenant un `rollback` après le contrôle d'entrée, puis revalide les droits avant chaque poll. Un test PostgreSQL vérifie l'absence de transaction persistante après l'entrée SSE. Le choix de workspace dans Paramètres revalide `workspace.read` auprès de FastAPI avant d'écrire le cookie HTTPOnly, et refuse un scope absent de la configuration. Ces correctifs postérieurs exigent une nouvelle CI sur leur HEAD exact.

Le run correctif [39777642801](https://github.com/Caratrac22/novalton-os/actions/runs/39777642801) a migré PostgreSQL et passé le frontend, mais cinq assertions backend ont échoué : trois attendaient encore littéralement `20261021_0039`, une fixture B n'avait pas forcé le `flush` de son humain avant son identité fédérée, et un faux `Request` SSE n'avait pas de champ `headers`. Le gate [39777642704](https://github.com/Caratrac22/novalton-os/actions/runs/39777642704) a aussi relevé le test de tête Alembic et l'ancien parcours I-044 installé sans credential. Le commit `e617e9c566303f7859db0af0802b2f30758201d8` corrige ces causes : assertions sur la tête actuelle, ordre d'insertion SQL explicite, fixture SSE complète, et exemption de fixture dans l'acceptation I-044 installée **après** vérification du profil/test DB. Les tests d'isolation SaaS continuent d'exiger un JWT et les grants réels. Runs de ce commit : [CI 39779032572](https://github.com/Caratrac22/novalton-os/actions/runs/39779032572) SUCCESS, [I-044A/B 39779032579](https://github.com/Caratrac22/novalton-os/actions/runs/39779032579) SUCCESS. Aucun run en échec n'est présenté comme preuve de succès.
