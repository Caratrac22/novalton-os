# Mission 12G — passerelle IA sécurisée

Base vérifiée : PR #107, HEAD `b75a895babda84c1c9a8f150ae2d5a0509b73336`. PR empilée #108, branche `feature/mission12g-secure-ai-gateway`. Premier commit de code `20fd42678b24664cdd147b2e900e844c9a5d44a1` ; les gates initiaux CI `40908552548`, Chromium `40908552617` et I-044A/B `40908552599` sont à vérifier avant livraison. Le HEAD final et ses gates exacts figurent dans la PR et le rapport final. Aucun merge, déploiement, fournisseur payant réel ni activation de production.

## Registre priorisé

| Chantier | État | Preuve et limite |
|---|---|---|
| P0 inventaire des générations | PASS | `cadrage/generation.py` a un appel local ; `agents/execution.py` a l'appel initial, la continuation d'outil, la récupération de troncature et la réparation de contrat. Le dispatch et QA passent par ces chemins ; les registres de mémoires sont projetés dans l'appel initial. Aucun autre `.complete(` dans le code applicatif. |
| P0 frontière facturable | PARTIAL | `financial/gateway.py` impose destination fixe HTTPS, identité et portée, modèle, quota, réservation unique committée, revalidation et verrou pendant une requête HTTP bornée. Test avec `httpx.MockTransport`. Aucun chemin runtime ne l'appelle ; fournisseurs payants toujours absents de `main.py`. |
| P0 concurrence, révocation, incertitude | PARTIAL | Un identifiant de tentative déjà réservé est refusé, même après timeout ; réservation concurrente sur PostgreSQL, mauvais tenant, mauvaise autorisation, modèle différent et révocation testés. Le futur raccordement devra utiliser un identifiant stable du `ModelRun` et interdire de recréer un autre identifiant pour rejouer le même effet. Le verrou de ligne retarde une révocation concurrente jusqu'à la fin de l'appel borné. |
| P0 confidentialité | PARTIAL | L'adaptateur masque la clé dans ses erreurs et logs ; la passerelle n'accepte pas d'URL arbitraire. Les paquets mémoire sont filtrés pour la cible dans `agents/execution.py`, mais la passerelle n'est pas encore raccordée à ce chemin et ne peut certifier la provenance de texte déjà injecté dans une requête. Aucun BYOK n'est déchiffré pour générer. |
| P1 modèles et politiques | PARTIAL | Routage et capacités existants préservés, aucun fallback payant activé ; profils économique/équilibré/performance/personnalisé non terminés. |
| P1 modèle local réel | BLOCKED | Ports loopback 1234 et 11434 inaccessibles dans ce runtime ; corpus de onze scénarios non exécuté sur un vrai modèle. `REAL_MODEL_QUALITY_NOT_VERIFIED`. |
| P1 Manager → Developer → QA | PARTIAL | Parcours déterministe 12E/12F et gates de régression conservés ; aucun chemin facturable n'est raccordé à leur exécution. |
| P1 I-044 installé | PARTIAL | Diagnostics d'échec bornés enrichis avec forme des champs et état systemd ; cause de l'ancien incident AppArmor/runner encore indéterminée. Aucun retry automatique. |

## Chemins et invariant de facturation

| Chemin | État de sécurité facturable |
|---|---|
| Chat cadrage `local_cadrage` | Local loopback uniquement ; génération distante non raccordée. |
| Agent initial Manager/Developer/QA | Fournisseur payant non enregistré ; raccordement à la passerelle nécessaire. |
| Continuation après outil | Même limite ; nouvelle tentative et nouvelle réservation requises avant chaque I/O. |
| Récupération de troncature | Même limite ; nouvelle réservation, sans rejouer un effet incertain. |
| Réparation du contrat | Même limite ; nouvelle réservation, sans rejouer un effet incertain. |
| Injection de mémoires | Filtre `LOCAL_ONLY`/`RESTRICTED` déjà appliqué avant sélection distante ; provenance à revalider à la frontière avant activation payante. |
| Catalogue de modèles | Métadonnées séparées de la génération ; aucune autorisation implicite. |

La passerelle ne constitue pas une activation. Elle accepte seulement un adaptateur OpenAI-compatible exact à l'une des deux destinations fixées dans le code, avec clé déjà fournie par un composant de confiance. OpenRouter exige une cible amont épinglée, `require_parameters` et les fallbacks désactivés ; l'identité de réponse est contrôlée. `reserve(..., reject_existing=True)` verrouille la politique et brûle durablement l'identifiant avant HTTP. La revalidation du grant, projet et autorisation est sérialisée avec la révocation pendant l'appel. Le quota est une borne sur **l'estimation réservée**, jamais une limite de facture garantie : `BILLING_UNVERIFIED`.

## Validation et limites de livraison

Tests ajoutés : destination hostile et clé absente ; requête HTTP déterministe instrumentée ; tenant, autorisation et modèle étrangers ; révocation ; timeout et identifiant réutilisé ; deux lancements concurrents avec un seul appel. Les tests PostgreSQL s'exécutent en CI sur `novalton_test` ; les gates exacts figurent dans la PR et le rapport final. La machine Work n'a pas de service PostgreSQL local. Ruff et tests fournisseurs indépendants peuvent y être exécutés sans base. Chromium conserve quatre largeurs et deux thèmes sur la branche 12G ; I-044A/B ne modifie ni le runner installé ni sa politique.

Avant toute activation : raccorder **tous** les appels initial/continuation/récupération/réparation et le chat distant à un identifiant de travail durable ; appliquer une autorisation de génération distincte, la provenance mémoire et la sélection de modèle au point d'envoi ; traiter crash, révocation et changement de grant par tests PostgreSQL et HTTP instrumentés ; vérifier l'isolation des secrets BYOK après déchiffrement ; exécuter les onze scénarios sur un modèle local réel. Conserver les fournisseurs payants désactivés jusqu'à ces preuves.

`WORKFLOW_CREATED`, `WORKFLOW_EXECUTED` et `QA_PASSED` restent les résultats jetables démontrés en 12E/12F. `PRODUCTION_ACCEPTED` n'est pas atteint.
