# Arclume — Guide de structure du code et d’implémentation

Ce document présente la structure du backend Arclume, les principaux fichiers et classes, les relations entre les modules, ainsi que les endroits à consulter lorsque vous voulez modifier un comportement.

Il est recommandé de commencer par le chapitre 1 pour construire une carte générale du code. Le chapitre 2 permet ensuite de comprendre l’implémentation de chaque couche. Pour lancer le projet ou vérifier une modification, consultez les chapitres suivants.

Pour comprendre pourquoi le système a été conçu de cette manière et suivre le parcours complet d’une requête, voir `project_design_and_request_flow_fr.md`.

Ce document correspond au code actuellement présent dans le workspace.

Les comportements liés aux modèles externes, à Redis et à ChromaDB doivent être vérifiés dans un environnement réel. Le fait que les unit tests passent ne signifie pas automatiquement que les services réels fonctionnent correctement.

Le projet traite actuellement principalement des messages de service client en anglais et des documents de Knowledge Base en anglais.

## 1. Carte du repository : dossiers, fichiers et relations

On peut d’abord voir le repository comme plusieurs parties avec des responsabilités différentes.

`api/` reçoit les requêtes.

`core/` analyse la demande et prépare les données envoyées au modèle.

`agents/` décide quel Agent doit traiter la demande et produit la réponse.

`memory/` et `knowledge/` fournissent différentes sources de données.

`tools/` définit les capacités disponibles, tandis que `harness/` contrôle comment ces capacités peuvent être utilisées.

`schemas/` définit les structures de données utilisées entre les différentes couches.

`monitor/` est utilisé pour l’observability pendant l’exécution, et `evaluation/` pour l’évaluation offline.

Le chapitre 2 expliquera plus en détail pourquoi ces modules sont organisés de cette manière.

### 1.1 Structure générale

```text
arclume/
├── api/                 Routes HTTP, démarrage et assemblage des ressources
├── agents/              Routing, Agents spécialisés et fusion des réponses
├── core/                Intent recognition, client LLM, assemblage du Context et des Skills
├── schemas/             Contrats de données pour API, State, Context et Tools
├── memory/              Working memory Redis et Long-Term Memory ChromaDB
├── knowledge/           Découpage des documents, retrieval vectoriel et BM25
├── tools/               Fonctions des Tools, registration et gestion du retrieval
├── harness/             Permissions des Tools, exécution, approbation et Trace
├── skills/              Fichiers d’instructions métier maintenus manuellement
├── monitor/             Métriques, alertes et ajustement limité du routing
├── frontend/            Interface web Vue/Vite pour le chat (optionnelle)
├── evaluation/          Cas de test, métriques, rapports et quality regression
├── tests/               Tests de modules sans dépendance aux vrais services externes
├── data/demo_docs/      Documents anglais de démonstration
├── docs/                Documentation d’apprentissage, design, code et évaluation
├── config/              Configuration Nginx et Prometheus
├── requirements.txt     Dépendances Python
├── docker-compose.yml   Services locaux
└── Dockerfile           Build du conteneur API
```

La plupart des fichiers `__init__.py` servent seulement à déclarer un package ou à exporter certaines exceptions. Ils ne sont généralement pas importants pour comprendre le main flow.

`memory/__init__.py` et `knowledge/__init__.py` définissent également certains types d’erreurs propres à ces modules.

Ce document décrit uniquement l’implémentation actuellement utilisée par `api/main.py`. Les versions prévues ou expérimentales basées sur LangChain ou LangGraph ne font pas partie du main flow présenté ici.

### 1.2 Détail par dossier : rôle des fichiers principaux

L’arborescence suivante montre les fichiers que vous ouvrirez le plus souvent pour exécuter, lire ou modifier le projet.

La plupart des fichiers `__init__.py`, les lock files du frontend, les dossiers de cache et les données générées pendant l’exécution ne sont pas affichés. Ils ne sont généralement pas nécessaires pour comprendre le main flow.

```text
api/
└── main.py                    Crée les composants partagés et définit /chat et les interfaces de gestion

agents/
├── agent_orchestrator.py      Route selon IntentResult, exécute en parallèle, fusionne et écrit la réponse finale
├── agent_profile.py           Définit les responsabilités, workflows, limites et Tools de chaque type d’Agent
├── customer_service_agent.py  Exécuteur commun pour General/Technical/Billing : Context, modèle et Tools
├── general_agent.py           Configuration de rôle pour les demandes générales, produits, commandes et logistique
├── technical_agent.py         Configuration de rôle pour les problèmes techniques
├── billing_agent.py           Configuration de rôle pour remboursements, factures et paiements
├── escalation_agent.py        Traitement déterministe et message lors d’une escalation humaine
└── response_composer.py       Fusionne les réponses multi-Agent selon la priorité, sans rappeler le modèle

core/
├── intent_recognizer.py       Keywords, templates, vérification LLM optionnelle, entities et subtasks
├── context_builder.py         Organise historique, connaissances, Skills, State et résultats des Tools pour le modèle
├── skill_loader.py            Lit les SKILL.md, sélectionne et rend les instructions métier selon Agent/Intent
└── llm_utils.py               Client compatible OpenAI, génération normale et parsing des Tool Calls

schemas/
├── api.py                     Modèles de données HTTP comme ChatRequest et ChatResponse
├── state.py                   AgentState et enum des statuts
├── context.py                 Structures du Context utilisées pour un appel modèle
└── tool.py                    Contrats ToolCall, ToolResult et autres données liées aux Tools

memory/
├── conversation_memory.py     Messages récents Redis, résumé de conversation, compression et écriture finale
├── long_term_memory.py        Lecture/écriture des résumés historiques et profils utilisateur dans ChromaDB
└── state_store.py             Stockage de AgentState dans Redis par utilisateur et conversation

knowledge/
├── knowledge_base.py          Import de documents anglais, découpage par paragraphes et Dense retrieval avec ChromaDB
├── bm25_index.py              Index BM25 en mémoire du processus
└── hybrid_retriever.py        Dense/BM25 en parallèle, RRF, déduplication et fallback

tools/
├── tool_functions.py          Fonctions concrètes : knowledge_search, Mock commandes/logistique, etc.
└── tool_manager.py            Couche d’exécution avancée : Query Rewriting, cache, circuit breaker, ranking et fallback

harness/
├── policy.py                  Décide allow/deny/approval selon Tool, Agent, statut et niveau de risque
├── executor.py                Valide les paramètres, gère timeout/retry et standardise ToolResult
├── runtime.py                 Point d’entrée commun reliant Policy, Executor, ToolManager et Trace
└── trace.py                   Définit les événements Trace et stocke les records en mémoire selon request_id

monitor/
└── performance_monitor.py     Agrège succès/latence des Agents et Tools, alertes et métriques Prometheus

evaluation/
├── __main__.py                Entrée CLI pour `python -m evaluation`
├── models.py                  Structures pour les cas de test et rapports d’évaluation
├── runner.py                  Exécute les évaluations locales Intent/routing
├── metrics.py                 Calcule Accuracy, Macro-F1 et métriques de retrieval
├── evaluator.py               Lance l’évaluation end-to-end via l’API
├── judge.py                   Logique optionnelle LLM-as-a-Judge
├── regression.py              Compare les anciens et nouveaux rapports
└── data/                      Smoke tests, 500 exemples synthétiques Intent/routing et cas RAG de démonstration

skills/
├── refund/SKILL.md            Instructions métier pour remboursements et paiements
├── technical/SKILL.md         Instructions de diagnostic technique
├── logistics/SKILL.md         Instructions pour les scénarios logistiques
└── escalation/SKILL.md        Instructions pour les escalations humaines

frontend/
├── src/App.vue                Page de chat, état de santé et affichage basique des Traces
├── src/api.js                 Wrapper des appels HTTP vers le backend
├── src/main.js                Point d’entrée de l’application Vue
├── src/style.css              Styles de l’interface
├── package.json               Dépendances frontend et scripts npm
└── vite.config.js             Configuration Vite pour développement et build

data/demo_docs/                Documents anglais de démonstration pouvant être importés
tests/                         Unit/integration tests ; les fichiers de test montrent le comportement attendu
config/prometheus.yml          Configuration du scraping des métriques API par Prometheus
config/nginx/nginx.conf        Exemple de configuration Nginx reverse proxy
docs/                          Documentation du projet dans `zh/`, `eng/` et `fr/`
```

Pour lire le code, vous pouvez commencer par `api/main.py`.

Quand vous rencontrez un objet appartenant à une autre couche, utilisez ensuite le dossier correspondant dans l’arborescence ci-dessus.

Par exemple, si vous voulez modifier la manière dont l’Intent est reconnu, commencez directement par `core/intent_recognizer.py`.

Regardez ensuite les tests correspondants dans `tests/` ainsi que les données de regression dans `evaluation/`.

Il n’est pas recommandé de commencer par modifier le Prompt d’un Agent.

### 1.3 Ce que contiennent les principaux fichiers

La section suivante présente les fichiers et symboles les plus importants pour comprendre le main flow.

Il s’agit d’un **index de navigation**, et non d’une copie complète de chaque fonction privée. Une telle copie deviendrait rapidement obsolète lorsque le code change.

#### 1.3.1 `api/` et `schemas/` : frontières externes et types de données partagés

| Fichier | Contenu | Quand l’ouvrir |
|---|---|---|
| `api/main.py` | `lifespan()` assemble les composants partagés ; `chat()` traite `/chat` ; les routes health, Knowledge Base, Skill, Trace, Monitor et evaluation sont également définies ici | Ajouter une API, vérifier les dépendances au démarrage ou suivre le chemin HTTP jusqu’à l’Orchestrator |
| `schemas/api.py` | `ChatRequest` / `ChatResponse`, ainsi que les modèles Pydantic pour l’import de connaissances et l’évaluation | Modifier les champs d’une requête/réponse ou comprendre les contraintes de l’API |
| `schemas/state.py` | Enum `AgentStatus` et `AgentState` : Intent, entities, Agents actifs, état d’escalation, version, etc. | Modifier l’état métier conservé entre plusieurs requêtes |
| `schemas/context.py` | `ContextMessage` et `Context` pour l’appel courant du modèle ; contient historique, résumé, connaissances, Skill, résultats des Tools et metadata | Comprendre quelles informations structurées le modèle peut réellement recevoir |
| `schemas/tool.py` | `ToolCall` avec nom du Tool, paramètres et origine ; `ToolResult` avec succès, erreur, approval, cache, fallback, etc. | Modifier le contrat des Tools ou les champs du Trace |

`ChatRequest` et `ChatResponse` correspondent au contrat HTTP.

`AgentState` représente un état métier qui peut être conservé entre plusieurs requêtes.

`Context` représente les informations temporaires fournies au modèle pour une exécution donnée.

`ToolCall` et `ToolResult` définissent le contrat d’exécution des Tools.

Ces objets peuvent tous contenir des notions de “state” ou de “result”, mais leur cycle de vie est très différent.

Pour connaître les champs exacts, il faut toujours se référer aux définitions Pydantic correspondantes.

#### 1.3.2 `core/` : comprendre la requête et préparer l’appel au modèle

| Fichier | Classes / fonctions principales | Responsabilité |
|---|---|---|
| `core/intent_recognizer.py` | `IntentCategory`, `IntentSubtask`, `IntentResult`, `IntentRecognizer.recognize()` ; `_pattern_evidence()`, `_template_match()`, `_ambiguity_reasons()`, `_build_subtasks()`, `_information_need()`, `_planned_tool()` | À partir du message et de l’historique, identifie le sujet métier, les ambiguïtés, les entities, les subtasks d’une requête complexe, les besoins en evidence et le plan éventuel de Tools. N’exécute ni Agent ni Tool. |
| `core/llm_utils.py` | `LLMSettings`, `LLMClient.chat()`, `chat_with_tools()`, `LLMToolResponse` | Lit de manière unifiée la configuration du fournisseur et appelle une API Chat Completions compatible OpenAI. Parse le texte normal, les Tool Calls et les champs spécifiques du fournisseur qui doivent être renvoyés tels quels au tour suivant. |
| `core/context_builder.py` | `ContextBuilder.build()`, `render_system_prompt()`, `render_history()` | Organise les éléments déjà récupérés : Memory, connaissances, Skill et State, puis les transforme en messages pour le modèle. N’accède pas directement aux bases de données. |
| `core/skill_loader.py` | `SkillDocument`, `SkillLoader.select_for_agent()`, `render()`, `reload()` | Parse les Skills maintenus manuellement. Pour les candidats déjà sélectionnés selon l’Intent, vérifie seulement leur activation et leur compatibilité avec l’Agent. Lors d’un appel direct, peut également découvrir un Skill avec des keywords du message. Rend ensuite le texte des règles métier. |

Les principaux champs du résultat de reconnaissance peuvent être lus en quatre groupes.

`intent`, `intent_group` et `confidence` répondent à la question : **« quel est le problème principal ? »**

`topic_evidence`, `ambiguity_reasons` et `supporting_domains` expliquent : **« pourquoi le système a fait ce choix et existe-t-il d’autres sujets indépendants ? »**

`subtasks` indique **quel Agent doit traiter quelle partie du message original**.

`information_need`, `should_use_rag` et `planned_tool_name` répondent à la question : **« quelles evidence sont nécessaires avant de répondre à la requête complète ? »**

Lors d’une exécution multi-Agent, il faut également regarder les besoins en evidence de chaque `IntentSubtask`. Il ne faut pas se baser uniquement sur les champs au niveau global de la requête.

#### 1.3.3 `agents/` : qui traite la demande et comment la réponse est produite

| Fichier | Classes / fonctions principales | Responsabilité |
|---|---|---|
| `agents/agent_orchestrator.py` | `AgentType`, `RoutingDecision`, `AgentResponse`, `OrchestratorResult`, `AgentOrchestrator.run()`, `_make_decision()`, `_run_parallel()`, `_persist_final_turn()` | Routing, demande d’informations supplémentaires à l’utilisateur, exécution multi-Agent en parallèle, fallback, fusion des résultats, décision d’escalation et écriture finale de la conversation. |
| `agents/agent_profile.py` | `AgentProfile` | Définit les missions d’un rôle, son workflow, ses contraintes d’entrée/sortie, les conditions d’escalation et son `tool_scope`. |
| `agents/customer_service_agent.py` | `CustomerServiceAgent.respond()`, `_tool_schemas()`, `_run_tool_loop()`, `_record_tool_result()` | Exécuteur partagé par les Agents métier classiques : précharge les evidence, sélectionne le Skill, construit le Context, appelle le modèle et le Harness, puis met à jour `AgentState`. |
| `agents/general_agent.py` | `GeneralAgent` | Traite les questions générales, commandes, logistique et fallback. Les éléments principaux sont son Profile, son périmètre de Tools et son system prompt. |
| `agents/technical_agent.py` | `TechnicalAgent` | Traite les problèmes techniques et de connexion. Réutilise l’exécuteur partagé au lieu de dupliquer toute la Tool Loop. |
| `agents/billing_agent.py` | `BillingAgent` | Traite les remboursements, factures et paiements. Ses limites sont définies par son Profile et son prompt. |
| `agents/escalation_agent.py` | `EscalationAgent.respond()` | Produit une réponse déterministe pour l’escalation humaine et met à jour l’état correspondant. N’utilise pas le flow de génération des Agents métier classiques. |
| `agents/response_composer.py` | `ResponseComposer.compose()` | Fusionne les réponses réussies du primary Agent et des supporting Agents en donnant la priorité à la réponse principale. Ne rappelle pas le modèle. |

`AgentOrchestrator.run()` est le point d’entrée de l’orchestration.

`CustomerServiceAgent.respond()` est le point d’entrée pour l’exécution d’un Agent métier classique.

`AgentResponse` représente le résultat interne d’un seul Agent.

`OrchestratorResult` représente le résultat interne après la fin de l’orchestration, avant son retour à la couche HTTP.

Ces structures ne sont pas des `ChatResponse`.

Pour comprendre pourquoi un champ apparaît dans l’API, il faut généralement suivre la chaîne entre `AgentResponse`, `OrchestratorResult` et `ChatResponse`.

#### 1.3.4 `memory/` et `knowledge/` : deux sources de données différentes

| Fichier | Classes / fonctions principales | Responsabilité |
|---|---|---|
| `memory/conversation_memory.py` | `ConversationMemory.get_context()`, `add_message()`, `_maybe_compact()`, `update_profile()` | Gère les messages récents et les résumés dans Redis. Si nécessaire, récupère également des informations pertinentes dans la Long-Term Memory et le profil utilisateur. |
| `memory/state_store.py` | `StateStore.get_or_create()`, `save()` | Stocke le `AgentState` structuré dans Redis, avec isolation par utilisateur et conversation. |
| `memory/long_term_memory.py` | `LongTermMemory.search_episodic()`, `add_episodic_summary()`, `get_user_profile()`, `update_user_profile()` | Stocke dans ChromaDB les résumés historiques et profils utilisateur. Ne stocke pas les chunks de Knowledge Base métier. |
| `knowledge/knowledge_base.py` | `KnowledgeBase.add_documents()`, `search()`, `_chunk_text()`, `_chunk_id()` | Découpe les documents métier anglais, les stocke dans une collection ChromaDB dédiée et effectue le Dense retrieval. |
| `knowledge/bm25_index.py` | `BM25Index.replace()`, `upsert()`, `search()` | Maintient un index lexical en mémoire du processus et calcule les scores BM25. |
| `knowledge/hybrid_retriever.py` | `HybridRetriever.search_async()`, `refresh_async()`, `_rrf_fuse()` | Récupère des candidats via Dense retrieval et BM25, fusionne les résultats, déduplique et tente un fallback si une branche échoue. |

ChromaDB est utilisé à la fois par `LongTermMemory` et `KnowledgeBase`, mais avec des collections différentes.

`LongTermMemory` stocke l’historique utilisateur et les profils.

`KnowledgeBase` stocke les documents métier utilisés pour le RAG.

Le fait que les deux utilisent ChromaDB ne signifie donc pas que la mémoire utilisateur fait partie de la Knowledge Base du RAG.

#### 1.3.5 `tools/` et `harness/` : séparer les capacités de leur gouvernance

| Fichier | Classes / fonctions principales | Responsabilité |
|---|---|---|
| `tools/tool_functions.py` | `knowledge_search()`, `order_query()`, `logistics_query()`, `lookup_error_code()`, `register_tools()`, etc. | Définit le comportement concret des Tools et leur registration. Les données de commande et logistique sont des données de démonstration. `ticket_create` n’est pas connecté à un vrai système de ticketing. |
| `tools/tool_manager.py` | `ToolManager.execute()`, `search_with_rewrite()`, `rewrite_query()`, `rerank()` | Gère cache, circuit breaker, statistiques et fallback des Tools. Pour le RAG, gère aussi Query Rewriting, déduplication et ranking final. |
| `harness/policy.py` | `ToolPolicy.evaluate()`, `PolicyAction`, `ToolRiskLevel` | Décide si un `ToolCall` est autorisé, refusé ou nécessite une approval. N’exécute pas le Tool. |
| `harness/executor.py` | `ToolDefinition`, `ToolExecutor.execute()`, `_validate_arguments()` | Définit les entrées et la configuration de risque d’un Tool, valide les arguments, gère timeout/retry et standardise le résultat. |
| `harness/runtime.py` | `HarnessRuntime.handle_tool_call()`, `tool_schemas()`, `tool_trace()` | Relie Policy, Executor/ToolManager, périmètre de l’Agent et Trace pour produire un appel Tool contrôlé. |
| `harness/trace.py` | `TraceEventType`, `TraceEvent`, `TraceRecorder` | Conserve en mémoire les événements d’une requête avec une capacité limitée. Les événements peuvent être retrouvés par `request_id`. |

`tools/` répond à la question : **« que fait concrètement cette capacité ? »**

`harness/` répond plutôt aux questions : **« cette capacité peut-elle être utilisée dans ce cas ? Comment doit-elle être exécutée ? Quelles traces faut-il conserver ? »**

`ToolManager` hérite en pratique de `ToolExecutor`.

Il participe donc à l’exécution des Tools, mais gère aussi une partie importante de la chaîne de retrieval.

C’est pour cette raison que `api/main.py` enregistre d’abord les Tools dans `ToolManager`, puis transmet ce composant à `HarnessRuntime`.

#### 1.3.6 Exécution, évaluation et fichiers de ressources

| Dossier / fichier | Contenu | Relation avec le main flow |
|---|---|---|
| `skills/*/SKILL.md` | Règles de scénario maintenues manuellement pour refund, technical, logistics et escalation | Pour `/chat`, les candidats sont d’abord sélectionnés selon l’Intent précis. `SkillLoader` vérifie ensuite leur activation et leur périmètre Agent avant de les injecter. Ce ne sont pas des fichiers Python exécutables. |
| `monitor/performance_monitor.py` | `PerformanceMonitor`, détection d’alertes/anomalies, sortie des métriques et ajustement limité du routing | Lit périodiquement les statistiques des Agents et Tools en arrière-plan. Ne remplace pas l’évaluation offline de la qualité. |
| `evaluation/__main__.py` | Entrée CLI de `python -m evaluation` | Lance l’évaluation locale des Intents et du routing déterministe. Ne démarre pas le chat complet. |
| `evaluation/models.py`, `metrics.py`, `runner.py` | Modèles des cas et rapports, métriques de classification/retrieval et exécution des cas | Constituent la base d’une évaluation locale reproductible. |
| `evaluation/evaluator.py`, `judge.py`, `regression.py` | Évaluation end-to-end via API, LLM Judge optionnel et comparaison des rapports | Il faut distinguer les vrais appels modèle des résultats placeholder ou des résultats produits après un échec. |
| `evaluation/data/` | `cases.json` pour les smoke tests, `intent_cases_500.json` pour les 500 exemples synthétiques de classification générés par LLM, `rag_cases.json` pour les cas de retrieval de démonstration | Après une modification de l’Intent recognition ou du chunking, il faut également vérifier les données et leurs labels. |
| `tests/` | Tests du comportement des principaux modules, principalement avec des mocks ou autres test doubles | Utilisés pour la regression lors des modifications du code. Ils ne remplacent pas les tests avec les vraies dépendances externes. |
| `data/demo_docs/` | Documents anglais de démonstration sur refund, logistics, security et technical support | Peuvent servir à construire une petite Knowledge Base de démonstration, mais ne représentent pas des politiques métier officielles. |
| `frontend/src/App.vue`, `api.js`, `main.js`, `style.css` | `App.vue` organise l’interface de chat et l’affichage des états principaux ; `api.js` encapsule les requêtes vers `/chat`, `/health`, `/monitor`, etc. ; `main.js` démarre Vue ; `style.css` définit le style de la page | Interface locale de démonstration optionnelle. Elle ne participe pas aux décisions métier du backend. Le frontend actuel indique seulement si le Monitor est actif. Les métriques complètes doivent être consultées via `/monitor`, `/metrics` ou Prometheus. |
| `frontend/package.json`, `vite.config.js`, `index.html` | Dépendances frontend, configuration Vite pour développement/build et point d’entrée de la page | À consulter pour modifier les commandes de démarrage du frontend, le proxy ou le processus de build. |
| `docs/zh/`, `docs/eng/`, `docs/fr/` | `zh/` contient actuellement la documentation chinoise d’apprentissage et de design la plus complète. `eng/` et `fr/` contiennent les versions anglaise et française destinées à la présentation | La documentation ne participe pas à l’exécution. La présentation générale du projet, le design flow, la navigation dans le code, le protocole d’évaluation, le PRD et la roadmap doivent rester cohérents entre les trois langues. |
| `config/`, `Dockerfile`, `docker-compose.yml` | Nginx, Prometheus, exécution des conteneurs et infrastructure locale | À vérifier lors d’une modification des ports, mots de passe, variables d’environnement ou du déploiement. |

### 1.4 Partir d’une requête `/chat` pour retrouver les fichiers concernés

Le tableau suivant présente un **ordre de lecture du code**. Il ne représente pas les étapes obligatoires suivies par chaque requête pendant l’exécution.

Si vous voulez savoir dans quelle couche un comportement est implémenté, vous pouvez commencer par suivre cette liste :

| Point à examiner | Emplacement principal | Entrée ou méthode clé | Responsabilité de la couche |
|---|---|---|---|
| Validation de la requête, création des dépendances et réponse externe | `schemas/api.py`, `api/main.py` | `ChatRequest`, `ChatResponse`, `lifespan()`, `chat()` | Contrat HTTP et assemblage des composants. Les règles d’Intent ne doivent pas être écrites ici. |
| Sujet, entities et besoin en evidence | `core/intent_recognizer.py` | `IntentRecognizer.recognize()` | Produit `IntentResult`. N’exécute aucun Tool. |
| Routing, multi-Agent et écriture finale | `agents/agent_orchestrator.py` | `run()`, `_make_decision()`, `_persist_final_turn()` | Décide qui doit traiter la demande et organise le résultat final envoyé vers l’extérieur. |
| Exécution réelle d’un Agent | `agents/customer_service_agent.py` | `respond()`, `_run_tool_loop()` | Précharge les evidence, construit le Context, appelle le modèle et les Tools, puis maintient `AgentState`. |
| Rôle, Skill et Context du modèle | `agents/agent_profile.py`, `core/skill_loader.py`, `core/context_builder.py` | `AgentProfile`, `select_for_agent()`, `build()`, `render_history()` | Définit les responsabilités et prépare les informations visibles par le modèle. |
| Import et retrieval des connaissances | `knowledge/`, `tools/tool_manager.py` | `add_documents()`, `search_with_rewrite()` | Chunking, Dense/BM25 retrieval, fusion, déduplication et Reranking. |
| Approbation et exécution des Tools | `harness/`, `tools/tool_functions.py` | `handle_tool_call()`, `evaluate()`, `execute()` | Permissions et risques, validation des paramètres, exécution et Trace. |
| Conversation, Long-Term Memory et State | `memory/`, `schemas/state.py` | `get_context()`, `add_message()`, `get_or_create()` | Enregistre et récupère les données utilisées entre plusieurs requêtes. |

Il existe plusieurs frontières faciles à confondre.

`IntentResult.should_use_rag` signifie que le système **prévoit d’avoir besoin de connaissances**. Cela ne signifie pas que le retrieval a déjà réussi.

`RoutingDecision` est une décision de routing interne. Ce n’est pas une réponse API.

`Context` contient les informations fournies au modèle pour le tour actuel. Ce n’est pas une mémoire persistante.

`ToolResult` représente le résultat d’une tentative d’exécution d’un Tool.

Il ne faut donc pas utiliser uniquement `tools_used` pour représenter l’historique complet des Tools, car cette liste ne suffit pas pour montrer les appels qui ont échoué.

### 1.5 Comment les données principales circulent entre les couches

```text
ChatRequest
  → api.chat() lit la Memory et récupère history + memory_context
  → IntentRecognizer.recognize() produit IntentResult
      → pour une requête complexe, produit aussi des IntentSubtask par domaine
  → AgentOrchestrator._make_decision() produit RoutingDecision
  → l’Orchestrator transmet chaque sous-problème au CustomerServiceAgent.respond() correspondant
  → chaque Agent effectue son propre retrieval, génère sa réponse et enregistre ses appels de Tools
  → ResponseComposer (uniquement en multi-Agent) construit le texte final
  → OrchestratorResult
  → api.chat() le transforme en ChatResponse
```

`request_id` identifie **une requête unique**. Il est principalement utilisé pour le Trace.

`conversation_id` identifie **une conversation multi-tour**. Il est utilisé par la Memory.

Si le client ne fournit pas de `conversation_id`, l’API en génère un et le retourne dans la réponse. Pour continuer la même conversation, le client doit ensuite réutiliser ce même identifiant.

`user_id` sert à isoler les données entre utilisateurs. Quand il n’est pas fourni, le projet utilise une valeur par défaut destinée à la démonstration. Dans un vrai système métier, cette valeur anonyme par défaut ne doit pas être utilisée pour l’isolation entre tenants ou utilisateurs.

Les objets suivants sont ceux que l’on rencontre le plus souvent lors du debugging :

| Objet (fichier de définition) | Champs à regarder en priorité | Qui le crée et qui l’utilise |
|---|---|---|
| `ChatRequest` (`schemas/api.py`) | `message`, `user_id`, `conversation_id` | Le client l’envoie à FastAPI ; `api.chat()` le lit. |
| `IntentResult` (`core/intent_recognizer.py`) | `intent`, `entities`, `confidence`, `information_need`, `should_use_rag`, `planned_tool_name`, `supporting_domains`, `subtasks` | Créé par le Recognizer ; utilisé par l’Orchestrator pour le routing puis transmis aux Agents. |
| `IntentSubtask` (`core/intent_recognizer.py`) | `domain`, `query`, `intent`, `information_need`, `should_use_rag`, `planned_tool_name`, `entities` | Créé par le Recognizer pour les requêtes complexes ; l’Orchestrator retrouve la subtask correspondant à chaque domaine et transmet seulement sa `query` à l’Agent concerné. |
| `RoutingDecision` (`agents/agent_orchestrator.py`) | `primary_agent`, `supporting_agents`, `use_rag`, `reason` | Créé par `_make_decision()` ; utilisé par `run()` pour choisir le chemin d’exécution. |
| `AgentState` (`schemas/state.py`) | `status`, `active_agent`, `needs_rag`, `needs_human`, `pending_approval`, `version` | Lu et mis à jour par les Agents ; sauvegardé par `StateStore`. L’existence d’un champ ne signifie pas que tout le workflow correspondant est déjà implémenté, par exemple la reprise après approval. |
| `Context` (`schemas/context.py`) | `conversation_history`, `memory_summary`, `knowledge_results`, `skill_instructions`, `metadata` | Créé par `ContextBuilder.build()` ; rendu par l’Agent pour le modèle. L’objet complet n’est pas sauvegardé tel quel. |
| `ToolCall` / `ToolResult` (`schemas/tool.py`) | `tool_name`, `arguments` / `success`, `data`, `error`, `requires_approval` | L’Agent ou le Harness initie le ToolCall ; le Harness/Executor retourne le résultat d’exécution. |
| `OrchestratorResult` (`agents/agent_orchestrator.py`) | `response`, informations de routing, escalation, `tools_used`, `tool_traces` | Produit par l’Orchestrator ; `api.chat()` le transforme en `ChatResponse` externe. |

Ce tableau présente uniquement les champs les plus utiles pour le debugging. Il ne contient pas forcément tous les champs disponibles.

Pour vérifier les valeurs par défaut, les types ou les nouveaux champs, il faut ouvrir directement la classe correspondante.

Pour savoir **à quel moment un champ reçoit sa valeur**, il faut ensuite rechercher les endroits où l’objet est créé ou mis à jour.

### 1.6 Comment les dossiers travaillent ensemble : trois chaînes différentes

**Chaîne d’assemblage au démarrage** : `api/main.py:lifespan()` crée d’abord la Memory, la `KnowledgeBase`, le `ToolManager`, le Harness, les Agents et l’Orchestrator.

Ces objets sont donc des dépendances partagées. Ils ne sont pas recréés pour chaque requête.

Pour comprendre **d’où vient un composant** ou **à quel moment une configuration est appliquée**, il faut partir de `lifespan()` et suivre les objets créés.

**Chaîne d’exécution d’une conversation** : `api.chat()` commence par appeler `ConversationMemory.get_context()` pour récupérer le contexte de conversation.

Il transmet ensuite les données à `AgentOrchestrator.run()`.

L’Orchestrator appelle `IntentRecognizer.recognize()`, crée une décision de routing et lance les Agents de domaine nécessaires.

Un Agent classique utilise ensuite `ContextBuilder` et `LLMClient` pour produire sa réponse. Si nécessaire, il utilise des Tools via le Harness.

Une fois les résultats obtenus, l’Orchestrator les combine, écrit le résultat final dans la conversation, puis l’API retourne un `ChatResponse`.

Pour comprendre **qui appelle qui**, il faut suivre cette chaîne.

**Chaîne Knowledge et Tools** : les documents entrent d’abord dans `KnowledgeBase` via `/knowledge/add`, puis l’index BM25 est rafraîchi.

Pendant une conversation, `IntentResult` peut indiquer qu’une preuve externe est nécessaire.

L’Agent passe alors par `HarnessRuntime.handle_tool_call()` pour appeler le `ToolManager`.

Le `ToolManager` utilise ensuite `HybridRetriever`, `KnowledgeBase` et `BM25Index`.

Les passages trouvés sont finalement renvoyés à l’Agent et intégrés dans son Context.

Si vous voulez comprendre **pourquoi le retrieval n’a pas été lancé ou pourquoi il a retourné un mauvais résultat**, il vaut mieux suivre cette chaîne étape par étape plutôt que d’essayer de deviner à partir de la réponse finale.

La direction générale des dépendances peut être simplifiée ainsi :

```text
api ──→ orchestrator ──→ intent recognizer
 │             │
 │             └──→ domain Agent ──→ ContextBuilder ──→ LLMClient
 │                       │
 ├──→ memory/             ├──→ SkillLoader
 │                       └──→ Harness ──→ ToolManager ──→ knowledge/
 └──→ response schema                         │
                                             └──→ tools/tool_functions.py

schemas/ fournit les structures de données validées utilisées entre les couches.
Trace et Monitor observent l’exécution.
Evaluation mesure séparément la qualité.
```

### 1.7 Comment chercher un champ ou une méthode quand on ne sait pas où il se trouve

La documentation donne des points d’entrée, mais **les définitions de types, les call sites et les tests sont les sources de vérité du code actuel**.

La méthode la plus simple est généralement :

1. chercher d’abord où le champ ou la méthode est déclaré ;
2. chercher ensuite où il est utilisé ;
3. regarder enfin les tests correspondants.

Par exemple, pour suivre `planned_tool_name` :

```bash
rg -n 'planned_tool_name' core agents schemas tests
rg -n 'class (IntentResult|RoutingDecision|ChatResponse)' core agents schemas
rg -n 'async def respond|async def handle_tool_call|def _persist_final_turn' agents harness
```

En général, on trouve d’abord dans `IntentResult` l’endroit où le champ est créé.

On peut ensuite voir dans l’Orchestrator comment il est transmis à l’Agent.

Enfin, on vérifie dans l’Agent si ce champ déclenche réellement l’appel d’un Tool.

Lire uniquement la déclaration du champ ne permet donc pas de savoir ce qui se passe réellement pendant l’exécution.

Si vous modifiez un champ, il faut aussi vérifier s’il traverse correctement la chaîne :

`IntentResult → RoutingDecision / Agent → OrchestratorResult → ChatResponse`

Il faut enfin vérifier que les tests correspondants couvrent bien ce comportement.

## 2. Design du code et limites de modification par couche

### 2.1 HTTP et cycle de vie de l’application

Dans `api/main.py`, `lifespan()` crée au démarrage du processus le `LLMClient`, les adaptateurs Redis/ChromaDB, la Knowledge Base, le `ToolManager`, le Harness, les Agents, l’Orchestrator, l’Evaluator et le Monitor, puis les attache à `app.state`. Ces objets sont réutilisés pendant le traitement des requêtes ; les connexions sont libérées lors de l’arrêt. Une erreur d’initialisation de la Long-Term Memory ou de la Knowledge Base peut être gérée avec un fallback, mais une vraie erreur de lecture ou d’écriture Redis doit provoquer une erreur sur `/chat` ; elle ne doit pas être silencieusement interprétée comme « aucun historique ».

`chat()` s’occupe uniquement de la couche transport : il parse `ChatRequest`, détermine le `conversation_id`, lit la Memory, appelle l’Orchestrator et transforme `OrchestratorResult` en `ChatResponse`. Il ne faut pas ajouter de nouvelles règles d’Intent, de permissions de Tools ou de Prompt directement dans les routes HTTP. Lorsqu’un champ externe est modifié, il faut vérifier en même temps `schemas/api.py`, `api/main.py`, les modèles de résultats internes et les tests. Les autres routes — Knowledge Base, Skills, Trace, Monitor et Evaluation — sont également définies dans `api/main.py`, mais elles ne font pas pour autant partie du main flow de `/chat`.

### 2.2 Intent recognition et routing

`IntentRecognizer.recognize()` reçoit le texte du tour actuel ainsi qu’un historique optionnel, puis retourne un `IntentResult` contenant l’Intent, la confidence, les entities structurées, les scores par domaine, les topic evidence détectées, les ambiguïtés, `information_need`, `planned_tool_name`, les domaines indépendants pouvant être supportés et les `subtasks`. Le code est principalement organisé autour de plusieurs étapes : `_pattern_evidence()` pour les indices basés sur des keywords locaux ; `_template_match()` pour la similarité en character n-gram avec des questions prédéfinies ; `_ambiguity_reasons()` pour détecter les ambiguïtés ; `_llm_match()` pour une vérification optionnelle par LLM ; `_build_subtasks()` pour découper une requête complexe ; puis la fusion finale, l’extraction des entities et la décision sur les besoins en information.

Lors des modifications, il ne faut pas confondre « ceci est une question » avec « à quel domaine métier cette question appartient ». Par exemple, `What is your refund policy?` peut correspondre à une structure de question générale, mais `refund` constitue une evidence métier plus précise ; c’est `information_need=knowledge` qui justifie ensuite le retrieval. `order_query` et `logistics_query` ne peuvent être planifiés comme Tools de prélecture en read-only que si les IDs correspondants sont disponibles. Après toute modification des keywords, templates ou thresholds, il faut vérifier les negative examples, les domaines proches et `tests/test_intent.py`, puis exécuter la regression locale sur les 500 cas. Actuellement, `_template_match()` n’utilise pas de Semantic Embedding ; sa capacité à gérer les paraphrases et expressions synonymes reste donc limitée.

`AgentOrchestrator._make_decision()` transforme `IntentResult` en `RoutingDecision`. Une demande claire de transfert humain ou une urgence grave est envoyée vers Escalation ; les autres cas utilisent le mapping d’Intent et les scores de domaine pour sélectionner le primary Agent. Le choix des supporting Agents ne dépend pas seulement de scores proches : il est également limité par les evidence de problèmes indépendants dans `supporting_domains`. Une fois dans la branche parallèle, `_task_for()` retrouve dans `subtasks` le sous-problème correspondant à chaque Agent, et `_run_parallel()` ne lui transmet que ce texte. Le Skill, la requête RAG, `information_need`, les entities et le plan éventuel de Tool read-only utilisent eux aussi les champs au niveau de la task. `task_scoped=True` ajoute également une limite explicite dans le Prompt : les autres sujets présents dans l’historique ou les anciennes réponses complètes ne doivent pas être traités à nouveau. `run()` gère aussi les demandes d’informations supplémentaires à l’utilisateur, les fallbacks en cas d’échec, la fusion des résultats et l’agrégation des signaux d’escalation. Si le routing est incorrect, il faut d’abord examiner les evidence et le résumé des tasks dans `intent_recognized`, puis `route_selected` ; il ne faut pas modifier directement le Prompt du primary Agent pour masquer une erreur de classification située en amont.

### 2.3 Agent, Profile, Skill et Context

General, Technical et Billing utilisent tous `CustomerServiceAgent.respond()`, mais chacun possède son propre `AgentProfile`, son rôle dans le Prompt et son périmètre de Tools. Le Profile correspond au contrat du rôle : missions, étapes de travail, contraintes d’entrée/sortie, conditions de transfert vers un humain et `tool_scope`. Un Skill est une instruction métier maintenue manuellement pour un scénario comme refund, technical ou logistics ; ce n’est pas un Tool exécutable.

Dans `/chat`, la sélection du Skill est d’abord effectuée par `AgentOrchestrator._skills_for()` : cette méthode retourne des candidats selon **l’Agent actuel et l’Intent précis au niveau de la task**. Par exemple, `refund` / `payment_issue` correspondent au Skill `refund`, tandis que les Intents techniques correspondent au Skill `technical`. Comme ce candidat représente déjà la décision de scénario prise en amont, `SkillLoader` vérifie seulement si le Skill est activé et si l’Agent actuel est autorisé à l’utiliser ; il n’exige pas que le texte de l’utilisateur corresponde une deuxième fois aux keywords du Skill. Si aucun candidat n’est proposé, aucun Skill n’est injecté. `invoice` et le domaine large `billing` n’ont actuellement pas de Skill correspondant et ne doivent donc pas réutiliser incorrectement le SOP de refund.

Les `keywords` présents dans les metadata du Skill sont toujours conservés pour permettre la découverte par mots-clés lorsqu’un Agent est appelé directement sans candidat fourni par l’Orchestrator ; ils pourront plus tard être complétés ou remplacés par une similarité basée sur Embedding. Après modification d’un fichier Skill, il est possible d’appeler `POST /skills/reload`. Le modèle ne modifie jamais lui-même les Skills.

L’ordre d’exécution d’un Agent de domaine est le suivant : lire la Memory et le `AgentState` nécessaires → si des connaissances sont requises, précharger `knowledge_search` via le Harness, et si un Tool read-only est déjà planifié et exécutable, le précharger également → sélectionner le Skill → utiliser `ContextBuilder.build()` pour assembler les informations du tour → appeler le modèle et, si nécessaire, entrer dans `_run_tool_loop()` → mettre à jour `AgentState` et les records d’exécution. Un Tool déjà préchargé n’est pas à nouveau exposé au modèle comme Tool disponible pendant ce tour ; les autres Tools doivent toujours respecter le périmètre défini dans le Profile et passer par le Harness.

`ContextBuilder` organise uniquement les contenus déjà chargés ; il ne se connecte pas directement à Redis, ChromaDB ou au modèle. Le modèle ne voit pas « tout ce qui existe dans la base de données » : il reçoit seulement les informations préparées pour ce tour, comme l’historique récent, le résumé, les passages récupérés, le Skill sélectionné, le State structuré et les evidence provenant des Tools. Lorsqu’une réponse est incorrecte, il faut d’abord vérifier si la bonne evidence est effectivement entrée dans le Context ; si l’information n’est jamais arrivée jusqu’au modèle, modifier uniquement le Prompt ne résout généralement pas la cause principale. Lorsque le modèle ne dispose pas de connaissances vérifiées ou de vraies données métier, le Prompt de l’Agent lui demande de ne pas présenter une supposition comme un fait certain ; cela ne constitue toutefois pas un mécanisme strict de fact checking phrase par phrase.

### 2.4 RAG : ingestion et retrieval au moment de la requête sont deux chemins différents

**Chemin d’ingestion** : `POST /knowledge/add` ou `/knowledge/upload` → `KnowledgeBase.add_documents_async()` → `knowledge/knowledge_base.py` découpe d’abord les documents selon les titres Markdown et les paragraphes anglais ; si un segment est trop long, il est ensuite limité selon les frontières de phrases ou de mots, avec ajout d’un overlap entre chunks adjacents → ChromaDB enregistre les chunks et leurs source metadata → l’API tente ensuite de rafraîchir l’index BM25 en mémoire. Les anciens chunks ne sont pas automatiquement reconstruits lorsque les règles de chunking changent ; après une modification du découpage, il faut donc prévoir le nettoyage de l’ancien index, une nouvelle ingestion et la mise à jour des chunk IDs utilisés dans les labels.

**Chemin de retrieval** : lorsque `CustomerServiceAgent.respond()` détermine qu’une knowledge evidence est nécessaire, il appelle d’abord `knowledge_search` via le Harness ; `ToolManager.search_with_rewrite()` conserve la requête originale et génère un petit nombre de variantes ; `HybridRetriever.search_async()` interroge ChromaDB Dense et BM25 ; les candidats sont fusionnés par RRF puis dédupliqués, avant d’être classés localement par `ToolManager.rerank()` et finalement limités au Top-K. Par défaut, BM25 est activé et les query variants ainsi que le Reranking utilisent des méthodes locales. Ce n’est que lorsque `ARCLUME_RAG_LLM_ENABLED=true` est activé que le Chat model configuré peut également être utilisé pour Query Rewriting et scoring/reranking. Le projet ne déploie pas de modèle Cross-Encoder ou Reranker indépendant.

Le comportement par défaut de l’Embedding dans ChromaDB dépend actuellement de la version fixée `chromadb==0.5.23` ; le projet n’injecte pas explicitement de fonction d’Embedding métier personnalisée. Tout changement d’Embedding doit donc être accompagné d’une reconstruction des vectors déjà stockés. Lorsqu’on modifie l’algorithme de retrieval, il faut distinguer **le cas où le bon chunk n’est pas rappelé**, **le cas où il est rappelé mais n’entre pas dans le Top-K**, et **le cas où il entre dans le Top-K mais où le modèle répond quand même incorrectement** ; ces problèmes doivent être examinés respectivement dans `knowledge/`, `tools/tool_manager.py` et Agent/Context, au lieu d’essayer de tout corriger au même endroit. `evaluation/data/rag_cases.json` dépend également des chunk IDs des documents de démonstration ; les labels doivent donc être revérifiés après toute modification de la logique d’ingestion.

### 2.5 Tools et Harness

`tools/tool_functions.py` contient les fonctions métier ou de démonstration ainsi que `register_tools()` ; dans `harness/executor.py`, `ToolDefinition` décrit le nom, le Schema, le niveau de risque, les Agents autorisés, le timeout, les retries, etc., tandis que `ToolExecutor.execute()` assure la validation des paramètres et l’exécution ; `tools/tool_manager.py` ajoute par-dessus le cache, le circuit breaker, les statistiques, les fallbacks et la recherche RAG. Dans `harness/policy.py`, `ToolPolicy.evaluate()` décide uniquement si un appel est autorisé, refusé ou soumis à approval ; dans `harness/runtime.py`, `handle_tool_call()` relie Policy, Executor, résultat standardisé et Trace.

Un ToolCall retourné par le modèle ne constitue pas une autorisation d’appeler directement une fonction Python. Le Tool doit être enregistré, activé, autorisé dans le périmètre de l’Agent actuel et passer le contrôle de risque. Un Tool à haut risque retourne `requires_approval` et n’est pas exécuté pendant cette requête ; il n’existe actuellement pas de boucle `/chat` permettant de reprendre automatiquement l’exécution après approbation. `ticket_create` est bien enregistré comme Tool de démonstration à haut risque, mais il n’appartient pas actuellement au périmètre des Tools des Agent Profiles et n’est connecté à aucun vrai système de ticketing. `order_query` et `logistics_query` retournent des Mock Data ; il n’existe actuellement aucun accès temps réel réel aux paiements ou remboursements.

Lors de l’ajout d’un nouveau Tool, il faut au minimum vérifier deux niveaux de permissions : **`allowed_agents` / `risk_level` dans la registration** et **`AgentProfile.tool_scope`**. Modifier seulement la fonction sans mettre à jour le Tool Schema peut empêcher le modèle de fournir les bons paramètres ; exposer seulement le Schema sans contrôle Policy casserait la frontière de gouvernance. Les échecs de Tool, les fallbacks et les résultats d’approval doivent être visibles dans `tool_traces` et dans le Trace.

Les Tool Calls retournés par les modèles ne contiennent pas toujours uniquement les champs standards. `core/llm_utils.py` conserve `extra_content` comme extension fournisseur non interprétée ; `CustomerServiceAgent._run_tool_loop()` renvoie ensuite ce contenu tel quel au modèle avec le Tool Call correspondant lorsqu’il lui transmet le résultat du Tool. L’interface OpenAI-compatible de Gemini 3 retourne par exemple une signature dans `extra_content.google.thought_signature` et exige qu’elle soit renvoyée lors de l’itération suivante de la Tool Loop ; si elle est absente, Gemini retourne une erreur 400. Les modèles OpenAI-compatible classiques n’ont généralement pas ce champ, mais suivent le même chemin. Lorsqu’on modifie le client modèle ou qu’on reconstruit l’historique des messages, il ne faut pas supprimer ce type de champ d’extension inconnu ; le test de regression associé est `tests/test_gemini_tool_signatures.py`.

### 2.6 Memory, AgentState et réponse finale

`ConversationMemory` utilise Redis pour stocker les messages récents et le résumé actuel de la conversation, puis compresse les anciens messages lorsqu’un seuil est atteint ; `LongTermMemory` utilise les collections `episodic` et `user_profile` de ChromaDB pour stocker des résumés historiques rappelables et le profil utilisateur ; `StateStore` utilise Redis pour stocker le `AgentState` structuré. Ces trois éléments contiennent des données persistantes entre plusieurs requêtes, mais leurs fonctions sont différentes : l’historique sert à maintenir la continuité de la conversation, `AgentState` représente l’état actuel du traitement du dossier, tandis que la Knowledge Base ChromaDB contient des informations métier et non la mémoire de conversation d’un utilisateur.

Dans le flow `/chat`, un Agent peut mettre à jour le `AgentState` du primary Agent, mais il ne se charge pas d’écrire le tour de conversation dans Redis ; après que l’Orchestrator a sélectionné **le texte final réellement envoyé à l’utilisateur**, `_persist_final_turn()` écrit de manière centralisée le message utilisateur et la réponse Assistant. Ainsi, lors d’une fusion multi-Agent, d’une demande d’information supplémentaire ou d’un fallback après échec, le système n’enregistre pas simplement un brouillon produit par le primary Agent. Les supporting Agents n’écrivent ni dans la conversation partagée ni dans le State partagé. Lorsqu’un Agent est appelé directement de manière isolée, sa capacité historique d’écriture dans la conversation reste disponible. Les écritures Redis ne sont pas transactionnelles à l’échelle de plusieurs messages : si une erreur se produit au milieu de l’écriture, un état partiellement écrit reste possible, et le système ne doit pas être présenté comme offrant une garantie transactionnelle.

Lorsqu’on modifie la Memory, il faut d’abord clarifier si l’objectif est de changer **où les données sont stockées**, **quand elles sont lues** ou **quelles informations sont montrées au modèle**, puis regarder respectivement `memory/`, `AgentOrchestrator` et `ContextBuilder`. Il ne faut pas traiter le `Context` temporaire d’une requête comme une base persistante, ni écrire plusieurs fois le même tour de conversation depuis plusieurs Agents exécutés en parallèle.

### 2.7 Trace, Monitor et Evaluation

Dans `harness/trace.py`, `TraceRecorder` conserve un nombre limité d’événements en mémoire du processus ; `request_id` relie les événements d’Intent, routing, Agent, Tool, Memory et fin de requête. Ces données disparaissent après un redémarrage du service ou lorsque les anciens événements sont évincés de la mémoire ; il ne s’agit pas d’une base d’audit. `PerformanceMonitor` lit périodiquement les métriques des Agents et Tools et peut appliquer une pénalisation limitée au score de routing entre plusieurs instances d’un même type d’Agent ; il ne juge pas si le contenu d’une réponse est factuellement correct et ne modifie pas automatiquement les Prompts ou Skills.

`evaluation/` correspond à un système séparé de contrôle qualité. `python -m evaluation` teste uniquement l’Intent recognition local et le routing déterministe ; il n’appelle pas le vrai `/chat`, le modèle, Redis ou ChromaDB. Les évaluations de retrieval RAG et de conversation end-to-end passent par l’API et dépendent de la Knowledge Base et de la configuration modèle actuelles ; la définition des métriques, les limites des données et la manière de sauvegarder les rapports sont décrites dans `evaluation_protocol_zh.md`. Attention en particulier : `POST /eval/run` sauvegarde actuellement une baseline end-to-end ; une requête contenant uniquement des cas RAG peut elle aussi écraser la baseline configurée. Il ne faut donc pas lancer une évaluation de démonstration sur une baseline à conserver sans avoir vérifié au préalable le chemin de sortie.

## 3. Modifications courantes : partir du besoin pour trouver rapidement le code

### 3.1 Utiliser d’abord ce tableau pour trouver le bon point d’entrée

| Ce que vous voulez modifier | À regarder en premier | À vérifier aussi | Tests principaux |
|---|---|---|---|
| L’Intent d’une phrase, les entities, ou la décision knowledge / real-time data | `core/intent_recognizer.py` | `agents/agent_orchestrator.py` ; vérifier si cela affecte le préchargement des Tools | `tests/test_intent.py`, `tests/test_orchestrator_memory.py` |
| Ajouter, séparer ou modifier un Skill de scénario | `skills/<name>/SKILL.md`, `AgentOrchestrator._skills_for()` | `agents` / `enabled` dans le front matter ; vérifier s’il faut ajouter un Intent plus précis ; longueur du Context et limites des Tools | `tests/test_skills.py`, `tests/test_request_plan_execution.py`, `tests/test_orchestrator_memory.py` |
| Choix du primary/supporting Agent ou demande d’informations supplémentaires à l’utilisateur | `agents/agent_orchestrator.py` | `IntentResult.supporting_domains`, `ResponseComposer`, écriture finale de la conversation | `tests/test_orchestrator_memory.py`, `tests/test_escalation.py` |
| Rôle ou règles métier visibles par le modèle | Sous-classe Agent, `AgentProfile`, `skills/`, `core/context_builder.py` | Périmètre des Tools, longueur du Context, indicateurs d’escalation | `tests/test_skills.py`, `tests/test_request_plan_execution.py` |
| Comment les connaissances sont découpées, stockées, recherchées et classées | `knowledge/`, `tools/tool_manager.py` | Rafraîchissement BM25, anciens chunks, dataset annoté RAG | `tests/test_knowledge_chunking.py`, `tests/test_hybrid_rag.py` |
| Ajouter un Tool métier ou rendre ses permissions plus strictes | `tools/tool_functions.py`, `harness/` | Tool Schema, Profile scope, Trace, approval | `tests/test_trace.py`, `tests/test_request_plan_execution.py` |
| Sauvegarde des messages ou mémoire multi-tour | `memory/`, `agents/agent_orchestrator.py` | `ContextBuilder`, profil utilisateur, State | `tests/test_memory.py`, `tests/test_orchestrator_memory.py` |
| Champs de l’API externe | `schemas/api.py`, `api/main.py` | `OrchestratorResult`, contrat OpenAPI | Tests du module concerné et vérification manuelle dans `/docs` |

### 3.2 Exemple : la politique de remboursement ne déclenche pas de retrieval

1. Commencez par regarder `intent`, `primary_agent` et `request_id` dans la réponse de `/chat`. Si l’Intent principal est devenu `query`, vérifiez `_pattern_evidence()`, `_template_match()` et `_information_need()` ; si l’Intent est bien `refund` mais qu’aucun besoin de connaissance n’est détecté, vérifiez surtout `_information_need()`.

2. Consultez `intent_recognized`, `route_selected` et `rag_completed` dans `/traces/{request_id}`. Si `should_use_rag=true` mais `attempted=false`, vérifiez ensuite si le Agent Profile autorise `knowledge_search` et si le Harness est disponible.

3. Si un Tool est bien appelé mais que `result_count=0`, vérifiez `/knowledge/stats`, `/search`, les documents importés ainsi que l’état de BM25 et ChromaDB. Il ne faut pas interpréter une Knowledge Base vide comme une erreur d’Intent.

4. Si le retrieval retourne des résultats mais que la réponse est incorrecte, vérifiez si le chunk pertinent est bien entré dans le Context, puis examinez le ranking, les documents obsolètes et la sortie du modèle. Il n’existe actuellement pas de mécanisme obligatoire de citation ou de fact checking.

5. Après la modification, ajoutez un positive example et au moins un negative example proche, puis exécutez les tests d’Intent, de préchargement et de RAG. Si le problème concerne la qualité du retrieval, comparez également le Top-K avec les exemples annotés au lieu de regarder uniquement si la réponse du modèle semble fluide.

### 3.3 Exemple : ajouter un nouveau Tool read-only

Commencez par implémenter dans `tools/tool_functions.py` une fonction avec une structure de retour claire, puis enregistrez-la. Dans `ToolDefinition`, définissez l’Input Schema, le niveau de risque, les Agents autorisés, le timeout et les retries, puis ajoutez le Tool au `tool_scope` du Agent concerné. S’il correspond à une donnée temps réel qui doit être récupérée dès que le besoin d’information est clairement identifié, il faut également ajouter le mapping des paramètres dans `IntentRecognizer._planned_tool()` et dans le chemin de préchargement de `CustomerServiceAgent.respond()` ; sinon, le Tool peut simplement rester disponible comme option pour le modèle. Enfin, vérifiez au minimum cinq chemins : absence de permission, paramètres manquants, timeout, échec et succès, ainsi que les informations enregistrées dans `ToolResult` et le Trace. Si le Tool effectue une write operation ou nécessite une approval, il ne faut pas transformer directement un Tool de démonstration en exécution métier réelle : il faut d’abord concevoir l’authentification, l’idempotence et la reprise après approval.

### 3.4 Exemple : modifier le chunking ou le ranking du retrieval

Pour le chunking, commencez par `KnowledgeBase._chunk_text()`, puis regardez `_split_long_paragraph()` pour les limites des longs paragraphes et `_overlap_tail()` pour l’overlap entre chunks adjacents. Modifier uniquement la taille des chunks change les IDs déjà utilisés dans les labels et peut aussi créer une différence de version entre les contenus des index BM25 et Dense ; il faut d’abord tester les titres, longs paragraphes, courts paragraphes et imports répétés avec des documents anglais, puis reconstruire la Knowledge Base dans un dataset isolé. Pour le ranking, regardez `HybridRetriever._rrf_fuse()` et `ToolManager.rerank()` ; lors d’une modification, mesurez le candidate recall, le classement dans le Top-K, la latence et l’utilisation éventuelle d’un modèle supplémentaire. Les données actuelles ne permettent pas d’affirmer directement qu’une méthode de rerank est meilleure qu’une autre.

### 3.5 Exemple : modifier la réponse multi-Agent ou la Memory

Il faut d’abord distinguer plusieurs étapes : **comment les subtasks par domaine sont créées à partir du message original** (`IntentRecognizer._build_subtasks()`), **quels Agents sont sélectionnés** (`_make_decision()`), **comment chaque task est transmise au bon Agent** (`_task_for()`, `_run_parallel()`), **comment les réponses sont fusionnées** (`ResponseComposer`) et **comment la réponse finale est enregistrée** (`_persist_final_turn()`). Il ne faut pas faire uniquement de la déduplication de texte dans le Composer : si plusieurs Agents reçoivent encore la requête complexe complète, chacun effectuera son propre retrieval et produira des réponses qui se recouvrent. Après toute modification, il faut vérifier que le message actuel reçu par chaque Agent et sa requête RAG sont bien limités à son domaine, que le tour suivant relit **la réponse externe finale après fusion**, et que les supporting Agents n’écrivent pas plusieurs fois la même conversation. Les tests concernés se trouvent principalement dans `tests/test_intent.py` et `tests/test_orchestrator_memory.py`.

## 4. Lancer le projet et observer le comportement du code

### 4.1 Trois niveaux de validation

| Niveau | Ce qu’il faut faire | Ce qu’il faut avoir | Ce que cela permet de vérifier |
|---|---|---|---|
| Vérification locale du code | Unit tests, évaluation Intent/routing | Environnement Python | Vérifier si les règles, le routing et les contrats entre modules se comportent comme prévu avec des test doubles |
| Vérification de l’infrastructure | Démarrer l’API, consulter `/health`, tester séparément le retrieval | Redis, ChromaDB ; le retrieval peut fonctionner par défaut sans appeler le modèle | Vérifier si les services arrivent à se connecter aux dépendances, si les connaissances sont bien importées et si la chaîne de retrieval retourne des résultats |
| Vérification avec un vrai chat | Appeler `/chat` et suivre le `request_id` | Redis, un Chat model disponible ; pour le RAG, une Knowledge Base est également nécessaire | Vérifier si la requête complète passe réellement par le modèle, les Tools, la Memory et la génération de réponse |

Il est recommandé de valider le projet dans cet ordre afin d’éviter de mélanger les problèmes du modèle, du retrieval et du routing. Le fait que `/health` retourne 200 ne signifie pas que `/chat` est déjà utilisable : l’application peut démarrer même sans Model Key ou lorsque certains stockages optionnels ne sont pas disponibles.

### 4.2 Environnement local et configuration

Le projet utilise Python 3.10 et `requirements.txt`. Les commandes suivantes doivent être exécutées depuis la racine du repository ; si un `.venv` existe déjà, vous pouvez simplement l’activer sans le recréer.

```bash
python3.10 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m unittest discover -s tests -q
python -m evaluation --smoke
```

La configuration est enregistrée dans un fichier local `.env`, chargé par `api/main.py`. Il ne faut jamais commit une vraie API Key. Vérifiez au minimum les paramètres suivants :

| Configuration | Qui la lit | Utilité |
|---|---|---|
| `LLM_API_KEY`, `LLM_BASE_URL`, `LLM_MODEL` | `core/llm_utils.py` | Interface Chat Completions compatible OpenAI ; nécessaire pour un vrai `/chat` |
| `REDIS_URL` | `api/main.py`, `memory/` | Messages récents, résumé et `AgentState` ; un Redis accessible est nécessaire pour un vrai `/chat` |
| `CHROMA_HOST`, `CHROMA_PORT` | `knowledge/`, `memory/long_term_memory.py` | Knowledge Base, résumés historiques et profils utilisateur |
| `ARCLUME_INTENT_LLM_ENABLED` | `api/main.py` | Vérification optionnelle par modèle lorsqu’il existe une ambiguïté dans la reconnaissance locale ; désactivée par défaut |
| `ARCLUME_RAG_LLM_ENABLED` | `tools/tool_manager.py` | Query Rewriting et Reranking optionnels avec LLM ; désactivé par défaut |
| `ARCLUME_RAG_BM25_ENABLED` | `tools/tool_manager.py` | Branche de retrieval BM25 ; activée par défaut |
| `ARCLUME_MEMORY_LLM_ENABLED` | `memory/conversation_memory.py` | Résumé ou extraction d’informations supplémentaires avec modèle ; désactivé par défaut |

Pour un premier test, si vous voulez limiter le nombre d’appels modèle, gardez les trois options LLM facultatives sur `false`. Cela désactive uniquement les appels supplémentaires : **la génération normale de réponse par les Agents continue à appeler le Chat model**. Dans le Compose local, Redis demande un mot de passe par défaut ; si vous démarrez les dépendances avec `docker compose up -d redis chromadb`, le `REDIS_URL` utilisé par le processus Python sur la machine locale doit utiliser le même mot de passe que celui configuré dans Compose. ChromaDB est exposé sur le port 8001 de la machine hôte, tandis que son port dans le conteneur est 8000.

```bash
docker compose up -d redis chromadb
python -m uvicorn api.main:app --reload --host 127.0.0.1 --port 8000
```

Après le démarrage, commencez par vérifier :

```bash
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/knowledge/stats
```

S’il manque des connaissances dans la base, vous pouvez importer des documents anglais de service client avec `POST /knowledge/add` ou `POST /knowledge/upload`, puis tester à nouveau le retrieval. `POST /search` et `GET /knowledge/search` permettent d’observer séparément les résultats de recherche ; par défaut, le Query Rewriting et le ranking locaux ne consomment pas de model tokens, mais lorsque `ARCLUME_RAG_LLM_ENABLED` est activé, le système **peut** appeler le modèle.

### 4.3 Un chat minimal et les points d’entrée pour le debugging

```bash
curl -X POST http://127.0.0.1:8000/chat \
  -H 'Content-Type: application/json' \
  -d '{"message":"What is your refund policy?","user_id":"demo-user","conversation_id":"demo-001"}'
```

Conservez le `request_id` retourné dans la réponse. `message` correspond à la réponse réellement visible par l’utilisateur ; `intent`, `primary_agent`, `supporting_agents`, `tools_used` et `tool_traces` servent principalement au debugging. Vous pouvez ensuite appeler :

```bash
curl http://127.0.0.1:8000/traces/RETURNED_REQUEST_ID
curl http://127.0.0.1:8000/trace/tool/RETURNED_REQUEST_ID
```

Pour cette question sur la politique de remboursement, le système devrait d’abord identifier le domaine Billing et un besoin de connaissance, puis tenter un `knowledge_search`. Si aucun document pertinent n’est disponible dans la Knowledge Base, le système peut bien avoir essayé le retrieval sans obtenir d’evidence utilisable ; `primary_agent=billing` ou `use_rag=true` ne suffit donc pas à conclure que la réponse est réellement supportée par la Knowledge Base.

## 5. Tests, évaluation et vérifications après modification

Lors d’une modification, commencez par exécuter les unit tests les plus proches du code concerné, puis lancez l’ensemble des tests. Ces tests utilisent des test doubles et ne prouvent pas que le vrai fournisseur de modèle ou les vrais services de stockage sont disponibles :

```bash
python -m unittest discover -s tests -p 'test_intent.py' -v
python -m unittest discover -s tests -q
python -m evaluation
python -m evaluation --smoke
git diff --check
```

Les 500 exemples synthétiques d’Intent en anglais générés par LLM peuvent être utilisés pour la regression des règles, mais ils ne représentent pas du trafic naturel et n’ont pas encore fait l’objet d’une validation humaine indépendante. Après avoir ajusté plusieurs fois les règles sur ce même dataset, il ne faut surtout pas le présenter comme une preuve indépendante de généralisation. Pour le RAG, il faut vérifier séparément les documents réellement importés et les retrieval labels ; pour les réponses d’un vrai modèle, il faut également examiner la fidélité aux evidence, la latence et le coût. Si vous voulez conserver un rapport d’évaluation, utilisez `python -m evaluation --report <fichier_de_sortie_clairement_defini>` au lieu d’écraser directement un ancien résultat important. Le risque lié aux baselines lors des évaluations RAG via API est décrit dans la section 2.7 ci-dessus et dans `evaluation_protocol_zh.md`.

Avant un commit, vérifiez au minimum les points suivants : tout comportement ajouté ou modifié possède des positive et negative examples ; le contrat HTTP reste cohérent avec les modèles de résultats internes ; les Mock Data et les vraies données ne sont pas présentées de la même manière dans la documentation ou les réponses ; les options de modèle facultatives ont le comportement attendu ; les chemins d’erreur peuvent être identifiés avec le Trace ; aucune API Key, donnée client ou fichier `.env` local n’est ajouté au repository. Lorsqu’une nouvelle write operation métier est introduite, il faut également vérifier l’approval, l’idempotence, les permissions et l’audit, et ne pas se contenter de voir que les unit tests passent.

## 6. Diagnostic par symptôme

| Symptôme | À regarder en premier | Cause fréquente ou étape suivante |
|---|---|---|
| `/health` retourne 200, mais `/chat` retourne 503 | `llm_configured`, connexion Redis, logs API | Le service peut démarrer même si le modèle ou Redis n’est pas encore utilisable ; vérifier le `.env` local et `REDIS_URL` |
| `/chat` retourne 502 | Erreur d’appel du modèle et configuration | Vérifier que la Base URL pointe vers une interface compatible Chat Completions, le nom du modèle, le quota, le réseau et le `detail` retourné par l’API ; si l’échec apparaît uniquement lors du deuxième appel modèle dans une Tool Loop, vérifier que les champs d’extension du fournisseur ont bien été renvoyés, par exemple le `thought_signature` de Gemini ; ne jamais partager la Key |
| Mauvais Intent ou mauvais Agent | `intent_recognized`, `route_selected` | Distinguer topic evidence, mauvais match de template, ambiguïtés et détection de plusieurs domaines indépendants |
| Une question de politique n’utilise pas les connaissances | `should_use_rag`, `rag_completed`, Tool Trace | Déterminer d’abord si le RAG n’a pas été planifié, n’a pas été exécuté ou a été exécuté sans résultat |
| `/search` retourne un résultat vide | `/knowledge/stats`, ChromaDB, nombre de documents BM25 | Connaissances non importées, anciens chunks, mismatch entre query et ranking, ou fallback d’une branche |
| Le modèle affirme avoir consulté une vraie commande ou un vrai remboursement | `information_need`, `planned_tool_name`, `tool_traces` | Les commandes et la logistique utilisent seulement des Mock Data ; il n’existe pas de vraie interface de données pour paiements/remboursements. Il faut corriger la réponse et concevoir un mécanisme de fact checking |
| La Memory du tour suivant est incorrecte | Messages/résumé Redis, `_persist_final_turn()` | Vérifier `user_id` / `conversation_id`, le texte final enregistré, le TTL Redis et un éventuel partial write |
| Seulement une partie du Trace est visible | `/traces/{request_id}`, état du processus | Le Trace existe uniquement dans le processus courant et peut disparaître après un redémarrage ou à cause de la limite de capacité |

L’ordre de diagnostic recommandé est généralement : HTTP/dépendances → Intent → Routing → Agent/Context → Tool/RAG → réponse du modèle → écriture dans la Memory. Commencez par utiliser `request_id` pour vérifier quelles couches ont réellement été traversées avant de modifier le code ; il ne faut pas essayer de deviner le chemin interne uniquement à partir de la réponse visible par l’utilisateur.

## 7. État actuel et limites de l’implémentation

Ce repository est actuellement un prototype d’ingénierie démontrable, et non un service déjà connecté à un système de support client en production : les intégrations réelles pour commandes, logistique, paiements, remboursements et tickets ne sont pas terminées ; les Tools à haut risque peuvent seulement être bloqués ou marqués comme « approval required », sans reprise d’exécution après approbation ; le Trace n’est pas persistant ; l’évaluation RAG reste limitée et ne permet pas encore de démontrer qu’un LLM Reranker est meilleur que le ranking local ; le Context ne possède pas encore de gestion complète du Token budget et les réponses ne sont pas soumises à une vérification obligatoire des sources. L’API ne dispose pas non plus actuellement d’un système complet d’authentification utilisateur, d’autorisation fine-grained, de gestion de la vie privée ou de rate limiting.

Lors de la lecture ou de la modification du code, il faut distinguer **« le code possède déjà un point d’entrée »**, **« la fonction peut être démontrée avec des Mock Data »** et **« la capacité métier réelle est déjà intégrée »**. Pour avancer vers la production, il faut d’abord compléter les contrats avec les vrais systèmes métier et les security boundaries, puis construire des baselines séparées pour l’Intent, le retrieval et la qualité des réponses à partir de cas de service client en anglais validés manuellement ; le succès d’un seul appel `/chat` ne suffit pas à déclarer qu’une fonctionnalité est terminée.

## Annexe : raccourci des interfaces et fichiers de test

| Utilité | Route ou fichier |
|---|---|
| HTTP et documentation interactive | `POST /chat`, `GET /health`, `GET /docs` ; `api/main.py`, `schemas/api.py` |
| Retrieval et import de connaissances | `GET /knowledge/search`, `POST /search`, `POST /knowledge/add`, `POST /knowledge/upload`, `GET /knowledge/stats` |
| Debugging et monitoring | `GET /traces/{request_id}`, `GET /trace/tool/{request_id}`, `GET /monitor`, `GET /metrics` |
| Gestion des Skills | `GET /skills`, `POST /skills/reload` |
| Évaluation API | `POST /eval/run` ; `evaluation/`, `evaluation_protocol_zh.md` |
| Tests Intent/routing | `tests/test_intent.py`, `tests/test_orchestrator_memory.py` |
| Tests RAG/préchargement | `tests/test_knowledge_chunking.py`, `tests/test_hybrid_rag.py`, `tests/test_request_plan_execution.py` |
| Tests Memory/Tool/état d’exécution | `tests/test_memory.py`, `tests/test_trace.py`, `tests/test_escalation.py`, `tests/test_monitor.py` |