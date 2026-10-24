# Mission 12B — transmission (23 octobre 2026)

## Référence Git et état de livraison

PR [#103](https://github.com/Caratrac22/novalton-os/pull/103), branche `feature/mission12b-intelligent-cadrage-byok`, empilée sur #102 au SHA `17cd50e048b1203e9e9c5b9f4777d196aa0b267a`. #102 est sur #101 `e64ee1e246985db7c43fa5753a5e77e60f9dc86c`. #99 exclue. PR ouverte, brouillon, non fusionnée ; consulter la tête GitHub et la description de PR pour la SHA et les runs du dernier commit, car le commit portant ce rapport ne peut contenir sa propre SHA. Aucun merge ni force-push.

Le premier arbre publié était `189baf22d7fe5b3929da134763d1595032891b29` et correspondait exactement à l'arbre Git local. Le push HTTPS direct n'avait pas d'identifiants ; l'API GitHub a créé les blobs, l'arbre, le commit et la branche depuis la base vérifiée. Les commits locaux organisent la récupération, le cahier, le coffre, les tests et le frontend ; la publication GitHub compacte le premier lot dans un commit d'arbre identique. Les correctifs de CI et ce rapport suivent sans réécriture de la base.

## Registre des tâches

| ID | Priorité / dépendance | État | Preuve et limite |
|---|---|---|---|
| 12B-A compte | P0 / aucune | PARTIAL | Argon2id, cookie et Origin, grants SQL, expiration et révocation préservés ; limite de saturation distribuée par IP et acceptation cible ouvertes. |
| 12B-B récupération | P1 / A | PARTIAL | Commande locale TTY transactionnelle, session révoquée, audit, grant intact ; CI du correctif final à consulter. |
| 12B-C coffre | P0 / audit | PARTIAL | AES-256-GCM et AAD propriétaire/tenant/workspace/fournisseur, keyring hôte, rotation transactionnelle ; tests et cible de déploiement à confirmer. |
| 12B-D BYOK | P1 / C | PARTIAL | Paramètres et API ajout/remplacement/activation/désactivation/suppression, réauthentification locale ; aucun appel distant n'emploie la clé. |
| 12B-E modèle/finance | P1 / D | PARTIAL | Aucun fallback ni appel payant ; profils non différenciés, sélection distante et budget réel non autorisés. |
| 12B-F cahier | P0 / conversation | PARTIAL | Versions SQL immuables, contrôle optimiste et isolation ; validation CI finale requise. |
| 12B-G questions | P1 / F + modèle | PARTIAL | Propositions validées et conflits de sujet, contexte du cahier ; qualité de vrai modèle non vérifiée. |
| 12B-H éditeur | P1 / F | PARTIAL | Résumé, corrections, confirmations, historique récent et retour au chat ; acceptation visuelle manquante. |
| 12B-I plan | P1 / F | PARTIAL | Brouillon déterministe traçable depuis une version du cahier, aucune ressource fictive ; planification IA riche non livrée. |
| 12B-J approbation | P0 / I | PARTIAL | Transitions SQL/audit humain, refus obsolète/double décision, supersession ; CI finale requise, sans dispatch. |
| 12B-K UX | P1 / API | PARTIAL | Chat et cahier côte à côte/contextuels ; responsive réel non accepté graphiquement. |
| 12B-L navigateur | P1 / environnement | BLOCKED | `GRAPHICAL_ACCEPTANCE_NOT_VERIFIED` ; aucun binaire local Chromium/Firefox et CI existante limitée au smoke HTTP. |
| 12B-M modèle local | P2 / disponibilité | BLOCKED | `REAL_MODEL_QUALITY_NOT_VERIFIED` ; aucune réponse sur loopback 1234 et aucun modèle téléchargé. |
| 12B-N transversal | P0 / continu | PARTIAL | Ruff, lint/types, 25 tests web et build local ; CI complète et I-044 sur HEAD final à consulter. |

## Compte et sécurité — avant / après

| Frontière | Base #102 | Travail 12B |
|---|---|---|
| Mot de passe/session | Argon2id 64 MiB/3 passes, token opaque SHA-256, une heure, révocation SQL | Récupération hôte et révocation de toutes les sessions du propriétaire ; réauthentification récente avant modification BYOK, compteur d'échecs partagé avec le login. |
| Bootstrap | CLI unique transactionnelle, grants `workspace.read`/`workspace.write` seulement | Aucune inscription ni récupération HTTP. Commande de récupération conservant tous les grants. |
| Tenant/workspace | `require_saas_access`, membership/grants, OIDC RS256 | Routes BYOK/cahier/plan utilisent la même dépendance et l'identité de propriétaire des conversations ; UUID et cookie ne confèrent aucun droit. |
| Mutation web | Cookie `Secure`, `HttpOnly`, `SameSite=Lax` et Origin HTTPS exact | Routes Next BYOK/cahier/plan rejettent les Origins invalides ; FastAPI exige bearer + `workspace.write`. |
| Secrets/logs | BYOK par environnement seulement | Valeur BYOK jamais retournée ni auditée ; AAD détecte modification de portée, réponse générique en cas de coffre indisponible. |
| Gouvernance | I-044 et dispatch gouverné | Aucune route du nouveau plan n'appelle l'orchestrateur, le dispatch ou un fournisseur payant. |

Récupération depuis un terminal privilégié sur l'hôte, après vérification de l'instance et des sauvegardes :

```bash
uv run --project apps/api python -m novalton_api.modules.local_auth.recover mon_identifiant
```

Le secret est saisi par `getpass`, jamais dans les arguments. La commande exige le compte propriétaire actif du tenant configuré, prend le verrou transactionnel du bootstrap, remplace le hash, révoque les sessions et ajoute `account.password.recover` avec la catégorie d'audit `service` et l'indication `privileged_host_cli`. En cas d'erreur, rollback. L'accès à l'hôte et aux secrets de base constitue ici l'autorité ; protéger cet accès est une exigence de déploiement.

## Coffre BYOK

`personal_provider_keys` conserve seulement l'identifiant de clé maîtresse, nonce aléatoire de 96 bits, ciphertext/tag AES-256-GCM, propriétaire, tenant, workspace, fournisseur et état. L'AAD encode toutes ces coordonnées : une substitution de métadonnées rend le déchiffrement impossible. Le serveur n'accepte que `openrouter` et `openai_compatible` dans cette API ; aucune URL saisie dans la page ne devient destination réseau. Les clés sont chiffrées côté API et ne transitent qu'une fois dans la mutation TLS du navigateur ; les réponses et listes omettent même les derniers caractères. Un compte OIDC seul ne peut changer ces secrets personnels : compte local récent (dix minutes) et mot de passe actuel requis. Les échecs de réauthentification sont limités par le compteur du login.

La clé maîtresse reste hors PostgreSQL : `NOVALTON_BYOK_KEYRING` est un JSON privé `{"v1":"<base64 de 32 octets aléatoires>"}` et `NOVALTON_BYOK_ACTIVE_KEY_ID=v1`. Sans cette configuration, le formulaire est désactivé et les mutations échouent ; aucune valeur d'exemple n'est une clé réelle. Sauvegarder la keyring séparément et sous autorité restreinte, faute de quoi un dump SQL chiffré ne peut être restauré. Pour la rotation, ajouter `v2` à la keyring, définir `v2` actif, puis lancer dans un terminal privilégié :

```bash
uv run --project apps/api python -m novalton_api.modules.provider_keys.rotate
```

L'opération verrouille les enregistrements et les rechiffre dans une transaction. Ne retirer `v1` qu'après vérification et politique de restauration des anciennes sauvegardes. Une mauvaise clé interrompt la rotation et provoque un rollback. La suppression BYOK efface l'enregistrement ; l'ancienne valeur peut subsister dans des sauvegardes de base chiffrées avec une ancienne keyring, ce qui relève de la politique de rétention. Le bouton « activer » n'est pas un consentement financier : le chat ne lit pas ces clés et les fournisseurs distants restent désactivés pour lui. `BILLING_UNVERIFIED`.

## Cadrage, versions et approbation

Migrations `20261023_0043`, `0044`, `0045` ajoutent `cadrage_specifications`, `personal_provider_keys`, `cadrage_plans`. Le cahier contient un résumé et des éléments extensibles `{topic, value, provenance, state}`. Les versions sont append-only avec version monotone, auteur/source et date. Une mutation exige `expected_version`; un 409 empêche d'écraser une correction plus récente. Une proposition IA arrive avec `MODEL_PROPOSAL`/`PROPOSED`, une divergence de sujet devient `CONFLICT`, et seul l'utilisateur peut confirmer. Le serveur refuse une provenance IA forgée dans une édition humaine. Une réponse tardive ne peut enregistrer sa proposition si le cahier a changé ; la réservation du modèle est invalidée par l'édition humaine.

Le brouillon de plan reprend uniquement les éléments confirmés d'une version précise. Il est explicitement déterministe et doit être revu : il ne prétend ni sélectionner de vrais agents ni autoriser une dépense. `DRAFT → READY_FOR_REVIEW → APPROVED/REJECTED/NEEDS_CHANGES`, avec audit et identité de décision. Une nouvelle version du cahier marque les anciens plans `SUPERSEDED`, y compris un plan auparavant approuvé. Les doubles approbations et versions obsolètes sont refusées. La décision ne lance aucun agent ; le lancement gouverné sera une mission distincte.

L'éditeur est dans le chat du projet. Il affiche éléments proposés/confirmés, permet une correction et une nouvelle version, puis présente le plan et ses décisions. L'historique visible est borné aux 20 versions les plus récentes ; l'API est paginée. Des catégories métier plus riches, une détection sémantique des contradictions et les profils de modèles restent ouverts.

## Tests et diagnostics

- Local : `uv run --project apps/api --extra dev ruff check apps/api/src apps/api/tests infra/migrations/versions/20261023_004*.py` PASS ; `ruff format --check` après format ; `alembic -c apps/api/alembic.ini heads` retourne une seule tête `20261023_0045`. Import FastAPI et contrat AES-GCM direct PASS.
- Frontend local : `npm run typecheck -w apps/web`, `npm run lint -w apps/web`, `npm test -w apps/web` : 25/25 PASS ; `npm run build -w apps/web` PASS après déplacement d'un cache Turbopack local corrompu. `npm audit --audit-level=high` : 0 vulnérabilité après mise à jour du lockfile `zod`.
- `pytest` local n'a pas pu être lancé : fixture obligatoire de `novalton_test`, aucun PostgreSQL local accessible. La migration et les tests PostgreSQL sont exécutés dans GitHub Actions sur une base jetable.
- [Première CI #183](https://github.com/Caratrac22/novalton-os/actions/runs/40026632840) FAILED : frontend build/smoke PASS mais avis npm `zod` haut ; backend migrations PASS, gate ciblé 8 PASS/2 FAILED. Causes : valeur `actor_type` hors enum dans l'audit de récupération et chargement implicite SQL `MissingGreenlet` après activation de clé. Correctifs : catégorie `service` documentée, réponse sérialisée avant commit, puis régulation des tentatives de réauthentification et durcissement du contexte du modèle. Ces échecs ne sont pas cachés. Le résultat du HEAD final est à lire sur la PR et dans le rapport de fin de mission.
- I-044A/B du premier lot : [run #112](https://github.com/Caratrac22/novalton-os/actions/runs/40026632743), encore en cours à la rédaction ; le gate du HEAD final fait foi.

## Acceptation et suite

Pas de navigateur graphique local ni modèle réel local ; aucun appel externe payant. Le navigateur de CI n'est pas installé/configuré dans les workflows existants ; le smoke OIDC HTTPS est HTTP. Les copies d'écran, contrastes, focus et largeurs 1440/768/390/320 restent `NOT_VERIFIED`. Aucun secret de test réel n'a été créé ni publié.

Priorités suivantes : (1) clore toute CI du HEAD final et revue de sécurité du diff ; (2) tester le parcours navigateur jetable complet avec Chromium sur runner autorisé ; (3) évaluer un vrai modèle local sur cinq domaines, contradictions et corrections tardives ; (4) enrichir les politiques de modèle et l'autorisation financière sans dépenser ; (5) préparer séparément le lancement gouverné d'un plan approuvé avec I-044, permissions et budgets, sans le déclencher dans 12B.

## Reprise du 24 octobre 2026 — acceptation Chromium et défauts d'interface

Ce complément remplace les seules mentions ci-dessus selon lesquelles aucun navigateur n'était disponible. Un workflow PR `mission12b-browser.yml` utilise Chrome/ChromeDriver du runner Ubuntu GitHub et PostgreSQL `novalton_test` jetable. Il démarre FastAPI, Next et un proxy HTTPS local, crée un propriétaire synthétique par la procédure privilégiée, puis pilote un vrai navigateur par WebDriver. Le mot de passe aléatoire est masqué dans Actions ; aucune clé fournisseur ni appel payant. La PR reste en brouillon.

Le [premier run Chromium](https://github.com/Caratrac22/novalton-os/actions/runs/40034275571) a échoué sur un corps POST WebDriver absent, corrigé. Le [deuxième](https://github.com/Caratrac22/novalton-os/actions/runs/40034518411) a révélé un débordement réel de 31 px à 768 px, corrigé en empilant le chat à partir de 900 px. Le [troisième](https://github.com/Caratrac22/novalton-os/actions/runs/40076851572), au HEAD `db112cfaa319c0cd6b2df35036856fb6e79adac2`, a réussi : refus sans session, connexion locale, création d'un projet et d'une tâche, conversation persistée, édition du cahier, brouillon de plan, soumission et approbation humaine, rechargement, vérification du débordement à 1440/768/390/320 px dans les thèmes sombre et clair. Huit captures ont été déposées dans [l'artefact Actions](https://github.com/Caratrac22/novalton-os/actions/runs/40076851572/artifacts/12552599813). Une capture mobile inspectée a révélé que la navigation verticale occupait presque tout l'écran malgré l'absence de débordement horizontal. Le correctif définit une rangée horizontale bornée, avec une assertion de hauteur ; les captures attendent désormais le chargement du message et du plan. La déconnexion et le refus de session après celle-ci ont aussi été ajoutés au parcours final. Le résultat CI de ce dernier correctif est à consulter sur la PR, car il suit le commit de cette note.

La preuve graphique est **PARTIAL** jusqu'à la réussite de ce dernier run et reste limitée aux parcours cités. Elle ne couvre pas encore la révocation par un autre opérateur au milieu d'une page, les droits cross-workspace en navigateur, un audit complet de contraste et lecteur d'écran, ni l'évaluation d'un modèle réel. Les tests PostgreSQL d'isolation et de révocation du backend constituent des preuves distinctes. `REAL_MODEL_QUALITY_NOT_VERIFIED` et `BILLING_UNVERIFIED` restent inchangés. Aucun plan approuvé n'a déclenché un agent.
