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
| B seconde autorisation humaine | P0 | TODO | Dépend des contrats de session et d'une empreinte stable ; aucun consentement implicite. |
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
