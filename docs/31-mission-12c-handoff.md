# Mission 12C — jonction contrôlée, première tranche (24 octobre 2026)

## Registre priorisé

| ID | Priorité | Dépendances | État | Preuve / blocage | Prochaine action |
|---|---|---|---|---|---|
| 12C-F audit | P0 | Aucune | PASS | Matrice ci-dessous, code 12B lu | Vérifier à chaque évolution du moteur |
| 12C-G compilation | P0 | F | PARTIAL | Proposition SQL, contrôle de portée, tests de refus | CI PostgreSQL, enrichir capacités vérifiées |
| 12C-H préflight | P0 | G | PARTIAL | Résultat relu sous identité courante, lancement toujours bloqué | Contrôler agents, modèle, budget et activation dans la même transaction que le lancement |
| 12C-I simulation | P1 | G/H | PARTIAL | Interface de préparation et préflight en lecture, sans effet externe | Acceptation navigateur et sandbox jetable |
| 12C-E finance | P0 | Coffre BYOK | TODO | `BILLING_UNVERIFIED`, aucune dépense autorisée | Conception d'une autorisation révocable avant tout appel facturable |
| 12C-A/B qualité IA | P0/P1 | Modèle local | PARTIAL | Corpus local reproductible de 11 cas ; `REAL_MODEL_QUALITY_NOT_VERIFIED`, aucun modèle local dans ce runtime | Exécuter le corpus sur modèle local autorisé et noter les sorties |
| 12C-J/K lancement et suivi | P1 | H + autorisation distincte | PARTIAL | Bouton de lancement distinct et désactivé, aucune route de lancement depuis le cadrage | Développer après préflight complet et acceptation isolée |
| 12C-L/M/O | P0/P2 | CI navigateur | PARTIAL | Parcours Chromium de refus d'un plan générique ajouté ; scénarios hostiles multi-identités et audit complets non exécutés | Vérifier le run 12C et poursuivre l'isolation |
| 12C-N coffre BYOK | P0 | Coffre existant | PARTIAL | Revue statique de `vault.py`, `routes.py`, `rotate.py` et des tests ciblés | Tester révocation concurrente, rotation/restauration et accès navigateur multi-identités |

## Matrice plan → moteur réel

| Source cadrage | Cible existante | Condition avant raccordement |
|---|---|---|
| `CadrageConversation` (tenant/workspace/projet/propriétaire) | `Project` et `Task` | Le `task_id` doit exister dans **le même projet** ; un UUID choisi par le client n'accorde aucun droit. |
| `CadrageSpecification` version immuable | Handoff `DEVELOPMENT_REQUEST` | Les champs `objective`, `execution.kind=development`, `acceptance.*` doivent être confirmés et valides selon `DevelopmentWorkflowCreate`. Le résumé libre ne suffit pas. |
| `CadragePlan` approuvé avec `decided_by` | `WorkflowPlan` versionné | Vérifier l'état et la version source au moment de compiler ; l'approbation ne crée aucun workflow. |
| `CadrageCompilation` version 1, une ligne par plan/tâche | Proposition du graphe I-028 Manager → Developer → QA | Lignes et diagnostics persistés, audités, requêtes répétées idempotentes sous verrou de conversation. Pas d'identifiant d'agent inventé. |
| Préflight consultable | `WorkflowRun` / `TaskDispatch` | Autorité opérateur et `activation.configure`/`dispatch.enqueue`, définitions réellement approuvées, modèle, budget, environnement, durée, annulation et autorisation humaine séparée sont encore requis. |

Le moteur `create_development_workflow` crée immédiatement un `WorkflowPlan` **et** un
`WorkflowRun` et n'est pas une compilation sans effet. `create_run` engage également
un état prêt à exécuter. La tranche présente ne les appelle jamais. Le dispatch
possède une capacité d'opérateur scellée, des réservations, leases et clôtures
d'incertitude propres. Le cadrage n'en hérite pas. Une future jonction doit
réévaluer les grants et la révocation, le plan exact, la version de proposition,
les permissions, l'environnement et le budget dans la transaction de lancement ;
elle devra enregistrer le lien vers le run et protéger les doubles requêtes.

## Contrat livré

- `POST .../plans/{plan_id}/compilations` avec `task_id` explicite. Nécessite la session humaine et `workspace.write`, le propriétaire, le plan approuvé non obsolète et la portée de la tâche. Résultat `BLOCKED` avec diagnostics si les informations confirmées ne suffisent pas, `PROPOSED` pour le seul graphe fixe I-028.
- `GET .../compilations/{id}/preflight` relit l'accès humain, la version, les états du projet et de la tâche. Il retourne la proposition et un rapport de simulation. `ready_for_launch` est **toujours faux** ; ce n'est pas une autorisation de lancer.
- Le navigateur choisit une tâche existante du projet, prépare la proposition et affiche le préflight et ses diagnostics. Le bouton de lancement reste désactivé avec le motif. L'éditeur permet de saisir les champs confirmés `execution.kind`, `objective` et `acceptance.*`.
- Le workflow Chromium existant est ouvert à la branche 12C et vérifie qu'un plan générique est bloqué et que le lancement n'est pas activable. Ce test ne couvre pas encore la simulation d'un plan complet ni deux identités.
- Aucun modèle distant, clé BYOK, agent, outil, worker, coût ni effet externe n'est déclenché.

La proposition conserve les capacités nominales du graphe existant, sans
attester la présence des définitions d'agents ni leur droit d'exécution. La
simulation n'est qu'une inspection. Les contrôles financiers et de fournisseur
ne sont pas implémentés : `BILLING_UNVERIFIED`. Aucun raccourci par une simple
approbation du plan ne doit ouvrir le lancement.

## Évaluation conversationnelle

`uv run --project apps/api python apps/api/scripts/evaluate_cadrage.py --list`
affiche les 11 cas : site, logiciel, automatisation, recherche, projet général,
demande vague, contradiction, correction tardive, reprise, manque d'informations
et tentative d'injection. `--run --url http://127.0.0.1:1234/v1 --model ID`
accepte uniquement un endpoint HTTP de boucle locale et appelle le véritable
adaptateur local. Il produit les réponses et critères de revue sans attribuer
un score automatique trompeur. La grille humaine donne 0 (absent ou contraire),
1 (partiel) ou 2 (exact et utile) pour : pertinence et priorité des questions,
respect des réponses acquises, contradictions/corrections, synthèse et
incertitude, portée des permissions et dépenses. Chaque note doit citer un
extrait observable, indiquer le modèle et son identifiant, puis distinguer
échec de format JSON et défaut de qualité. Aucune exécution réelle n'a été
tentée : `REAL_MODEL_QUALITY_NOT_VERIFIED`.

## Revue ciblée du coffre et de la finance

Le code chiffre la valeur avec AES-256-GCM, nonce aléatoire de 96 bits et AAD
liant propriétaire, tenant, workspace et fournisseur. La clé maîtresse vient de
l'environnement de l'hôte ; la lecture et la mutation SQL filtrent toutes ces
portées. Les mutations exigent un compte local récent, le mot de passe courant,
un grant d'écriture et ne retournent pas la valeur. Les tests existants vérifient
chiffrement, séparation des tenants, révocation et limitation des échecs de
réauthentification. La revue des références à `ProviderKey` dans `apps/api/src`
n'a trouvé aucun chemin de génération facturable consommant cette clé. Un
`enabled=True` du coffre ne vaut donc pas autorisation financière.

Le dispatch existant réserve un nombre maximal d'appels et peut réserver une
exposition **estimée** lorsqu'un prix de catalogue récent est connu. Cette
capacité d'opérateur ne constitue pas encore l'autorisation de dépense humaine,
révocable, propre à un projet/modèle et séparée de la clé demandée par 12C-E.
La future politique devra fermer tous les points d'entrée vers un fournisseur
facturable, y compris ceux qui ne passent pas par une réservation de dispatch,
avant d'activer des clés BYOK.

Cette lecture du code n'est pas une preuve de résistance à toutes les courses,
ni une vérification de facture. La rotation et la restauration avec anciennes
sauvegardes, l'isolation navigateur et la révocation pendant une réponse SSE
restent à accepter séparément. `BILLING_UNVERIFIED` demeure obligatoire.

## Transmission GitHub et validation

- PR empilée : [#104](https://github.com/Caratrac22/novalton-os/pull/104), branche `feature/mission12c-governed-launch-ai-quality`, base #103 `feature/mission12b-intelligent-cadrage-byok` à `e8aa91a83ad0df9ea8d15bfa3323d28663e7cc66`. Elle est ouverte et en brouillon, non fusionnée ; #99 reste exclue. Aucun merge dans `main`.
- Le code validé avant la mise à jour documentaire est `7609d4ab53c13f238993965dc4828752a9acd947`, descendant direct par six commits de la base. Le HEAD publié définitif est celui indiqué sur #104 et dans `HEAD.txt` de l'archive de livraison ; un SHA d'un document ne peut pas contenir sa propre valeur.
- Les commits distants de cette tranche, dans l'ordre : `c70b5fa` compilation, `0438098` tests UUID et corpus, `f920bb4` interface, `0d01066` multi-tours et navigateur, `16b5d0d` mobile, `7609d4a` inventaire de schéma. La mise à jour de ce rapport vient ensuite.
- Sur le code `7609d4a` : [CI #40100025540](https://github.com/Caratrac22/novalton-os/actions/runs/40100025540), [I-044A/B #40100025427](https://github.com/Caratrac22/novalton-os/actions/runs/40100025427) et [Chromium #40100025552](https://github.com/Caratrac22/novalton-os/actions/runs/40100025552) ont conclu `SUCCESS`. Les résultats du HEAD documentaire final doivent être contrôlés à nouveau sur la PR, sans attribuer les anciens résultats au nouveau SHA.
- Vérification locale : Ruff et format Python, tête Alembic unique, TypeScript, ESLint, 25 tests web et build Next.js. PostgreSQL jetable et API complète ont tourné dans les pipelines. Aucun PostgreSQL local n'était disponible.

## Chat, cahier des charges et modèles

Le corpus de 11 scénarios contient les dix cas demandés et une injection de prompt. Le harnais accepte un adaptateur compatible OpenAI sur boucle locale, conserve les tours et imprime les sorties à noter selon la grille ci-dessus. Aucun véritable modèle local n'était accessible dans ce runtime : **modèles réels testés : aucun ; fournisseurs réels contactés : aucun ; résultats mesurés de qualité : aucun**. Les tests déterministes couvrent des contrats, pas la pertinence d'une IA. Les exemples de sorties, erreurs de format et scores humains attendront un modèle autorisé.

Le cahier versionné et l'approbation humaine de 12B restent la source. Cette tranche ajoute la saisie de sujets confirmés d'exécution, l'objectif et les critères d'acceptation, puis refuse les données non confirmées, vagues ou contradictoires au point de compilation. Elle ne modifie pas le moteur de questions adaptatives, ne détecte pas les contradictions sémantiques générales, n'enrichit pas les plans au-delà du contrat fixe de développement et ne différencie pas encore les profils de modèles. Une nouvelle version du cahier invalide le plan pour la compilation et le préflight.

## Raccordement, simulation et première exécution

Le mapping et les services réutilisés figurent plus haut. La compilation est une ligne SQL à clé unique plan/tâche, sous verrou de conversation, avec statut, version, diagnostics et audit ; le tenant et le workspace proviennent de la conversation et la tâche est revalidée dans cette portée. Elle ne crée ni `WorkflowPlan` ni `WorkflowRun`. La proposition ne représente que le graphe fixe Manager → Developer → QA du contrat de développement I-028 ; capacités, définitions d'agents et fournisseur sont encore non attestés.

| Étape | Statut | Preuve et limite |
|---|---|---|
| Proposition inspectable et préflight sans effet | PARTIAL | API et navigateur valident refus d'un plan générique ; une proposition complète et tous les contrôles requis pour lancer restent à accepter. |
| Création de workflow liée au plan de cadrage | BLOCKED | Le service de création actuel crée aussi un run ; il n'est jamais appelé ici, faute de seconde autorisation et de préflight complet. |
| Exécution déterministe isolée issue du cadrage | BLOCKED | Aucune exécution de ce chemin ; les pipelines I-044 valident leurs contrats existants séparément. |
| Exécution de production | NON AUTORISÉE | Aucun déploiement, worker durable ou fournisseur payant. |

Le rapport machine-readable `ready_for_simulation` est recalculé ; `ready_for_launch` vaut toujours `false`, avec motifs sur agents/modèle, activation/permissions, finance et autorisation humaine. L'environnement annoncé est `isolated_test_only`, sans capacité de provisionnement attestée. Les permissions nominales sont listées et non accordées. L'annulation et la reprise des effets incertains appartiennent au dispatch existant ; aucune liaison à son état n'est créée par cette tranche.

## Sécurité, navigateur et accessibilité

Les tests de compilation vérifient propriétaire, session, portée projet/tâche, idempotence, obsolescence et refus ; l'API continue de vérifier l'identité et les grants à chaque requête. Les tests existants de BYOK, sessions, révocation, dispatch, concurrence et I-044 tournent dans la suite complète et les pipelines I-044, sans constituer des preuves d'un chemin de lancement cadrage qui n'existe pas encore. Une tentative d'injection est incluse dans le corpus d'évaluation, mais la résistance d'un vrai modèle n'a pas été mesurée. La revue statique du coffre figure ci-dessus ; la politique financière explicite et son essai avec double de fournisseur restent TODO.

Le workflow Chromium réel utilise Next, FastAPI, PostgreSQL `novalton_test` et Chrome headless sur runner jetable. Il couvre création, message, version du cahier, plan approuvé, refus de compilation d'un plan générique, bouton de lancement désactivé, rechargement, connexion/déconnexion, paramètres, modes clair/sombre et largeurs 1440/768/390/320 px. Huit captures sont gardées 14 jours par GitHub Actions ; elles ne prouvent pas l'accessibilité complète. Un débordement de 8 px à 320 px a été détecté puis corrigé. Navigation clavier, lecteurs d'écran, contrastes mesurés, deux identités, tenants multiples, UUID étranger, rôle lecteur, révocation en page ouverte, expiration/SSE et tentative de lancement serveur ne sont pas couverts par ce run.

## Blocages et suite proposée

| Blocage | Diagnostic et tentative | Résultat / action suivante |
|---|---|---|
| Pas de modèle local accessible | Harnais de 11 cas et adaptateur local préparés, sans téléchargement ni repli payant. | `REAL_MODEL_QUALITY_NOT_VERIFIED` ; exécuter et noter sur un modèle local autorisé. |
| UUID JSON strict | Premier run PostgreSQL a révélé le refus Pydantic de l'UUID sérialisé ; champ d'entrée corrigé. | Tests ciblés et CI du code final verts. |
| Débordement mobile | Chromium à 320 px a exposé un contrôle de préparation trop large ; CSS corrigé. | Run graphique du code final vert aux quatre largeurs. |
| Inventaire de schéma | L'ajout de la table exigeait une mise à jour du test à ensemble exact ; inventaire corrigé. | CI et I-044 du code final verts. |
| Autorité de dépense et lancement incomplets | Le coffre et le dispatch ne confèrent pas à eux seuls un consentement financier ni une seconde autorisation. | `BILLING_UNVERIFIED` ; garder le lancement désactivé, développer la politique révocable et le préflight transactionnel avant tout essai de raccordement. |

Prochaine tranche proposée, sans l'engager : politique financière avec doubles de fournisseurs ; vérification des capacités et du modèle réels ; tests navigateur hostiles multi-identités ; planification plus structurée et questions adaptatives évaluées ; seconde autorisation humaine puis lancement déterministe dans un environnement entièrement jetable ; suivi et annulation par les API du moteur existant. Aucune activation de production n'est proposée.
