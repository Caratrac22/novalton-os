# Mission 11 — Socle de navigation SaaS

## Origine et périmètre

Base : PR #100, commit `9a787d48c2756e05485dbe4ad740ae3a2f68e6d1`.
Branche : `feature/mission11-saas-foundation`, PR empilée sur `feature/mission10-integrated-acceptance`. La PR #99 fermée n'est pas utilisée.

Objectif : rendre les fondations web existantes compréhensibles en français sans modifier les autorités d'exécution ni prétendre que l'expérience Novalton complète existe déjà.

## Réalisé dans cette livraison

- Cinq rubriques prioritaires : Accueil, Projets, Centre de contrôle, Environnements, Paramètres.
- Rattachement des routes existantes `/tasks`, `/operator` et `/activity` à leurs rubriques parentes ; accès directs sur ordinateur.
- Accueil orienté projet avec nombre issu du backend et état explicite en cas de panne.
- Centre de contrôle : liens vers les fonctionnalités réelles et RuntimeEvents via le flux existant.
- Environnements : santé API et PostgreSQL réelle, sans simuler un inventaire Proxmox.
- Paramètres : état explicite des capacités et liens vers l'authentification opérateur ; aucune mutation fictive.
- Ajustements responsive, contenu en français sur les nouvelles pages, saut clavier vers le contenu.
- Tests unitaires de sélection du menu et protection des préfixes de routes.

## Non-objectifs et sécurité

Aucune nouvelle autorité serveur, aucune API fournisseur, aucun appel OpenRouter payant, aucune exécution permanente, aucun nouveau mécanisme de session. Les décisions sensibles restent régies par le backend existant. Les pages de statut affichent uniquement les champs sanitaires déjà retournés par `getSystemStatus()`.

Ce n'est **pas** une preuve de fonctionnement Proxmox/WSL2, de budget configurable, de chat de cadrage, de gestionnaire de fichiers ou de session OIDC avec fournisseur externe. L'identité graphique sombre est amorcée ; le thème clair vert reste à concevoir et valider.

## Validation attendue

- `npm run lint`, `npm run typecheck`, `npm run test`, `npm run build` depuis `apps/web`.
- CI générale et gate I-044A/B sur le HEAD exact, sans reprendre les compteurs de la PR #100 comme preuve de la nouvelle mission.
- Contrôle visuel desktop/mobile en environnement browser lorsque disponible.

## Priorités suivantes

1. Tests de navigation intégrés (authentifié/non authentifié, mobile, lecteur d'écran) et harmonisation progressive du français.
2. Chat de cadrage itératif avec questions, mémoire de décisions et cahier des charges persisté.
3. Validation humaine explicite d'un plan avant création de workflow autonome.
4. Gestion de fichiers, inventaire d'environnements et agents composables selon les permissions.
