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
| C revalidation de création | P0 | IN_PROGRESS | La création recontrôle sous verrou l'autorisation, la proposition, les grants, le profil/base de test, l'activation et le modèle local. Nouveau test PostgreSQL à vérifier sur CI. |
| D liaison cadrage/workflow | P0 | IN_PROGRESS | Un seul run/compilation et liaison durable dans le même commit que graphe, handoff et audit ; idempotence et refus d'exécution dans le test. Migration 0049 et CI à vérifier. |
| E exécution jetable complète | P0 | BLOCKED | Aucun parcours cadrage → Manager → Developer → QA qualifié. |
| F chemins facturables | P0 | PARTIAL | Fournisseur distant désactivé dans le registre standard ; injection explicite non qualifiée pour la dépense. Cartographie à poursuivre. |
| G BYOK/restauration | P1 | TODO | Rotation, sauvegarde et restauration non validées pour cette mission. |
| H interface | P1 | PARTIAL | Formulaire distinct de décision locale et révocation, protégé par Origin sur le proxy cookie Next ; lancement désactivé et aucune progression fictive. Tests web/Chromium de la branche à relever. |
| I Chromium hostile | P0 | PARTIAL | Gate graphique de branche #40246049990 SUCCESS ; les scénarios propres au nouveau lancement restent à écrire. |
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

Les chemins d'avance directe et d'enqueue historiques refusent explicitement
les runs liés au cadrage avec `launch_execution_unverified`. Ce verrou demeure
jusqu'à une validation distincte de l'autorité par étape, de la révocation, du
modèle routé et des limites de dépense. La révocation d'une décision après
création ne peut donc pas déclencher une exécution de ce run. Les autres
chemins historiques ne changent pas. Cette tranche ne démontre pas E.

La première CI de la migration 0049 a arrêté le test injecté sur une attente
erronée : le middleware HTTP a converti l'exception en réponse 500, au lieu
de la propager à `TestClient`. Le test contrôle désormais cette réponse puis
l'absence de run et de liaison ; la nouvelle CI reste à relever.

## États d'exécution

| État | Preuve 12E |
|---|---|
| `WORKFLOW_CREATED` | Graphe historique confirmé par CI ; création liée au cadrage en attente de la nouvelle CI. |
| `WORKFLOW_EXECUTED` | Non démontré depuis le cadrage. |
| `QA_PASSED` | Non démontré depuis le cadrage. |
| `PRODUCTION_ACCEPTED` | Interdit dans cette mission. |

La révision financière 12D reste une estimation et non un plafond de facture.
`BILLING_UNVERIFIED` et le refus d'exécution facturable subsistent. Aucun appel
payant, publication externe, merge ou déploiement de production.
