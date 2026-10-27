# Mission 12E — transaction de workflow et lancement supervisé

Base vérifiée : PR #105, `5e87db032f74ac2e644099e775b2f241ed9b1e30`, CI
`40243856923`, Chromium `40243856782`, I-044A/B `40243856849` SUCCESS.
Branche `feature/mission12e-atomic-governed-launch`, PR brouillon empilée sur
#105. Le HEAD final et les validations sont à relever sur la PR après le dernier
commit ; un document versionné ne peut indiquer son propre SHA.

## Registre

| Tâche | Priorité | État | Preuve / blocage / prochaine action |
|---|---|---|---|
| A transaction du workflow | P0 | PASS | Plan, run, audit et handoff dans une transaction unique pour le graphe fixe ; tests PostgreSQL de rollback et CI #40246050058 SUCCESS. |
| B seconde autorisation humaine | P0 | PASS | Décision persistante et révocable ; reauth, grants et versions ; CI #40246050058 SUCCESS. La décision seule ne crée pas de run. |
| C revalidation de création | P0 | PASS | Recontrôle sous verrou de l'autorisation, de la proposition, des grants, du profil/base de test, de l'activation et du modèle local. Test PostgreSQL et CI #40316187645 SUCCESS. |
| D liaison cadrage/workflow | P0 | PASS | Un seul run/compilation et liaison durable dans le commit du graphe, handoff et audit ; rollback et idempotence concurrente testés sur PostgreSQL. CI #40316187645 SUCCESS. |
| E exécution jetable complète | P0 | IN_PROGRESS | Route de dispatch réauthentifiée, garde par claim et modèle local à tarif zéro ; tests déterministes QA PASS, révocation après Manager et annulation ajoutés ; confirmer sur CI finale avant PASS. |
| F chemins facturables | P0 | PARTIAL | Fournisseur distant désactivé dans le registre standard ; injection explicite non qualifiée pour la dépense. Cartographie à poursuivre. |
| G BYOK/restauration | P1 | TODO | Rotation, sauvegarde et restauration non validées pour cette mission. |
| H interface | P1 | IN_PROGRESS | Création, dispatch et lecture des états persistés reliés au proxy Next avec Origin vérifié ; lint/typecheck/build locaux passent, Chromium final à relever. |
| I Chromium hostile | P0 | PARTIAL | Gate graphique du code final #40316187661 SUCCESS ; les scénarios hostiles propres à la nouvelle route de création restent à écrire. |
| J qualité du chat | P1 | BLOCKED | Modèle local indisponible dans ce runtime ; `REAL_MODEL_QUALITY_NOT_VERIFIED`. |

## Frontière transactionnelle

Le service I-028 historique validait le plan, puis le run, puis le handoff
avec trois commits. Le graphe fixe utilise maintenant les opérations internes
de persistance sans commit et effectue un seul commit après le handoff. Le
paramètre interne `commit=False` permet à une application future de contrôler
elle-même la transaction englobante. Les routes historiques continuent à
committer une réponse complète. Les audits sont insérés dans la même transaction ;
aucun journal de succès n'est émis avant le commit pour ce chemin.

Les tests injectent une erreur au handoff après la création du plan/run et
contrôlent leur absence après rollback ; un second test crée le graphe complet
sous transaction de l'appelant, puis annule et vérifie l'absence des quatre
entités (plan, run, handoff, audit). Le résultat PostgreSQL de ces tests doit
être relevé sur la CI de la branche avant PASS.

La première CI du refactoring a révélé des réponses HTTP 500 dans les routes
historiques de création : les valeurs nullable/default chargées depuis la base
manquaient à la sérialisation après le changement de frontière transactionnelle.
Le plan et le run sont rechargés avant de revenir au caller ; la CI
#40246050058 confirme la correction des routes historiques.

## Seconde décision humaine

Un endpoint dédié crée une décision pour un plan approuvé et une compilation
`PROPOSED` dont le document est recalculé depuis le plan, lorsque la spécification
reste actuelle, le projet est actif et la tâche exécutable. L'utilisateur local
doit posséder les trois grants exacts, présenter une session récente et son mot
de passe, envoyer une confirmation littérale et une clé UUID de requête.
L'empreinte SHA-256 canonique lie le plan, la compilation, la tâche, les
versions, les limites, les permissions, l'environnement jetable et le modèle
local. La clé idempotente est unique par propriétaire et refuse un contenu
différent. L'expiration est bornée à dix minutes ; la révocation et son audit
sont atomiques. Le fournisseur est limité par schéma et contrainte SQL à
`local` ; aucune permission de dépense n'est déduite d'une clé BYOK.

Il s'agit d'une autorisation préparatoire : le lancement reste absent et la
validité doit être recontrôlée dans la transaction qui créera le workflow.
Le proxy Next refuse les mutations sans Origin HTTPS exact et ne transmet que
les champs nécessaires au backend ; le mot de passe n'est pas conservé après
la réponse. L'API directe exige un bearer local explicite, sans cookie ambiant.

La première CI avec la nouvelle route a échoué dans un test de refus : il
attendait l'erreur de tâche `BACKLOG` avant d'ajouter les grants dispatch,
alors que le serveur refuse correctement l'absence de grant en premier. Le
scénario a été réordonné pour tester les deux frontières séparément.

## Création non exécutante depuis le cadrage

La route `/{launch_authorization_id}/workflow` exige une confirmation distincte,
une clé UUID idempotente et une réauthentification locale. Elle refuse tout profil
autre que `test` et vérifie `current_database() = novalton_test`. Sous verrous,
elle revalide la spécification courante, le plan approuvé, la compilation
recalculée, l'état projet/tâche, l'empreinte et l'expiration/révocation de la
décision, les trois grants, la génération de l'activation, le modèle local
configuré et une entrée de catalogue `AVAILABLE`/`LOCAL`. L'absence d'un seul
élément refuse la création. La migration 0049 ajoute une liaison facultative
sur la décision, avec unicité par compilation et par run. Le graphe fixe, le
run `CREATED`, le handoff, les audits et la liaison partagent un commit. Une
répétition avec la même clé renvoie le run ; une clé différente est refusée.
La route ne contacte aucun fournisseur.

Le test PostgreSQL provoque un échec de l'audit après écriture du graphe et
vérifie le rollback du run et de la liaison. Il envoie ensuite deux requêtes
concurrentes de même clé et vérifie l'unicité du run, puis refuse une autre clé
et l'avance directe. La CI #40316187645 confirme cette vérification.

Le premier essai concurrent a exposé un verrouillage croisé. La dépendance
HTTP conservait des verrous partagés sur la session locale et les grants avant
que la route ne demande des verrous exclusifs. Le simple rollback dans la route
ne suffisait pas : une deuxième requête pouvait déjà tenir la session en
lecture tout en attendant le grant détenu par la première. Pour les seules
mutations de lancement, la dépendance identifie l'utilisateur sans prendre
ces verrous ; la route termine sa transaction de lecture, puis revalide la
session, les grants et le rôle sous verrous exclusifs avant toute écriture.
La CI #40316187645 confirme la correction.

L'avance directe reste interdite pour les runs liés au cadrage. Le dispatch
requiert désormais une nouvelle requête humaine réauthentifiée, une confirmation
littérale, un UUID idempotent et le contexte interne de la route. La transaction
vérifie de nouveau le plan, la compilation, la spécification, le projet, la tâche,
l'empreinte, les grants, la décision, l'activation et le modèle local disponible
avec les deux tarifs explicitement nuls. Seul le profil `test` sur la base
`novalton_test` peut accepter cette requête. Le worker prend ensuite un claim
durable et recontrôle décision, génération, grants, budget et modèle à chaque
réservation. Un résultat tardif traverse de nouveau les barrières de l'effet.
Le parcours Manager → Developer → QA est exercé avec un adaptateur déterministe,
sans appel réseau ni coût, mais cette tranche n'est PASS qu'après la CI finale.
Le test complémentaire coupe l'autorisation après Manager et vérifie qu'aucun
appel Developer/QA n'est émis ; un troisième scénario annule le run et refuse
le claim suivant. Les effets incertains du dispatcher restent couverts par les
tests historiques, sans preuve spécifique supplémentaire au run de cadrage.

La première CI de la migration 0049 a arrêté le test injecté sur une attente
erronée : le middleware HTTP a converti l'exception en réponse 500, au lieu
de la propager à `TestClient`. Le test contrôle désormais cette réponse puis
l'absence de run et de liaison ; la CI #40316187645 est SUCCESS.

## États d'exécution

| État | Preuve 12E |
|---|---|
| `WORKFLOW_CREATED` | Graphe et liaison depuis le cadrage confirmés sur PostgreSQL par CI #40316187645 ; aucun modèle appelé. |
| `WORKFLOW_EXECUTED` | Scénario déterministe en attente de confirmation sur le HEAD final exact. |
| `QA_PASSED` | Verdict `PASS` et trois ModelRuns attendus dans le test PostgreSQL ; CI finale à relever. |
| `PRODUCTION_ACCEPTED` | Interdit dans cette mission. |

La révision financière 12D reste une estimation et non un plafond de facture.
`BILLING_UNVERIFIED` et le refus d'exécution facturable subsistent. Aucun appel
payant, publication externe, merge ou déploiement de production.

## Inventaire des points de génération

| Chemin | Autorité effective dans cette tranche |
|---|---|
| Chat de cadrage (`cadrage/generation.py`) | Appel direct à `local_cadrage`, lorsque configuré ; distinct du workflow. |
| Avance orchestrée et agents (`orchestrator`, `agents/execution.py`) | Les runs de cadrage exigent un claim durable actif et le modèle catalogué `local_cadrage` avec prix USD zéro. |
| Routes directes Manager, Developer et QA | Chemins historiques séparés de la décision de lancement ; aucun droit de dépense ne découle du BYOK. |
| Registre standard (`main.py`) | Seul `local_cadrage` peut être enregistré par configuration ; fournisseur distant absent de ce registre. |

Une injection explicite d'un autre registre hors du démarrage standard n'est
pas qualifiée pour une dépense. La rotation/restauration BYOK et les limites
facturables restent donc ouvertes ; aucun test 12E ne contacte un fournisseur
payant.
