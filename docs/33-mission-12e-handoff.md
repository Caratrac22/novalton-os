# Mission 12E — transaction de workflow et lancement supervisé

Base vérifiée : PR #105, `5e87db032f74ac2e644099e775b2f241ed9b1e30`, CI
`40243856923`, Chromium `40243856782`, I-044A/B `40243856849` SUCCESS.
Branche `feature/mission12e-atomic-governed-launch`, PR brouillon empilée sur
#105. Le HEAD final et les validations sont à relever sur la PR après le dernier
commit ; un document versionné ne peut indiquer son propre SHA.

## Registre

| Tâche | Priorité | État | Preuve / blocage / prochaine action |
|---|---|---|---|
| A transaction du workflow | P0 | IN_PROGRESS | Plan, run, audit et handoff dans une transaction unique pour le graphe fixe ; tests de rollback injecté et de transaction contrôlée par l'appelant. PostgreSQL CI à vérifier. |
| B seconde autorisation humaine | P0 | IN_PROGRESS | Décision persistante, révocable, liée au plan/compilation/document/versions, à l'environnement jetable, au modèle local, aux grants et aux limites ; reauth et test PostgreSQL ajoutés, CI à relever. Aucun run créé par cette décision. |
| C revalidation de lancement | P0 | BLOCKED | Dépend de B et de la preuve de transaction. Préflight de lecture seulement. |
| D liaison cadrage/workflow | P0 | BLOCKED | Aucun run depuis une compilation tant que B/C ne sont pas démontrés. |
| E exécution jetable complète | P0 | BLOCKED | Aucun parcours cadrage → Manager → Developer → QA qualifié. |
| F chemins facturables | P0 | PARTIAL | Fournisseur distant désactivé dans le registre standard ; injection explicite non qualifiée pour la dépense. Cartographie à poursuivre. |
| G BYOK/restauration | P1 | TODO | Rotation, sauvegarde et restauration non validées pour cette mission. |
| H interface | P1 | BLOCKED | Lancement désactivé tant que B–E restent bloqués. |
| I Chromium hostile | P0 | TODO | Scénarios 12D historiques ; nouvelle gate de branche à relever. |
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
Le plan et le run sont rechargés avant de revenir au caller ; la nouvelle CI
doit confirmer la correction sans masquer les erreurs.

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

## États d'exécution

| État | Preuve 12E |
|---|---|
| `WORKFLOW_CREATED` | Route historique seulement, à tester sur cette branche ; aucune liaison au cadrage. |
| `WORKFLOW_EXECUTED` | Non démontré depuis le cadrage. |
| `QA_PASSED` | Non démontré depuis le cadrage. |
| `PRODUCTION_ACCEPTED` | Interdit dans cette mission. |

La révision financière 12D reste une estimation et non un plafond de facture.
`BILLING_UNVERIFIED` et le refus d'exécution facturable subsistent. Aucun appel
payant, publication externe, merge ou déploiement de production.
