# Mission 12A — transmission (22 octobre 2026)

## Git

Base distante vérifiée : PR #101, `feature/mission11-saas-foundation`, `e64ee1e246985db7c43fa5753a5e77e60f9dc86c`, sur #100 `9a787d48c2756e05485dbe4ad740ae3a2f68e6d1`. #99 n'est pas ancêtre. [PR #102](https://github.com/Caratrac22/novalton-os/pull/102) empilée, `feature/mission12a-local-auth-cadrage`, brouillon, non fusionnée. Commits distants : `9b4066757e9759e5fa724dc583d4b5e9f7e07c01` (API), `0d12a1b25dc71f7924d914574ebfea6387408fd3` (web), `45619ebd2c1a3eafebb99dd53da778dc4c972c20` (correctifs), `5457ac6fef0f75e47f188244256b99b54b4a8cd1` (dépendances), `4a74184839269931098d7420771507ebe751e9e6` (isolation A/B), `2c2d8eff1997e07e0f7f5f373dcf2cd96ba10d99` (JSON et fixture), `598cb44c51e4b40d2c2c74457d620b85da860fd6` (rôle du prompt et concurrence), `d0f63d79bd66b07909a74888a0bc79a277bbdf53` (chargement UI). Les arbres ont été comparés avec les commits locaux. Le commit de documentation suit ; consulter le HEAD de #102 pour sa SHA exacte.

Les anciennes CI #101 [39780802448](https://github.com/Caratrac22/novalton-os/actions/runs/39780802448) et I-044 [39780802446](https://github.com/Caratrac22/novalton-os/actions/runs/39780802446) étaient vertes ; elles ne prouvent pas 12A.

## Registre des tâches

| Tâche | Priorité | Dépendance | État provisoire | Preuve / limite |
|---|---|---|---|---|
| 12A-A identité locale | P0 | audit | PASS | Argon2id, session révocable et grants SQL ; six tests ciblés PostgreSQL PASS sur CI 39824371279. |
| 12A-B bootstrap | P0 | A | PARTIAL | CLI transactionnelle et audit ; récupération administrateur non finalisée. |
| 12A-F conversations | P0 | A, schéma | PASS | Stockage SQL, propriétaire/projet, idempotence et reprise ; six tests ciblés PostgreSQL PASS. |
| 12A-L validation | P0 | continu | PARTIAL | CI 39824371279 : 876 tests API + 6 ciblés, frontend PASS ; CI du dernier lot à confirmer, graphique absent. |
| 12A-C compte web | P1 | A | PARTIAL | Login, logout, changement de mot de passe ; pas de navigateur graphique. |
| 12A-D fournisseurs | P1 | registre | PARTIAL | Local configuré par env ; BYOK seulement par secret serveur préexistant. |
| 12A-E choix | P1 | D | PARTIAL | Modèle local explicite, sans fallback payant ; profils non différenciés. |
| 12A-G questions | P1 | F, D | PARTIAL | Deux tours HTTP déterministes, sortie JSON contrôlée ; vrai modèle non évalué. |
| 12A-H cahier des charges | P1 | F/G | BLOCKED | Versions, décisions et incertitudes non implémentées. |
| 12A-I approbation | P1 | H | BLOCKED | Aucune route d'approbation ni déclenchement implicite. |
| 12A-J chat web | P1 | F | PARTIAL | Historique, reprise et erreurs reliés à l'API ; graphique non vérifié. |
| 12A-K navigateur | P1 | environnement | BLOCKED | GRAPHICAL_ACCEPTANCE_NOT_VERIFIED : aucun navigateur local installé. |

## Identité, bootstrap et autorisation

`LocalCredential` lie un login unique au `HumanOperator` existant. Argon2id : 64 MiB, trois itérations, parallélisme 1, sel 16 octets ; mot de passe de 12 à 128 caractères. `LocalSession` conserve SHA-256 d'un jeton aléatoire de 32 octets, expire après une heure et peut être révoquée. Le login vérifie le mot de passe, le compte actif et un grant `workspace.read`. Cinq échecs par login bloquent quinze minutes ; la réponse d'échec est générique et le login inconnu exécute une vérification factice. Les protections contre la saturation distribuée par IP restent du ressort du déploiement. Changer le mot de passe exige une session, un grant du workspace et l'ancien mot de passe ; toutes les sessions sont révoquées.

`authenticate_session` relie ce jeton au même `OperatorAuthority` que l'identité OIDC RS256. `require_human` verrouille l'utilisateur, le membership, le grant et la session avant la décision. Les routes SaaS ne se fient ni au cookie workspace ni à l'UUID du client. Les API FastAPI exigent le bearer ; les mutations Next vérifient Origin. Les cookies réutilisent les options `Secure`, `HttpOnly` et `SameSite=Lax` de la console. `NOVALTON_WEB_ORIGIN` doit désigner l'origine HTTPS exacte du proxy TLS de confiance ; son absence interdit le login par cookie. L'OIDC externe reste possible.

Après migrations, un opérateur privilégié sur l'hôte lance dans un terminal local :

```bash
uv run --project apps/api python -m novalton_api.modules.local_auth.bootstrap mon_identifiant
```

Le mot de passe est demandé sans écho, jamais en argument. Un verrou PostgreSQL et une transaction créent au plus un premier propriétaire, son tenant/workspace configuré, les grants `workspace.read` et `workspace.write` et une trace d'audit. Aucun `dispatch.*`, inscription publique, endpoint bootstrap ou mot de passe par défaut. La récupération administrative hors bande et l'ajout contrôlé d'autres comptes restent ouverts. Le frontend sélectionne parmi ses scopes configurés ; plusieurs workspaces nécessitent une configuration explicite.

## Modèles et chat

Le `ProviderRegistry` existant reçoit `local_cadrage`. Le serveur accepte `NOVALTON_LOCAL_MODEL_BASE_URL` et `NOVALTON_LOCAL_MODEL_ID` ensemble, uniquement sur loopback, ports 1234/11434, chemin `/v1` compatible LM Studio/Ollama. Réponse 64 KiB au plus, 512 tokens générés, timeout de lecture au plus 45 s, 16 messages de contexte et 4 000 caractères par entrée. Aucun modèle local réel n'était disponible : test avec transport HTTP déterministe. Aucun appel distant ou payant par le chat. Les politiques économique/équilibré/performance/personnalisé sont seulement affichées, sans algorithme de sélection différencié.

OpenAI compatible/OpenRouter demeure configurable par secrets d'environnement serveur. L'exemple `.env.example` garde URL et clé commentées : le fournisseur est réellement non configuré par défaut. Aucune clé BYOK n'est conservée dans PostgreSQL ni retournée au navigateur. La saisie persistante et l'activation individuelle sont désactivées. Le chat ne consomme pas ce fournisseur. Aucune garantie de facture vérifiée ou de plafond de coût facturé ; `BILLING_UNVERIFIED` s'applique.

Migrations `20261022_0041` et `0042` : credentials, sessions, throttle, `cadrage_conversations`, `cadrage_messages`. Le chat est lié au tenant/workspace/projet et au propriétaire, avec FK composite projet/workspace, ordre `sequence`, identifiant de requête unique et réservation atomique de la réponse. Routes sous `/api/v1/tenants/{tenant}/workspaces/{workspace}/projects/{project}/conversations` : liste, création, détail, configuration du modèle, messages paginés, envoi. Chaque accès est autorisé côté SQL ; un résultat tardif revérifie session et grant. Aucun dispatch, agent ou workflow n'est lancé. Sans modèle : message conservé, `MODEL_UNAVAILABLE`. Sortie JSON malformée : `PROVIDER_ERROR`. Les prompts et titres utilisateur restent des données non fiables, jamais des messages de rôle système. Le test à deux tours démontre le chemin technique et la reprise ; il ne valide pas la qualité conversationnelle d'un vrai modèle.

Web : `/login`, compte et mot de passe dans Paramètres, `/projects/[projectId]/chat`, entrée depuis Accueil/Projets, pagination et états d'erreur. Aucun cahier des charges versionné, approbation ni mémoire globale. Les statuts préparatoires de table ne sont pas des décisions humaines enregistrées.

## Validation et sécurité

- Local : `uv run --project apps/api --extra dev ruff check apps/api/src apps/api/tests` et `ruff format --check` PASS ; `python -m compileall` PASS ; `alembic heads` = `20261022_0042` ; `uv run --project apps/api --extra dev pip-audit` : aucune vulnérabilité connue, paquet local non audité sur PyPI. `npm run test:lint` 10/10 et `npm test -w apps/web` 25/25 PASS ; `npm run lint -w apps/web`, `npm run typecheck -w apps/web`, `npm run build -w apps/web` PASS ; `npm audit --audit-level=high` : zéro vulnérabilité ; `git diff --check` PASS. Premier build gêné par cache Turbopack corrompu, puis réussi après déplacement du cache. Aucun PostgreSQL local accessible ; CI sur `novalton_test`.
- Première CI [39822076440](https://github.com/Caratrac22/novalton-os/actions/runs/39822076440) FAILED au format Ruff, avant migrations/tests backend ; frontend PASS. Format corrigé ; CI [39822403227](https://github.com/Caratrac22/novalton-os/actions/runs/39822403227) a ensuite révélé des avis npm critiques sur Next 16.3.8 et un avis haut sur micromatch. L'API y a migré mais deux tests ont échoué : UUID JSON refusé (422) et fixture conservant un RuntimeEvent, entraînant d'autres échecs de bootstrap. Correction du champ UUID, nettoyage des données jetables et ajout d'un scénario A/B multi-tenant et d'un gate ciblé. Next mis à jour en 16.4.2 avec restauration de l'adaptateur fast-glob borné ; `npm ci`, ses 10 tests de contrat, 25 tests web, lint, types, build et `npm audit --audit-level=high` (0 vulnérabilité) PASS local. CI du correctif [39824371279](https://github.com/Caratrac22/novalton-os/actions/runs/39824371279) SUCCESS : frontend (25 tests, lint, types, build, smoke OIDC et audit npm), six tests ciblés comptes/chat sur PostgreSQL et 876 tests API de la suite complète. I-044 [39824371283](https://github.com/Caratrac22/novalton-os/actions/runs/39824371283) : fondation et acceptation installée PASS, suite source encore en cours à la rédaction. Ce run précède le septième test de concurrence et le correctif du rôle du titre ; une CI sur le HEAD final est nécessaire.
- Tests SQL nouveaux ciblent bootstrap concurrent et rollback, login erroné/verrouillé, expiration, révocation, mauvais tenant/workspace, grant retiré, lecteur, UUID étranger, idempotence, sortie modèle malformée et reprise. Six tests PASS au gate ciblé sur `novalton_test` du commit `2c2d8eff1997e07e0f7f5f373dcf2cd96ba10d99` ; suite de non-régression entière PASS (876 tests). Un septième test de réservation concurrente et le contrôle du rôle du titre sont ajoutés après ce run et exigent une CI sur le HEAD final.
- Sécurité du diff : aucun secret ni endpoint de bootstrap, pas de fallback payant, aucune permission `dispatch.*` initiale, aucun effet incertain rejoué et I-044 inchangé. L'environnement cible et le navigateur ne sont pas acceptés pour exposition publique.
- `GRAPHICAL_ACCEPTANCE_NOT_VERIFIED` : aucun binaire Chromium, Firefox ou WebKit ni cache Playwright ici. Le téléchargement Playwright de la mission précédente produisait une archive 0 MiB. Le smoke HTTPS OIDC en CI est HTTP, sans preuve graphique.

## Suite priorisée

1. Corriger tout échec PostgreSQL/CI du HEAD final ; conserver #102 en brouillon jusqu'aux preuves applicables.
2. Récupération administrative et administration contrôlée des comptes/grants, tests hostiles et limites d'abus.
3. Stockage BYOK chiffré et isolé avec clé séparée, activation/autorisation financière explicites.
4. Cahier des charges structuré/versionné, correction des faits puis approbation immuable auditée sans dispatch.
5. Évaluation conversationnelle de vrais modèles locaux et des contradictions sur plusieurs types de projet.
6. Parcours navigateur jetables à 1440/768/390/320 px, deux thèmes, isolation et focus clavier.
