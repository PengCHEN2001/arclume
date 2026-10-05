# Roadmap Arclume

Ce document distingue les capacités déjà présentes dans le prototype, les vérifications nécessaires avant une présentation publique et les travaux futurs. Ce n'est pas un journal de changements et il ne promet pas de date. « Implémenté » ne veut pas dire « validé avec de vraies données métier » ni « prêt pour la production ».

## État actuel

Le backend de support client possède une chaîne principale intégrée et une première interface web. Le projet convient à une exécution locale, une démonstration, l'apprentissage et la poursuite du développement. Il ne fournit pas encore la sécurité, la gouvernance des données et l'exploitation attendues en production.

### Principales capacités implémentées

| Domaine | État actuel |
| --- | --- |
| API et application | Endpoints FastAPI pour la santé, le chat, la recherche/import de connaissances, les Skills, les Traces, le Monitor et l'Evaluation. |
| Multi-Agent | Agents General, Technical, Billing et escalade ; profils, routage, coopération sur demandes composées et fusion des résultats. |
| RAG | Recherche Dense ChromaDB et BM25 lexical, recherche parallèle, fusion RRF, déduplication, reranking, variantes de requête, cache, timeout, retry, circuit breaker et fallback. |
| Mémoire | Redis pour la mémoire de travail, les résumés et AgentState ; ChromaDB pour la mémoire épisodique et les profils utilisateur. |
| Gouvernance des outils | Outils contrôlés par Harness : permissions, risque, résultats normalisés, limites de boucle, statistiques et Trace. Les opérations à risque ne contournent pas la frontière d'approbation. |
| Skills | Métadonnées maintenues à la main, sélection par Agent/mots-clés, limite de longueur et rechargement à chaud. |
| Trace et Monitor | Trace par requête, statistiques Agent/Tool, signaux de routage limités et métriques au format Prometheus. |
| Évaluation | Métriques intention/routage, métriques de retrieval, évaluation de dialogue, LLM Judge optionnel et comparaison de régression. Le dépôt contient des cas synthétiques générés par LLM et 18 cas RAG anglais ; les scores RAG et de réponses réelles restent à confirmer. |
| Interface web | Première interface Vue/Vite générée avec AI coding pour le chat, les connaissances et l'évaluation. Le backend reste le centre du projet. |
| Infrastructure locale | Configuration Compose pour Redis, ChromaDB, API, Prometheus et Nginx. |

Limites importantes : les outils de commande, livraison et ticket sont Mock ou déterministes ; les Traces sont surtout en mémoire de processus ; la base de démonstration contient neuf documents anglais fictifs et environ dix-huit chunks ; les 500 cas d'intention sont générés par LLM et non revus indépendamment.

## Vérifications minimales avant une présentation publique

1. **Exécuter un vrai retrieval.** Utiliser un ChromaDB vide et isolé pour les neuf documents de démonstration. Vérifier `/health` et `/knowledge/stats`, puis lancer les 18 cas `rag-smoke-v3`. Conserver la configuration, les métriques et les échecs. Ne pas supprimer une base existante uniquement pour recommencer.
2. **Faire quelques démonstrations `/chat` réelles.** Tester un message simple, une politique de remboursement, un échec de connexion avec double débit et une escalade. Vérifier la réponse, `primary_agent`, `supporting_agents`, `tools_used` et la Trace. Garder d'abord les options LLM Intent/RAG/Memory désactivées. Ne publier que des comportements réellement reproduits.
3. **Nettoyer le dépôt public.** Vérifier que les notes privées, versions expérimentales et clés ne sont pas publiées. Vérifier que README, liens et limites correspondent au code public. Lancer les tests et ne citer que des résultats reproductibles avec leurs limites.

## Directions futures

### 1. RAG : gérer les documents avant de comparer les méthodes

- Ajouter la source, le modèle produit, le périmètre et la version des documents. Définir comment une mise à jour ou suppression retire les anciens chunks, reconstruit BM25 et met à jour les labels d'évaluation.
- Créer un petit jeu anglais relu par un humain : produits proches, modèles précis, exceptions de politique, questions multi-documents, absence de réponse et information obsolète. Comparer Dense, BM25, hybride, réécriture et reranking avec Recall@K, MRR, nDCG et latence.
- Vérifier que la réponse finale est soutenue par les chunks et qu'elle exprime l'incertitude sans preuve. Tester un reranker spécialisé ou d'autres embeddings seulement si les résultats le justifient.

### 2. Agents : valider le routage et la coopération avant d'ajouter des rôles

- Ajouter des cas annotés pour Agents principal/auxiliaire, déclenchement RAG, choix d'outil, refus et escalade. Tester surtout sujets multiples, négation, historique et mots-clés proches.
- Vérifier les répétitions ou contradictions entre réponses multi-Agent. Améliorer la fusion et le fallback si nécessaire.
- Améliorer les réponses courtes comme `yes`, `no`, `it` ou `that`. Le fallback actuel est sûr mais trop général. Une version future pourra utiliser la dernière question Assistant et AgentState pour poser une question ciblée sans deviner.
- Concevoir une vraie approbation humaine, un refus, un timeout et une reprise pour les opérations à risque. Avant cela, les outils d'écriture restent indisponibles pour les Agents `/chat`.

### 3. LangChain / LangGraph : construire une seconde implémentation comparable

- Après apprentissage des frameworks, créer une version séparée avec le même périmètre : intention/routage, Memory, RAG, politique d'outils, escalade et Trace.
- Utiliser les mêmes requêtes et cas d'évaluation pour comparer lisibilité, état, reprise après erreur, latence et nombre d'appels modèle. Garder l'implémentation actuelle si le framework n'apporte pas de gain clair.

### 4. Intégration métier réelle et garanties de production

- Remplacer les outils Mock de commande, livraison et ticket par des adaptateurs configurables. Les écritures réelles exigent authentification, idempotence, protection contre les doublons et audit.
- Définir authentification, permissions, isolation des tenants, rate limiting, CORS, secrets et règles de conservation/suppression des données.
- Évaluer Trace persistante, alertes, limites de ressources et reprise de déploiement dans des scénarios réels.

## Hors engagement actuel

- Créer, modifier, publier ou annuler automatiquement des Skills.
- Ajouter des Agents seulement pour augmenter leur nombre.
- Intégrer MCP externe avant de stabiliser les limites et la gouvernance des outils internes.
- Affirmer que les scores actuels représentent une précision de production ou une préparation à la production.

## Règle de mise à jour

Quand une vérification est terminée ou qu'une direction change, mettre à jour son état et ses preuves. Ne pas présenter une idée non implémentée comme une capacité actuelle. Le README présente le projet ; cette roadmap enregistre les prochaines étapes.
