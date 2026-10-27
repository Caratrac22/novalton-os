# Mission 12F — fiabilité du lancement gouverné

Base vérifiée : PR #106, `65bb50fc4c2eeda09c01f0fb64b5002b9f430fbb` ; CI
`40478544136`, Chromium `40478544110`, I-044A/B `40478544128` SUCCESS sur
ce SHA. Branche empilée `feature/mission12f-governed-execution-reliability`.
La PR, les commits et les gates du HEAD 12F seront consignés après validation.

## Registre

| Tâche | État | Preuve / limite |
|---|---|---|
| Effets incertains du run de cadrage | IN_PROGRESS | Scénarios de crash, timeout, lease et réponse tardive à ajouter puis vérifier sur PostgreSQL. |
| Concurrence et révocations | IN_PROGRESS | Doubles lancements, grants, activation et budget à tester. |
| Chromium hostile | TODO | Deux tenants, UUID, session, plan obsolète et direct API sur les nouvelles routes. |
| I-044 intermittent | IN_PROGRESS | Sur #106, premier job installé échoué `KeyError: state` à l'annulation avec refus AppArmor observés, reprise même SHA réussie. Cause à isoler sans affaiblir la politique. |
| Génération facturable | TODO | Fournisseurs payants toujours désactivés ; inventaire et barrières à vérifier avec adaptateurs simulés. |
| Modèle local réel | BLOCKED | Aucun modèle joignable démontré dans ce runtime ; corpus de 11 scénarios à réutiliser si accessible. `REAL_MODEL_QUALITY_NOT_VERIFIED`. |
| BYOK/restauration PostgreSQL | TODO | Enregistrement chiffré restauré en 12E ; backup PostgreSQL jetable complet à tester. |
| UX et preuves | TODO | Corriger uniquement les écarts reproduits. |

## États et limites

`WORKFLOW_CREATED`, `WORKFLOW_EXECUTED` et `QA_PASSED` sont démontrés en 12E
avec un fournisseur déterministe local. `PRODUCTION_ACCEPTED` reste exclu.
Aucun fournisseur payant, Proxmox ou environnement de production n'est autorisé.
Les effets externes incertains ne doivent jamais être rejoués.
