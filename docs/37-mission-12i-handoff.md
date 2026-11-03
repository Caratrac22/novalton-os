# Mission 12I — identité durable et données vérifiées

Base : PR #110, `07b811b65bc3e28c7630895c6fc4a64b1530da29`. Branche empilée `feature/mission12i-durable-generation`. PR, HEAD, commits et CI exacts : voir la PR de livraison. Les fournisseurs payants ne sont ni enregistrés dans le runtime ni activés ; le registre interdit le chemin facturable hors environnement jetable de test.

## Registre priorisé

| Travail | État | Preuve et limite |
|---|---|---|
| Identité durable d'une tentative d'agent | PARTIAL | La réservation porte le `ModelRun`, l'autorisation, un ID de travail, le type/index de tentative et SHA-256 du contexte réellement envoyé. Deux `ModelRun` pour le même travail/type/index ne peuvent obtenir deux réservations, même avec une autre autorisation. Quand un `AgentRun` existe, son ID doit être l'ID de travail. Un nouveau `AgentRun` pour la même étape de workflow et le chat sans lien source persistent restent à traiter. |
| BYOK dans la frontière | PARTIAL | Le chemin jetable du registre accepte seulement un adaptateur HTTPS fixe sans clé préchargée. Après réservation et revalidation, la frontière verrouille la clé du propriétaire, vérifie son activation, la déchiffre avec la keyring serveur et ferme l'adaptateur éphémère. Une clé absente, désactivée ou incompatible empêche HTTP. Les appels applicatifs ne construisent pas encore l'autorité financière pour ce chemin. |
| Mémoires persistées | PARTIAL | La frontière relit les IDs typés, la portée, la classification, la validité et une provenance persistée ; elle construit elle-même le message envoyé et le revalide sous verrou après commit. `LOCAL_ONLY`, `RESTRICTED`, tâche non liée et UUID étranger sont refusés. Le texte libre des autres messages n'a pas de provenance certifiée ; ne pas ouvrir le distant. |
| Chat, agents, continuations, récupérations, réparations | PARTIAL | Tous passent par le registre commun depuis 12H et refusent HTTP distant sans contexte financier. Le chat utilise seulement `local_cadrage`. Le dispatch des agents ne transmet pas encore une autorité financière humaine distincte, donc aucune génération payante n'est activée. |
| Concurrence, révocation, effets incertains | IN_PROGRESS | Index uniques et réservation commitée avant I/O, verrou d'autorisation pendant l'appel, tests de second ID, classement mémoire changé, BYOK désactivé, expiration et timeout. Suite PostgreSQL et gates à confirmer sur le HEAD final. |
| Parcours Manager → Developer → QA, I-044, Chromium | IN_PROGRESS | Contrats existants conservés ; trois gates requis sur le HEAD final. Chromium n'exerce pas encore une interface de lancement payant, qui reste désactivée. |
| Qualité réelle locale | BLOCKED | Aucun serveur local accessible sur 1234/11434 dans cet environnement. `REAL_MODEL_QUALITY_NOT_VERIFIED`. |
| Profils économique/équilibré/performance/personnalisé | TODO | Aucun fallback payant implicite. |

## Matrice des chemins

| Chemin | Contrôle effectif |
|---|---|
| Chat cadrage | Registre commun ; `local_cadrage` sans clé sur loopback exact. HTTPS injecté refusé avant I/O. |
| Agent initial et étapes Manager/Developer/QA | Registre commun ; HTTPS sans tentative financière refusé. `ModelRun` persisté avant génération. |
| Continuation, réparation, récupération | Registre commun ; chaque nouvelle génération a son `ModelRun` et son type/index. HTTPS sans tentative financière refusé. |
| Tentative HTTPS explicitement injectée en test | Destination fixe, autorité humaine, modèle/portée/grants, budget et quotas, unicité du travail/type/index, empreinte du contexte, réservation durable, clé BYOK active déchiffrée dans la frontière, projection des mémoires persistées. Aucun fournisseur réel appelé. |
| Mémoires injectées dans les agents existants | Filtrage de cible existant. Leur contenu n'est pas encore transmis comme IDs à la frontière payante ; le payant reste fermé. |

La réservation borne une estimation, pas la facture : `BILLING_UNVERIFIED`. Les preuves antérieures du parcours jetable distinguent `WORKFLOW_CREATED`, `WORKFLOW_EXECUTED` et `QA_PASSED` ; `PRODUCTION_ACCEPTED` est exclu.

## Priorités

1. Lier l'identité à la requête source du chat et à l'étape de workflow, avec unicité à travers les nouveaux `AgentRun` après un effet incertain.
2. Transmettre l'autorité humaine et les IDs de mémoires depuis les véritables chemins applicatifs ; interdire tout texte injecté non tracé avant une activation payante.
3. Étendre Chromium aux parcours BYOK et autorisations une fois ces chemins activables en simulation, puis évaluer le modèle local disponible et les profils explicites.
