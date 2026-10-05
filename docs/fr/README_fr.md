# Arclume : comprendre, chercher des preuves, puis répondre

[English](../../README.md) · **Français** · [中文](../zh/README_zh.md)

Arclume est un prototype backend multi-agents pour le support client en anglais. Un client peut signaler plusieurs problèmes dans une même phrase, puis poser une question courte qui dépend du contexte précédent. Le système ne cherche donc pas seulement à produire un texte fluide : il identifie les problèmes, choisit le bon parcours, récupère les informations utiles, contrôle les outils et enregistre la trace du traitement.

```text
comprendre la demande
→ préparer un plan de traitement
→ obtenir des preuves si nécessaire
→ faire coopérer les Agents
→ générer une réponse
→ sauvegarder et tracer le résultat final
```

> Arclume est un projet personnel d'apprentissage et d'ingénierie. La version actuelle n'utilise pas LangChain, LangGraph ni un autre framework Agent de haut niveau. Ces frameworks accélèrent un prototype, mais peuvent cacher le passage d'état, l'orchestration, les appels d'outils et la gestion des erreurs.
>
> Cette version implémente explicitement en Python la reconnaissance d'intention, le routage, la construction du Context, la boucle de Tool Call, la Memory et les Traces. Une version de comparaison avec LangChain / LangGraph est prévue plus tard.
>
> Des outils d'AI coding ont aidé à écrire, refactoriser et tester le code. Le projet reste un prototype : il ne prétend pas être un service client de production.

## Structure du dépôt

```text
arclume/
├── api/                 routes FastAPI, démarrage et composants partagés
├── agents/              routage, profils, exécution et fusion des réponses
├── core/                intentions, client LLM, Skills et construction du Context
├── memory/              mémoire Redis, mémoire longue ChromaDB et état du dossier
├── knowledge/           découpage des documents, recherche vectorielle et BM25
├── tools/               capacités concrètes : connaissances, commande, livraison
├── harness/             permissions, validation, risque, exécution et Trace
├── frontend/            interface de chat Vue/Vite optionnelle
├── data/                documents de démonstration et données locales
├── docs/                documents produit, conception, code et évaluation
├── evaluation/          cas offline, métriques et rapports
├── tests/               tests de régression sans service externe réel
├── config/              configuration Prometheus et Nginx
├── requirements.txt     dépendances Python
├── docker-compose.yml   stack locale API, Redis, ChromaDB et Prometheus
└── Dockerfile           construction de l'image API
```
## Autres documents explicatifs

- [Document des exigences produit (PRD)](PRD_fr.md) : utilisateurs cibles, définition du problème, périmètre de la première version, exigences principales, critères d’acceptation et hypothèses à valider.
- [Design du projet et flow complet](project_design_and_request_flow_fr.md) : parcours d’une requête, design de chaque couche et principaux choix techniques.
- [Guide de structure du code et d’implémentation](code_guide_fr.md) : structure des dossiers, principaux fichiers, classes et fonctions, configuration et points d’entrée pour les modifications.
- [Système d’évaluation et méthodes d’exécution](evaluation_protocol_fr.md) : datasets, métriques, commandes d’exécution et limites des résultats.
- [Roadmap](roadmap_fr.md) : checklist de validation avant la présentation publique du projet et prochaines étapes d’itération.

## Ce que traite le prototype

Pour le message `I cannot log in and I was charged twice.`, Arclume détecte deux problèmes indépendants. Il peut choisir les Agents Technical et Billing, leur donner une sous-tâche distincte, puis fusionner leurs réponses. Le tour suivant relit la réponse finale fusionnée, pas seulement le brouillon d'un Agent.

Une question de politique, de produit ou de dépannage peut rechercher une information dans la base de connaissances. Une demande de commande ou de livraison avec un identifiant peut appeler un outil métier en lecture seule. Si une information importante manque, le système demande à l'utilisateur de la fournir. Une demande explicite d'assistance humaine suit un parcours déterministe d'escalade.

Ces mécanismes ne signifient pas que le prototype peut vérifier un vrai paiement ou contacter une vraie équipe de support.

## Chaîne principale

```text
POST /chat
  → lire la mémoire de conversation
  → reconnaître l'intention et les preuves nécessaires
  → router vers un Agent, plusieurs Agents, une demande d'information ou une escalade
  → rechercher des connaissances ou appeler un outil autorisé si nécessaire
  → générer et fusionner les réponses
  → sauvegarder le tour final visible par l'utilisateur et retourner ChatResponse
```

Le code principal est dans `api/`, `core/`, `agents/`, `memory/`, `knowledge/`, `tools/` et `harness/`. Une fois le service démarré, FastAPI expose la documentation interactive à `/docs`.

## Démarrage rapide

Arclume nécessite une API de modèle Chat, Redis, ChromaDB et l'API Arclume. L'interface web est optionnelle. Les secrets d'exécution doivent rester dans un fichier local `.env` à la racine du dépôt. Ne publiez pas `.env`, même après avoir retiré les valeurs personnelles ; le dépôt contient seulement `.env.example` avec des valeurs factices.

Copiez le modèle, puis modifiez `.env` avec votre fournisseur et votre clé API :

```bash
cp .env.example .env
```

Vérifiez au minimum ces valeurs :

```dotenv
LLM_API_KEY=your-api-key
LLM_BASE_URL=https://your-provider.example/v1
LLM_MODEL=your-chat-model
REDIS_PASSWORD=arclume123
ARCLUME_INTENT_LLM_ENABLED=false
ARCLUME_RAG_LLM_ENABLED=false
ARCLUME_MEMORY_LLM_ENABLED=false
```

Ces trois options désactivent les appels LLM supplémentaires pour la révision d'intention, la réécriture/réorganisation RAG et l'extraction de mémoire. Une réponse normale d'Agent appelle toujours le modèle Chat configuré. Ne publiez jamais une vraie clé API.

### Avec Docker Compose

Après avoir démarré Docker Desktop, lancez depuis la racine :

```bash
docker compose up -d --build api
docker compose ps
```

Compose démarre Redis et ChromaDB avant l'API. En cas de problème :

```bash
docker compose logs api
```

### Sans Docker

Installez les dépendances Python et démarrez Redis localement :

```bash
python3.10 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
brew install redis  # macOS, si nécessaire
redis-server --port 6379 --requirepass arclume123 --save '' --appendonly no
```

Ajoutez ensuite à `.env` :

```dotenv
REDIS_URL=redis://:arclume123@127.0.0.1:6379/0
CHROMA_HOST=127.0.0.1
CHROMA_PORT=8001
CHROMA_ALLOW_LOCAL_FALLBACK=true
CHROMA_PERSIST_DIRECTORY=./data/chroma
```

Puis démarrez l'API dans un autre terminal :

```bash
source .venv/bin/activate
python -m uvicorn api.main:app --host 127.0.0.1 --port 8000
```

Sans serveur ChromaDB disponible, l'API utilise le mode local persistant dans `data/chroma/`. Si la collection de connaissances est vide, le démarrage importe `data/demo_docs/`, crée les chunks et embeddings, écrit dans ChromaDB, puis construit l'index BM25.

## Vérifier le service

```bash
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/knowledge/stats
curl -X POST http://127.0.0.1:8000/chat \
  -H 'Content-Type: application/json' \
  -d '{"message":"What is the refund policy?","user_id":"demo-user"}'
```

Réutilisez le `conversation_id` retourné pour la suite de la conversation. Utilisez le `request_id` pour lire la Trace :

```bash
curl http://127.0.0.1:8000/traces/your-request-id
```

Ouvrez [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs) pour toutes les API. Pour l'interface web :

```bash
cd frontend
npm ci
npm run dev
```

Puis ouvrez `http://127.0.0.1:5173`.

## Vérification et limites

Ces commandes n'appellent pas de modèle Chat :

```bash
python -m unittest discover -s tests -q
python -m evaluation --smoke
python -m evaluation
```

Elles vérifient le comportement du code et l'intention/le routage sur un jeu de données anglais synthétique généré par LLM. Elles ne prouvent pas la qualité d'un vrai service client. Les outils de commande et de livraison utilisent des données de démonstration ; l'escalade ne contacte pas une équipe humaine ; le workflow complet d'approbation et de reprise d'une opération à risque n'est pas implémenté dans `/chat` ; les Traces sont en mémoire de processus ; l'authentification, la confidentialité et la gouvernance des données de production ne sont pas implémentées.

