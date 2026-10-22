# Mission Work 10F + 11 — transmission du 22 octobre 2026

## Base et frontières

PR #101 `feature/mission11-saas-foundation`, brouillon, empilée sur la PR #100 `feature/mission10-integrated-acceptance` à `9a787d48c2756e05485dbe4ad740ae3a2f68e6d1`. Base inspectée avant modification : #101 `e82a7da623016246c418935c58626ac52ff62aa7`, trois commits en avance sur #100 ; #99 fermée, non fusionnée et absente de l'ascendance. Aucune fusion, aucun rebase ni force-push. La CI #101 antérieure `39748822125` était SUCCESS mais ne vaut pas preuve pour le nouveau HEAD. Vérifier les runs sur le HEAD publié.

## Matrice d'acceptation 10F

| Critère | Preuve existante | État et limite |
|---|---|---|
| OIDC HTTPS local, S256 PKCE, state, nonce, signature RS256 et session | `apps/web/scripts/operator-oidc-smoke.mjs`, `operator-oidc.test.ts` ; CI #100 `39731721993` SUCCESS | PASS en environnement local contrôlé ; fournisseur externe NOT_VERIFIED. |
| Callback derrière proxy TLS | Smoke HTTPS et correctif de la PR #100 ; host public et `x-forwarded-proto=https` | PASS sous proxy de confiance qui écrase les headers et bloque l'accès direct à Next ; déploiement réel NOT_VERIFIED. |
| Cookies, Origin, workspace | Smoke, `operator-origin.test.ts`, `test_durable_dispatch_sessions.py` | PASS pour les routes opérateur testées ; les anciennes routes Projets/Workflows relèvent d'une autre frontière de confiance configurée côté serveur. |
| Next → FastAPI → PostgreSQL `novalton_test` | `test_operator_integrated_journey.py::test_local_oidc_console_and_real_api_workflow`, CI #100 | PASS en CI jetable avec client HTTP/cookie jar ; aucun navigateur graphique. |
| Manager → Developer → QA, preuves persistées | `test_signed_human_operates_completed_workflow_and_loses_authority`, test intégré ci-dessus | PASS avec fournisseur local déterministe ; workflow déjà créé/exécuté avant la consultation console, aucun chat de cadrage. |
| Annulation, révocation, refus cross-scope | Mêmes tests, smoke et autres tests de sessions | PASS dans les cas testés. Logout retire le cookie du navigateur ; une copie du token non révoquée relève du TTL ou de la révocation du grant. |
| Pas de rejeu incertain, I-044A/B | Tests de dispatch/heartbeat, gate #100 `39731722057` SUCCESS | PASS sur le HEAD #100 ; aucune modification de ces mécanismes dans #101. |
| Navigation graphique, mobile, expiration | Aucun moteur navigateur local installé ; smoke emploie HTTP | GRAPHICAL_ACCEPTANCE_NOT_VERIFIED. |
| IdP externe, fournisseur payant, facture indépendante, daemon H24 | Aucun accès ni budget autorisé | NOT_VERIFIED ; `LIVE_ACCEPTANCE_BLOCKED_CREDENTIALS_OR_BUDGET`, `BILLING_UNVERIFIED`. |

Le smoke local a été rejoué après la traduction de l'interface avec un IdP HTTPS local et un backend de test à jetons signés : PASS. Cela ne remplace pas l'intégration FastAPI/PostgreSQL de la CI.

## Audit et corrections Mission 11

- Les cinq entrées principales et les trois anciennes routes sont conservées. Les accès directs Tâches, Activité et Opérateur sont maintenant également visibles sur mobile ; clavier, focus et réduction du mouvement sont pris en compte par les styles.
- Apparence : palette sombre bleu-violet et palette claire verte. Le choix est conservé dans `localStorage` du navigateur et synchronisé entre onglets. Ce n'est pas un paramètre serveur ni une permission.
- Accueil : projets réellement chargés et liens directs vers les cinq premiers. Le compteur indique explicitement `100+` lorsque la première page atteint sa limite ; aucune donnée simulée.
- Projets/Tâches : liste, création, détail contextuel et sélection via les endpoints existants. Une URL de projet ou tâche absente du résultat chargé ne bascule plus silencieusement vers un autre projet/tâche. Première page limitée à 100 ; la pagination complète reste à faire.
- Contrôle : statuts du lot de workflows chargé, extrait de dix exécutions, flux RuntimeEvents existant. Une réponse workflow malformée produit un état indisponible au lieu d'un faux zéro. Aucun pourcentage de progression inventé.
- Opérateur : liste et détail plus lisibles en français, coûts estimés distincts des coûts déclarés, état vide, décisions accessibles sur mobile. Les actions existantes restent soumises au backend. Un refus d'approbation Git et un échec de rafraîchissement sont désormais visibles, sans prétendre qu'ils ont réussi.
- Environnements : santé API/PostgreSQL réelle seulement. Paramètres : apparence locale, liens vers fonctions existantes et intégrations indiquées non configurées. Pas de provisionnement ajouté.
- Le parcours de développement gouverné conserve les mêmes mutations ; la traduction ne transforme pas la séquence fixe en agents adaptatifs.

## Matrice des tâches

| Tâche | Statut | Preuve ou reste |
|---|---|---|
| 10F-A | PASS | Audit du rapport #100, scripts et tests cités ci-dessus. |
| 10F-B | BLOCKED | GRAPHICAL_ACCEPTANCE_NOT_VERIFIED : aucun navigateur graphique local disponible ; pas de capture desktop/mobile. |
| 10F-C | PARTIAL | Erreurs et états trompeurs de l'interface corrigés ; aucun défaut de l'OIDC lui-même reproduit. Défauts de frontière SaaS décrits ci-dessous. |
| 11-A | PASS | Routes, composants, API et diff #101 inspectés. |
| 11-B | PARTIAL | Style, thème et accès mobiles améliorés ; examen graphique, contrastes instrumentés et lecteur d'écran NOT_VERIFIED. |
| 11-C | PARTIAL | Projets réels et liens directs ; autres métriques et attention humaine agrégée restent limitées aux API actuelles. |
| 11-D | PARTIAL | Création/liste/tâches et sélection sûre ; pagination et projet riche à compléter. |
| 11-E | PARTIAL | Console et erreurs améliorées ; aucun historique complet ni contrôle graphique validé. |
| 11-F | PARTIAL | Santé réelle, préférence locale ; provisionnement et configuration des fournisseurs non implémentés et annoncés. |
| 11-G | PARTIAL | 23 tests web, ESLint, TypeScript, build Next et smoke local PASS ; tests navigateur NOT_VERIFIED. CI du nouveau HEAD à consulter. |

## Vérifications locales

`npm ci`; `npm run test --workspace @novalton/web` : 23/23, dont une régression de sélection ; `npm run lint --workspace @novalton/web` : PASS ; `npm run typecheck --workspace @novalton/web` : PASS ; `npm run build --workspace @novalton/web` : PASS ; `node apps/web/scripts/operator-oidc-smoke.mjs` : PASS, IdP local HTTPS + API stub à signature vérifiée ; `npm audit --audit-level=high --omit=dev` : 0 vulnérabilité ; `git diff --check` : PASS. Après le dernier changement, revérifier le build et la CI exacts. PostgreSQL local et batterie backend non relancés : aucun code backend, aucune migration ou autorité I-044 modifiée ; CI #100 en donne les preuves existantes. Aucun test destructif sur base réelle.

## Sécurité et limites de livraison

Aucun secret ajouté, aucune API externe appelée, aucun coût fournisseur, aucun daemon lancé. Les contrôles I-044 et le filtrage des RuntimeEvents n'ont pas été modifiés. Les vues web Projets/Tâches/Workflows existantes utilisent le tenant/workspace configuré côté serveur sans session opérateur individuelle, tandis que la console opérateur utilise le jeton OIDC et ses contrôles backend. Cette frontière préexistante ne prouve pas une isolation multi-utilisateur du SaaS public ; les routes de création/approbation de la console historique ne peuvent être qualifiées de parcours OIDC gouvernés. La PR doit rester en brouillon et l'exposition publique attend une architecture d'autorisation homogène, des protections de mutation et des tests cross-tenant/cross-workspace. Ne pas masquer cela derrière un thème plus joli.

## Suite priorisée, avant ou pendant le cadrage de mission 12

1. Définir et tester la frontière d'identité des routes web historiques Projets/Tâches/Workflows/approbations avant ouverture multi-client ; garder les contrôles I-044 et les grants serveur.
2. Valider dans un navigateur graphique HTTPS contre IdP local, Next, FastAPI et PostgreSQL jetable : clavier, mobile, révocation, expiration et logout. Tester les deux thèmes et les contrastes.
3. Ajouter pagination réelle, choix du projet actif et navigation directe vers le workflow lié à une tâche sans déduction depuis les 100 premiers runs.
4. Compléter les libellés et messages métier français fournis par l'API, sans exposer données brutes ni prompts.
5. Mission 12 seulement sur nouveau prompt : cadrage conversationnel durable, plan soumis à approbation et lancement gouverné. Ne pas présenter le chat comme existant.
