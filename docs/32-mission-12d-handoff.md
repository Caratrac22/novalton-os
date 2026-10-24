# Mission 12D — tranche de contrôle financier et préflight

Base : PR #104, `775d75ef353478a3ef0ad36cb1fbee39bbefe2c6`.
Branche : `feature/mission12d-governed-execution-financial-authorization`.
La PR empilée et les résultats distants sont à inscrire après publication.

## Registre priorisé

| Tâche | Priorité | État | Preuve et suite |
|---|---|---|---|
| 12D-A finance révocable | P0 | PARTIAL | Politique personnelle/projet/fournisseur/modèle, expiration, version, audit et réservations monotones sous verrou PostgreSQL. Aucun chemin de génération payante n'est encore raccordé au contrôle. |
| 12D-B préflight | P0 | PARTIAL | Définitions exactes des trois agents, activation et génération du dispatch, grants actifs du demandeur interrogés dans la base. Modèle, confidentialité, durée, environnement, annulation et revalidation transactionnelle non prouvés. |
| 12D-C seconde autorisation | P0 | TODO | Aucune autorisation de lancement ni clé d'idempotence de run. |
| 12D-D jonction workflow | P0 | BLOCKED | Conditionnée à B et C ; aucun run créé depuis le cadrage. |
| 12D-E exécution jetable | P0 | BLOCKED | Aucun PASS de bout en bout cadrage → Manager → Developer → QA. |
| 12D-I Chromium hostile | P0 | PARTIAL | [Chromium #40140031116](https://github.com/Caratrac22/novalton-os/actions/runs/40140031116) SUCCESS sur `ab75fdf` : second tenant/propriétaire, projet privé et refus UI/API. Scénarios de perte de grant et révocation de session après page ouverte ajoutés ensuite, à revérifier en CI ; expiration naturelle et plan obsolète en page restent à couvrir. |
| 12D-K CI | P0 | IN_PROGRESS | Ruff, format, compilation Python et SQL Alembic local ; PostgreSQL et pipelines distants à relever. |
| 12D-F interface et suivi | P1 | TODO | Lancement désactivé. |
| 12D-G modèle réel | P1 | BLOCKED | Aucun modèle local accessible dans ce runtime ; `REAL_MODEL_QUALITY_NOT_VERIFIED`. |
| 12D-H qualité cadrage | P1 | TODO | Corpus 11 cas existant, aucune nouvelle mesure de qualité réelle. |
| 12D-J BYOK/accessibilité | P1/P2 | TODO | Tests historiques ; nouveaux scénarios non exécutés. |

## Politique financière

La création exige une session locale récente, le mot de passe actuel, une
confirmation structurée, un projet actif et un grant de workspace. Chaque
autorisation lie l'humain, le tenant, workspace, projet, fournisseur et modèle
exact. Requêtes, tokens et exposition **estimée** ont des limites indépendantes.
La première version accepte explicitement la devise USD seulement et refuse
les estimations d'une précision supérieure à dix décimales, afin d'éviter un
arrondi silencieux qui viderait le plafond.
Une révocation incrémente la version ; création, révocation et réservation
produisent une trace d'audit. La réservation exige à nouveau la session et
le grant humains actifs, verrouille l'autorisation, refuse mauvaise portée,
modèle différent, expiration, révocation et dépassement, et associe une clé
d'idempotence UUID. Les compteurs ne sont jamais remboursés en cas d'effet
externe incertain. Une réponse tardive ne peut pas créer une seconde réservation.

Ces montants ne garantissent **aucun plafond de facture fournisseur** : usage
constaté, prix et effets tardifs doivent encore être rapprochés. Le code n'a
pas de jonction sûre entre tous les appels providers et cette réservation.
Le registre par défaut n'enregistre donc plus le fournisseur HTTP distant
configuré par l'environnement. Le provider local explicite et les doubles
injectés pour les tests sont indépendants. Les anciens chemins d'exécution
de provider distant via une injection explicite ne sont pas qualifiés pour
une exploitation payante. Le coffre BYOK reste déconnecté de la génération.
`BILLING_UNVERIFIED` reste affiché. Aucune clé ou facture réelle testée.

## Préflight et lancement

Le préflight est une inspection en lecture et son résultat n'est pas une
autorisation. Il vérifie maintenant les définitions actives et les constantes
attendues par le service I-028, l'état/génération d'activation et les grants
`workspace.write`, `activation.configure`, `dispatch.enqueue`. Les refus sont
des diagnostics, jamais une erreur de génération ou un lancement implicite.
`ready_for_test_launch` et `ready_for_launch` restent faux : les contrôles
non vérifiés sont indiqués. `ready_for_simulation` conserve sa définition
historique (proposition lisible et non obsolète, sans effet).

La jonction n'est pas une simple invocation de
`create_development_workflow` : ce service appelle `_create_plan` puis
`create_run`, chacun avec son propre commit. Sans refactorisation de ces
frontières, la vérification finale du consentement et de la seconde décision,
l'association durable à la compilation et la création du run ne peuvent pas
être atomiques. L'activer maintenant laisserait des runs orphelins ou des
retries doubles. La proposition et le préflight restent donc consultatifs.

## Validation et limites

- Empreintes des deux archives anciennes vérifiées : bundle `cdc151ad5e3465d9f0f9acf91d5c2b28bb683e144d84fd8661950114d81cdaf7`, ZIP `c80c3f6d315f0dbda28ccd40a886b434b2707b3426598e02211b4afe760251d4`.
- Ruff et format complets : PASS local. Migration Alembic tête unique `20261025_0047`, rendu SQL : PASS local. Import FastAPI et validation Pydantic sans base : PASS.
- PostgreSQL local indisponible ; aucun test de concurrence ou de révocation SQL ne peut être revendiqué PASS local. Des tests réels PostgreSQL ont été ajoutés au fichier d'intégration pour CI : absence de confirmation/réauthentification, quota, modèle, retry, révocation et deux réservations simultanées. Leurs résultats seront relevés après exécution sur `novalton_test`.
- Le parcours complet, navigateur hostile, I-044A/B, HTTPS et modèle réel restent non validés sur cette branche tant que les runs GitHub ne le confirment pas.
- Premier run CI sur `b7b3ce6` : le test local a révélé un HTTP 422 pour deux valeurs JSON usuelles (`estimated_limit`, `expires_at`) car le modèle Pydantic était strict. La validation de ces deux champs a été corrigée avec `strict=False` ; résultat PostgreSQL du HEAD corrigé à relever sur la prochaine CI.
- Deuxième run CI sur `ab75fdf` : les champs JSON passent, mais le filtre d'audit existant refuse la clé de métadonnée `authorization_id` (contient un marqueur réservé aux secrets). Le champ d'audit est devenu `financial_policy_id` ; aucun assouplissement du filtre. La nouvelle révision doit encore passer PostgreSQL. Le frontend de ce run était SUCCESS ; Chromium #40140031116 est SUCCESS avec huit captures aux quatre largeurs et deux thèmes.
- Troisième run CI #40140167676 sur `a5b779e` : migration et suite ciblée `test_local_cadrage.py` ont passé l'étape PostgreSQL ; suite complète encore en cours lors de cette note. Les ajouts locaux ultérieurs (refus projet PAUSED et vraie contention sur la ligne de consentement) devront être revérifiés sur leur HEAD définitif.
- Chromium #40140353588 sur `3eff414` a trouvé une assertion de test erronée : la double connexion de la seconde identité crée deux sessions, donc la révocation modifiait deux lignes, et non une. Assertion corrigée sans retirer le test ; [Chromium #40140457651](https://github.com/Caratrac22/novalton-os/actions/runs/40140457651) est SUCCESS sur `fcc718b` avec perte/restauration de grant et révocation de session vérifiées.

## Étapes suivantes

1. Faire passer les migrations, les tests PostgreSQL et les pipelines ; corriger toute régression.
2. Fermer chaque point de génération payante derrière une réservation et une politique de modèle/prix ; traiter la réponse tardive et les fallbacks. Conserver le fournisseur distant désactivé tant que cette jonction n'est pas démontrée.
3. Établir le préflight complet et sa revalidation atomique, puis une seconde décision humaine liée à l'empreinte de compilation et aux limites d'exécution.
4. Raccorder I-028 et accepter un parcours jetable complet avant d'activer le bouton de lancement ; ensuite étendre Chromium aux deux identités et à la révocation.
