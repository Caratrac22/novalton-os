# Mission 12C — jonction contrôlée, première tranche (24 octobre 2026)

## Registre priorisé

| ID | Priorité | Dépendances | État | Preuve / blocage | Prochaine action |
|---|---|---|---|---|---|
| 12C-F audit | P0 | Aucune | PASS | Matrice ci-dessous, code 12B lu | Vérifier à chaque évolution du moteur |
| 12C-G compilation | P0 | F | PARTIAL | Proposition SQL, contrôle de portée, tests de refus | CI PostgreSQL, enrichir capacités vérifiées |
| 12C-H préflight | P0 | G | PARTIAL | Résultat relu sous identité courante, lancement toujours bloqué | Contrôler agents, modèle, budget et activation dans la même transaction que le lancement |
| 12C-I simulation | P1 | G/H | PARTIAL | Lecture des étapes fixes sans effet externe | Acceptation navigateur et sandbox jetable |
| 12C-E finance | P0 | Coffre BYOK | TODO | `BILLING_UNVERIFIED`, aucune dépense autorisée | Conception d'une autorisation révocable avant tout appel facturable |
| 12C-A/B qualité IA | P0/P1 | Modèle local | BLOCKED | `REAL_MODEL_QUALITY_NOT_VERIFIED` ; aucune preuve de modèle local dans ce runtime | Harnais reproductible et essai sur modèle local autorisé |
| 12C-J/K lancement et suivi | P1 | H + autorisation distincte | TODO | Aucune route de lancement depuis le cadrage | Développer après préflight complet et acceptation isolée |
| 12C-L/M/N/O | P0/P2 | CI navigateur, coffre | TODO | Scénarios hostiles et audit complets non exécutés | Parcours multi-identités et validation transverse |

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
- Aucun modèle distant, clé BYOK, agent, outil, worker, coût ni effet externe n'est déclenché.

La proposition conserve les capacités nominales du graphe existant, sans
attester la présence des définitions d'agents ni leur droit d'exécution. La
simulation n'est qu'une inspection. Les contrôles financiers et de fournisseur
ne sont pas implémentés : `BILLING_UNVERIFIED`. Aucun raccourci par une simple
approbation du plan ne doit ouvrir le lancement.
