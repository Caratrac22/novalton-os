# Mission 12H — frontière commune des générations

Base vérifiée : PR #108, `4279ab1216b65cccd86439c5a22f422f7aaa12d3`. Branche empilée `feature/mission12h-gateway-integration`. HEAD, PR et checks exacts : consulter la PR de livraison. Aucun fournisseur payant n'est enregistré ni activé.

## Registre priorisé

| Chantier | État | Preuve / limite |
|---|---|---|
| P0 point d'entrée unique applicatif | PASS | Les six appels de génération du code applicatif passent désormais par `ProviderRegistry.complete` : chat cadrage, agent initial, continuation d'outil (avec et sans timeout gouverné), récupération de troncature et réparation. La recherche `.complete(` dans le code ne révèle plus de `provider.complete` hors registre et passerelle. |
| P0 refus de cible distante sans consentement | PASS | L'adaptateur HTTP injecté, y compris sous l'identité `local_cadrage`, est refusé avant HTTP sans contexte financier. En production, tout fournisseur non HTTP non reconnu est refusé. Seul `local_cadrage` sans clé peut appeler directement les endpoints loopback 1234/11434. Tests HTTP instrumentés du registre, du chat et de l'agent. |
| P0 tentative facturable liée à un run | PARTIAL | Le chemin `PaidGenerationAttempt` du registre passe par la passerelle de 12G et utilise l'ID d'un `ModelRun` RUNNING, de même portée, projet, fournisseur, modèle et budget de sortie. La réservation unique est committée avant l'I/O et brûlée en cas d'ambiguïté. Une nouvelle identité logique de run pour un même travail reste à interdire au niveau du workflow ; le chat distant ne possède pas encore de `ModelRun`. |
| P0 BYOK et confidentialité des mémoires | PARTIAL | Aucune clé BYOK n'est déchiffrée pour générer, et les fournisseurs payants sont absents du registre runtime. Le filtre des mémoires existant est conservé. La passerelle ne certifie pas encore au point d'envoi la provenance de tout texte injecté, ni une classification récupérée de la base ; aucun chemin applicatif ne lui remet un contexte financier payant. Ne pas activer le distant. |
| P0 concurrence et effets incertains | PARTIAL | Tests 12G de deux réservations et une seule requête HTTP, timeout, révocation et absence de rejeu conservés ; test 12H d'un `ModelRun` inconnu refusé après réservation et sans I/O. Crash et changement simultané de génération au niveau du workflow distant restent à tester après raccordement de l'autorité. |
| P1 Manager → Developer → QA et I-044 | IN_PROGRESS | La suite complète et les gates installés doivent confirmer la régression sur le HEAD final. |
| P1 Chromium | IN_PROGRESS | Gate branché pour 12H ; quatre largeurs, deux thèmes et deux tenants déjà exercés par le script existant. |
| P1 modèle local réel | BLOCKED | Aucun serveur sur 1234/11434 dans Work ; corpus de onze scénarios non exécuté sur un vrai modèle. `REAL_MODEL_QUALITY_NOT_VERIFIED`. |
| P1 profils de sélection | TODO | Politiques économique/équilibré/performance/personnalisé non terminées. Aucun fallback payant implicite n'est activé. |

## Matrice d'envoi

| Chemin | Contrôle effectif avant I/O |
|---|---|
| Chat cadrage | `registry.complete`, fournisseur local loopback exact sans clé ; HTTPS injecté refusé. Pas de chat payant activé. |
| Agent initial Manager/Developer/QA | `registry.complete` ; HTTP distant sans `PaidGenerationAttempt` refusé, même si un catalogue le sélectionne. |
| Continuation d'outil ordinaire ou gouvernée | Même point d'entrée ; le timeout gouverné reste appliqué. |
| Récupération de troncature | Même point d'entrée ; un nouvel appel distant exige sa propre identité et sa réservation. |
| Réparation de contrat | Même point d'entrée ; un nouvel appel distant exige sa propre identité et sa réservation. |
| Appel distant explicitement autorisé dans le registre | `PaidGenerationAttempt` → `PaidGenerationGateway`, destination HTTPS fixe, autorisation/portée/modèle/quotas, `ModelRun` courant, réservation durable, verrou et absence de replay du même ID. Aucun appel applicatif ne construit ce contexte aujourd'hui. |
| Mémoires et registres injectés | Filtre de cible existant, mais provenance à revalider dans la frontière. Un texte seul ne vaut pas preuve : activation payante interdite. |

Une réservation limite l'estimation autorisée ; elle ne garantit pas une facture. `BILLING_UNVERIFIED`. Les preuves déterministes de 12E/12F établissent `WORKFLOW_CREATED`, `WORKFLOW_EXECUTED` et `QA_PASSED` en environnement jetable. `PRODUCTION_ACCEPTED` reste exclu.

## Priorités suivantes

1. Persister l'identité logique du travail, la tentative et l'empreinte du contexte avec unicité interautorisation ; empêcher une seconde création de `ModelRun` après un effet incertain.
2. Transmettre une autorité humaine distincte à tous les chemins d'agents et au chat, puis relier le BYOK déchiffré uniquement dans la frontière serveur ; tester révocation, lease, annulation et réponse tardive à chaque étape.
3. Construire une projection de mémoires typée depuis les enregistrements de base, vérifier `LOCAL_ONLY`/`RESTRICTED` et la portée juste avant chaque envoi. Garder le distant fermé jusqu'aux preuves.
4. Exécuter le corpus réel lorsque le serveur local devient disponible, puis terminer les profils explicites sans fallback payant.
