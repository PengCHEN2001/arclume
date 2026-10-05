# Arclume — Document d'exigences produit (PRD)

| Élément | Contenu |
| --- | --- |
| Statut | Brouillon ; certaines décisions produit restent ouvertes |
| Version | 0.2 |
| Mise à jour | 2026-10-03 |
| Responsable produit | cxp |
| Version/date cible | À définir |
| Étape actuelle | Prototype exécutable ; pas encore un service client en ligne |

Ce document décrit le problème, les utilisateurs, le périmètre, l'expérience attendue et les critères d'acceptation. Une fonction présente dans le prototype ne signifie pas qu'elle est prête à être publiée.

## 1. Vue produit

Arclume est un système d'assistance client e-commerce par IA multi-Agent. La première version traite des conversations de support en anglais ; le multilingue viendra ensuite.

Un client peut parler d'un produit, d'une panne de connexion, d'un remboursement et d'une livraison dans un même message. Arclume ne donne pas tout le texte à un seul modèle. Il identifie les domaines, les informations nécessaires et le risque, puis construit un plan : un ou plusieurs Agents traitent la demande, le système recherche des connaissances ou appelle des outils métier contrôlés, et il retourne une réponse unique et traçable.

Le produit vise des réponses fondées et contrôlées. Si une information manque, il doit la demander. Si l'action est risquée ou si l'utilisateur demande un humain, il explique la limite et suit un parcours d'escalade. Le multilingue exige aussi de valider intention, retrieval, terminologie, routage et évaluation dans chaque langue.

## 2. Problème et hypothèses

Une question de politique nécessite une source de connaissance. Une question sur l'état actuel d'une commande nécessite des données métier récentes. Sans frontière claire, un système peut répondre au mauvais sujet, inventer une politique, prendre une ancienne information pour un état réel ou appeler un outil incorrectement.

Hypothèses à valider :

1. Une répartition par domaine et une fusion finale améliorent la couverture des demandes composées.
2. Distinguer connaissance et donnée temps réel réduit les réponses sans preuve et les appels d'outils inutiles.
3. Les traces par requête aident à trouver les erreurs, rejouer les cas et comparer les améliorations.

Ces hypothèses ne sont pas encore validées par des recherches utilisateurs ou des données de production.

## 3. Utilisateurs et cas d'usage

| Utilisateur | Besoin | Priorité |
| --- | --- | --- |
| Client | Réponse claire et exacte ; prochaine étape visible si le problème reste ouvert | Principale |
| Support / opérations | Voir les demandes humaines et maintenir les connaissances | Secondaire ; workflow à définir |
| Produit / opérations techniques | Observer le traitement, trouver les erreurs et mesurer la qualité | Secondaire |

La première version couvre les questions générales, les politiques de remboursement/livraison/produit, les comptes et paiements, les sujets multiples, les demandes en lecture seule sur l'état actuel et les demandes explicites d'assistance humaine. La langue cible est l'anglais ; canal, région et autres langues restent à définir.

## 4. Objectifs et mesures

| Objectif | Mesure | Base actuelle | Cible |
| --- | --- | --- | --- |
| Choisir le bon parcours | Accuracy intention/routage, erreurs par scénario | 92,2 % d'intention et 96,6 % de routage principal simplifié sur 500 cas anglais synthétiques générés par LLM ; non représentatif du trafic réel | À définir |
| Trouver la bonne preuve | Recall@K, MRR, nDCG, comportement sans réponse | 18 questions de retrieval annotées ; pas encore de résultat actuel confirmé | À définir |
| Répondre correctement | Revue humaine de l'exactitude, complétude et preuve | Pas de baseline end-to-end confirmée | À définir |
| Gérer les demandes complexes en sécurité | Couverture, appels inutiles, blocage des opérations à risque | Mécanismes présents ; validation incomplète | À définir |
| Rester stable | Succès, latence, échecs de dépendances, escalade | Pas de baseline production | À définir |

Les scores offline du prototype ne sont pas une promesse de service client.

## 5. Périmètre de la première version

### Dans le périmètre

- Recevoir un message et garder le contexte utile dans une conversation.
- Identifier domaine, informations clés et preuves nécessaires.
- Router une demande simple ou multi-domaine et produire une réponse complète.
- Rechercher politiques et produits ; envisager une lecture métier autorisée pour un état actuel.
- Demander l'information manquante, refuser ou escalader si nécessaire.
- Conserver les événements utiles au diagnostic et à l'évaluation.
- Fournir des entrées simples pour les connaissances et la qualité.

### Hors périmètre actuel

- Exécuter automatiquement remboursement, paiement ou autre écriture à risque.
- Transférer réellement vers une équipe humaine.
- Connecter de vrais systèmes de commande, livraison, paiement ou ticket.
- Promettre disponibilité, performance, conformité vie privée ou multi-tenancy de production.
- Gérer une langue de support autre que l'anglais dans la première version.

## 6. Parcours principaux

**Politique ou produit.** Pour « What is the refund policy? », le système recherche des connaissances puis répond avec les éléments trouvés. Sans preuve fiable, il doit dire qu'il ne peut pas vérifier au lieu d'inventer délais ou conditions.

**Demande composée.** Pour « I cannot log in and I was charged twice », il identifie deux problèmes, les traite séparément puis retourne une réponse cohérente. Il ne doit pas prétendre avoir vérifié un paiement réel sans donnée correspondante.

**État actuel.** Une demande sur une commande doit être distinguée d'une politique de livraison. Seul un résultat métier autorisé peut justifier un état temps réel. Les données Mock ne doivent jamais être présentées comme un dossier réel.

**Humain ou opération à risque.** Une demande humaine reçoit une prochaine étape claire. Une opération à risque ne doit pas être exécutée sans approbation. Tant qu'il n'existe pas d'intégration réelle, le système ne doit pas prétendre avoir créé un ticket ou contacté un conseiller.

## 7. Exigences fonctionnelles

| ID | Priorité | Exigence | Critère observable |
| --- | --- | --- | --- |
| FR-01 | P0 | Recevoir et poursuivre une conversation | Réponse, conversation ID et request ID ; les tours suivants utilisent l'historique utile. |
| FR-02 | P0 | Reconnaître problème et besoin d'information | Distinguer chat, connaissance, donnée temps réel, demande composée et humain ; prévoir un parcours en cas d'incertitude. |
| FR-03 | P0 | Choisir le bon parcours | Envoyer vers un ou plusieurs domaines et permettre d'inspecter le choix. |
| FR-04 | P0 | Répondre avec des connaissances | Rechercher une source si nécessaire ; ne pas prétendre avoir une preuve sans résultat fiable. |
| FR-05 | P0 | Gouverner les outils | Respecter rôle, paramètres et risque ; bloquer une écriture à risque non approuvée. |
| FR-06 | P0 | Produire une réponse complète | Couvrir tous les sujets et sauvegarder la réponse finale. |
| FR-07 | P0 | Demander ou escalader | Donner une prochaine étape exacte sans inventer une escalade terminée. |
| FR-08 | P1 | Maintenir les connaissances | Ajouter/voir des connaissances et vérifier retrieval ; revue, publication et rollback à définir. |
| FR-09 | P1 | Observer et évaluer | Inspecter les décisions et relancer les évaluations ; séparer erreur d'exécution et score valide. |
| FR-10 | P1 | Fournir une interface | Permettre le parcours client principal ; canal, design et accessibilité à définir. |

## 8. Contenu et interaction

- Employer une langue compréhensible et répondre aux problèmes réellement posés.
- Distinguer une action faite, une action proposée et une information non vérifiable.
- Sans preuve, limiter l'affirmation, demander une information ou escalader ; ne pas inventer de politique, commande ou paiement.
- Sources visibles, ton, longueur, mobile, accessibilité et interface opérateur restent à définir.

## 9. Contraintes non fonctionnelles

| Domaine | Décision nécessaire |
| --- | --- |
| Sécurité | Authentification, rôles, autorisation d'outils et approbation des écritures avant intégration réelle. |
| Vie privée | Traitement, conservation/suppression, accès et règles légales des données personnelles. |
| Fiabilité | Comportement quand modèle, base, mémoire ou outil est indisponible ; objectifs de reprise. |
| Performance / coût | Latence, concurrence et coût modèle/outils acceptables. |
| Traçabilité | Persistance, droits d'accès et durée de conservation des requêtes. |
| Cycle de vie des connaissances | Responsable, revue, version, suppression et refresh de l'index. |

## 10. Conditions de validation

Avant de considérer la première version prête, tester de bout en bout questions normales, connaissances, sujets multiples, état actuel, information manquante et humain. Fixer connaissances anglaises, chunking et configuration retrieval ; mesurer rappel/classement avec des exemples revus ; vérifier absence de réponse et informations obsolètes. Une revue humaine doit vérifier exactitude, complétude et soutien par les preuves. Les opérations à risque doivent être bloquées sans approbation. Jeu de test indépendant, seuils, responsable de publication et rollback restent à finaliser.

## 11. État du prototype et écarts

Le prototype contient chat, intention/routage, traitement multi-domaine, mémoire, RAG, outils contrôlés, Trace et évaluation. Cela ne prouve pas les objectifs produit.

- Base de démonstration petite et pas de score retrieval actuel confirmé.
- Outils commande, livraison et ticket Mock ou déterministes.
- Escalade non connectée à un vrai processus ; pas de reprise après approbation dans `/chat`.
- Traces surtout en mémoire ; authentification, gouvernance et persistance de production incomplètes.
- Interface web, qualité des réponses LLM et gestion complète des pannes à valider de bout en bout.

## 12. Risques et décisions ouvertes

| Sujet | Question ouverte |
| --- | --- |
| Besoins utilisateurs | Pas de recherche client ni de distribution réelle des problèmes. |
| Escalade humaine | Équipe, ticket, horaires et promesse client à définir. |
| Intégration métier | Source de données, permissions, idempotence et audit à définir. |
| Gouvernance | Conservation, suppression, isolation et données sensibles à définir. |
| Qualité | Jeu indépendant, cibles et règle de publication à définir. |
| Connaissances | Responsable, revue, mise à jour et nettoyage des anciens index à définir. |

## 13. Références

Les guides suivants ont seulement aidé à organiser ce PRD. Ils ne prouvent pas les besoins ou résultats d'Arclume.

- [Atlassian: How to create a product requirements document](https://www.atlassian.com/agile/product-management/requirements/)
- [Atlassian: Product requirements template](https://www.atlassian.com/software/confluence/templates/product-requirements/)
- [Productboard: Product Requirements Document overview](https://www.productboard.com/glossary/product-requirements-document/)
