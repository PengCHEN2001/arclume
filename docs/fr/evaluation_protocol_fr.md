# Arclume — Système d’évaluation et méthodes d’exécution

Ce document explique **ce qui est actuellement évalué, comment l’évaluation est réalisée, comment la lancer soi-même et ce qui n’est pas encore évalué**. Pour le design et le flow du code, voir `project_design_and_request_flow_fr.md` ; les principaux points d’entrée de l’évaluation se trouvent dans `evaluation/` et `api/main.py`. Le projet cible des messages de service client en anglais et des documents de Knowledge Base en anglais ; toutes les conclusions sur la qualité doivent donc être basées sur des données cohérentes avec cet objectif.

> Statut : protocole d’évaluation d’ingénierie. Les données actuelles servent principalement à la regression pendant le développement. Les seuils d’acceptation officiels, les règles d’annotation et un test set indépendant ne sont pas encore définis. Les métriques ou frameworks futurs sont indiqués comme « planned » et ne doivent pas être présentés comme des capacités déjà implémentées.

## 1. L’évaluation doit être faite par couche, et pas seulement avec un score global

| Couche | Question à laquelle répondre | Point d’entrée actuel | Existe-t-il actuellement un résultat fiable ? |
|---|---|---|---|
| Comportement des modules | Les contrats du code pour le chunking, les permissions, l’écriture finale, les fallbacks en cas d’erreur, etc. sont-ils corrects ? | Unit tests dans `tests/` | Il existe un signal pass/fail des tests ; ce n’est pas une mesure d’Accuracy. |
| Intent et primary Agent | Le topic label est-il correct et le primary routing déterministe correspond-il aux annotations ? | `python -m evaluation` | Il existe des résultats locaux sur des exemples synthétiques générés par LLM ; ils n’incluent pas les réponses du modèle. |
| RAG retrieval | Les chunks annotés comme pertinents sont-ils rappelés et placés dans le Top-K ? | `retrieval_cases` dans `/eval/run` | 18 cas de démonstration et les métriques sont implémentés ; il n’existe pas encore de résultat actuel confirmé. |
| Conversation Agent | Une ou plusieurs étapes de conversation permettent-elles de résoudre la demande, et la réponse est-elle utile ? | `dialog_cases` dans `/eval/run`, vrai `/chat` | L’exécution et un LLM Judge optionnel sont disponibles ; il n’existe pas encore de baseline de qualité en anglais calibrée manuellement. |
| Fiabilité en exécution | Comment évoluent les erreurs, la latence et le taux de succès des Tools dans le temps ? | `/monitor`, `/metrics`, Trace | Il s’agit d’observability en exécution, pas d’une évaluation de qualité sur des données annotées. |

Ces différentes couches doivent être analysées séparément. Par exemple, une mauvaise réponse à une question sur la politique de remboursement peut venir d’un Intent mal reconnu, d’un RAG non déclenché, d’un chunk correct non rappelé, d’un résultat qui n’entre pas dans le Top-K, ou encore du modèle qui répond mal malgré la présence de la bonne evidence. Regarder uniquement la réponse finale ou un score global ne permet pas de localiser la cause.

## 2. Données et code d’évaluation actuels

| Données / code | Contenu actuel | Limites principales |
|---|---|---|
| `evaluation/data/intent_cases_500.json` | 500 messages synthétiques en anglais générés par LLM, 19 classes d’Intent et primary Agent attendu | Les exemples et labels n’ont pas encore fait l’objet d’une validation humaine indépendante et ne représentent pas la distribution réelle des utilisateurs ; les règles peuvent être overfit sur ce dataset. |
| `evaluation/data/cases.json` | 9 cas locaux de smoke test | Sert uniquement à vérifier rapidement que les principaux points d’entrée fonctionnent ; ne permet pas de publier une conclusion sur la qualité. |
| `evaluation/data/rag_cases.json` | `rag-smoke-v3` : 18 questions de retrieval en anglais, avec les chunk IDs pertinents annotés dans 9 documents de démonstration fictifs ; la plupart utilisent `top_k=3`, avec une question cross-document en `top_k=5` | Couvre uniquement une petite Knowledge Base de démonstration ; doit rester cohérent avec les documents actuels, les paramètres de chunking et la version de l’index. |
| Cas de dialogue par défaut dans `evaluation/evaluator.py` | Quelques exemples de questions-réponses et de flows multi-tour | Les exemples par défaut contiennent actuellement du chinois et ne conviennent pas comme baseline d’un produit de service client en anglais ; une vraie évaluation doit fournir ses propres cas en anglais. |
| `evaluation/metrics.py`, `runner.py` | Métriques de classification et de retrieval, enregistrement détaillé des erreurs | Calcule uniquement les scores à partir des labels fournis par les données ; ne vérifie pas si ces labels sont eux-mêmes corrects. |
| `evaluation/judge.py` | Chat LLM optionnel pour scorer les réponses | Le Judge n’est pas calibré avec des évaluations humaines ; le scoring du modèle ne remplace pas une vérification des faits métier. |

### 2.1 Principes d’annotation et de version des données

Chaque cas de classification doit contenir au minimum le message, l’Intent attendu et le primary Agent attendu ; chaque cas de retrieval doit contenir au minimum une query en anglais, les chunk IDs pertinents et `top_k`. Pour évaluer plus tard le multi-Agent, les Tools et les evidence, il faudra également annoter les supporting Agents attendus, l’`information_need`, les Tools obligatoires ou interdits, les paramètres importants, les evidence attendues et les réponses sûres acceptables.

Modifier les documents, `CHROMA_CHUNK_SIZE` / `CHROMA_CHUNK_OVERLAP` ou le code de chunking peut modifier les chunk IDs. Les labels actuels de `rag-smoke-v3` ont été revérifiés avec le chunking actuel utilisant par défaut une limite de 500 caractères et un overlap de 50 caractères, et `tests/test_evaluation.py` vérifie que les IDs annotés correspondent toujours aux fichiers de démonstration. **Ce test ne vérifie pas que les labels sémantiques sont forcément corrects et ne supprime pas automatiquement les anciens chunks déjà présents dans ChromaDB.** Si une évaluation utilise un ancien index, il faut d’abord reconstruire la Knowledge Base dans un environnement isolé ; un mauvais score obtenu sur un ancien index ne doit pas être interprété directement comme une regression de l’algorithme de retrieval.

Avant toute comparaison formelle, il faut fixer la version du code, la version du dataset, le snapshot de la Knowledge Base, la configuration Embedding/modèle, les options BM25 et RAG LLM, le Top-K, la date et le nombre de répétitions. Après avoir ajusté plusieurs fois les règles sur le même dataset public, il faut également conserver un test set séparé qui ne sert pas au tuning et effectuer une vérification humaine d’un échantillon des annotations.

## 3. Comment les métriques actuelles sont calculées et ce qu’elles permettent de conclure

### 3.1 Intent et primary routing déterministe

`evaluation/runner.py:evaluate_intent_cases()` appelle le `IntentRecognizer.recognize()` local et compare l’Intent prédit avec le label annoté ; le CLI local utilise également une fonction simplifiée de mapping déterministe pour obtenir le primary Agent attendu. Le rapport fournit séparément l’Accuracy et le Macro-F1 pour l’Intent et le primary routing, ainsi que la Precision, le Recall, le F1 et les exemples d’échec pour chaque classe.

- **Accuracy** : nombre de prédictions correctes ÷ nombre total d’exemples.
- **Precision / Recall / F1** : répondent respectivement aux questions « parmi les exemples prédits comme appartenant à cette classe, combien appartiennent réellement à cette classe ? », « combien d’exemples de cette classe ont été retrouvés ? » et « quel est le compromis entre les deux ? ».
- **Macro-F1** : moyenne simple du F1 de chaque classe, afin d’éviter que les grandes classes masquent les problèmes des petites classes.

Ici, le primary routing correspond à « sortie du Recognizer + table de routing simplifiée ». **Le système n’instancie pas les Agents complets et n’évalue ni les supporting Agents, ni le déclenchement du RAG, ni les appels de Tools, ni les réponses du modèle.** Cette évaluation est utile pour détecter une regression dans la classification en amont, mais elle ne doit pas être appelée « Accuracy de l’ensemble du système Agent ».

### 3.2 Retrieval : vérifier si les chunks pertinents sont revenus

`evaluate_retrieval_cases()` envoie chaque query dans la chaîne de retrieval actuelle, récupère les `chunk_id` retournés et les compare aux IDs annotés comme pertinents. Un même ID retourné plusieurs fois ne compte qu’une seule fois ; les métriques sont d’abord calculées séparément pour chaque cas, puis moyennées simplement sur l’ensemble des cas.

| Métrique | Signification dans ce projet |
|---|---|
| Recall@K | Parmi les chunks annotés comme pertinents, combien apparaissent dans les K premiers résultats |
| Precision@K | Parmi les K premières positions, combien correspondent à des chunks pertinents ; même si moins de K résultats sont réellement retournés, K reste le dénominateur |
| MRR | Inverse du rang du premier chunk pertinent ; vaut 0 si aucun chunk pertinent n’apparaît dans les K premiers résultats |
| nDCG@K | Donne un meilleur score lorsque les chunks pertinents apparaissent plus haut dans le classement ; les labels actuels sont binaires : pertinent / non pertinent |

Les cas de retrieval actuels vérifient uniquement **si des chunks avec des IDs fixes apparaissent dans les résultats**. Ils ne vérifient pas si la réponse finale reste fidèle aux evidence et ne couvrent pas encore le cas où le système devrait refuser de répondre parce que la Knowledge Base ne contient pas l’information. Les cas en erreur sont enregistrés comme erreurs et participent au résumé avec un résultat vide ; pendant l’analyse, il faut donc regarder aussi `retrieval_failures` et `retrieval_errors`, et pas uniquement les moyennes.

### 3.3 Dialogue et LLM Judge

`EndToEndEvaluator` exécute les `dialog_cases` prédéfinis ou personnalisés. À chaque tour, l’Orchestrator est réellement exécuté, puis un `LLMJudge` optionnel peut attribuer un score de 0 à 1 à la pertinence, l’exactitude, la complétude et l’utilité de la réponse ; la moyenne de ces quatre dimensions devient le score `overall` du tour. Le seuil de réussite actuel pour un cas individuel est `0.75`. Pour les cas multi-tour, chaque tour est évalué séparément ; il ne faut pas réduire toute une conversation à un seul score qui masquerait les tours en échec.

**Limite importante :** si le Judge échoue ou n’est pas configuré, le code utilise quatre valeurs `0.5` comme placeholders et ajoute le flag `judge_failed` ; si l’exécution de l’Orchestrator échoue, il enregistre également `execution_failed`. Ces deux types de scores ne doivent jamais être interprétés comme une vraie mesure de qualité de réponse. Le `context` fourni actuellement au Judge correspond surtout aux tours précédents de la conversation d’évaluation, **et non aux evidence complètes récupérées par le retrieval** ; même lorsqu’un Judge fonctionne correctement, cela ne suffit donc pas à démontrer que chaque affirmation de la réponse est fidèle à la Knowledge Base. Il faut examiner manuellement la réponse, les passages récupérés et le Trace, puis construire une évaluation séparée de la cohérence avec les evidence.

### 3.4 La comparaison de regression n’est pas un seuil de mise en production

Le CLI compare deux rapports JSON uniquement lorsque `--baseline` est fourni explicitement. Par défaut, `evaluation/regression.py` autorise une baisse relative maximale de 5 % pour chaque métrique ; par exemple, passer de 0.80 à environ 0.76 correspond à une baisse relative de 5 %, et non à une baisse de 5 points de pourcentage. Une métrique présente dans l’ancienne baseline mais absente du nouveau rapport est également considérée comme un problème. Ce seuil est seulement une valeur par défaut dans le code et **ne constitue pas encore un critère officiel d’acceptation** ; il faut aussi vérifier que les datasets et configurations des deux runs sont réellement comparables.

## 4. Comment exécuter les évaluations : du mode sans modèle au vrai dialogue

Les commandes suivantes doivent être lancées depuis la racine du repository. Si les dépendances Python sont nécessaires, activez d’abord `.venv` ; pour la configuration nécessaire au démarrage de l’API, voir `code_guide_zh.md`. Avant toute exécution réelle, il ne faut jamais écrire une vraie API Key directement dans une commande, un rapport ou le repository.

### 4.1 Le moins coûteux : unit tests et évaluation locale Intent/routing

```bash
python -m unittest discover -s tests -q
python -m evaluation --smoke
python -m evaluation
```

Ces commandes n’appellent pas de vrai Chat model et ne nécessitent pas de lancer l’API, Redis ou ChromaDB. Il faut examiner dans la sortie `metrics`, `counts`, `failure_preview` et les métriques par classe ; si vous voulez conserver les détails de chaque cas, indiquez un **nouveau** chemin de rapport :

```bash
python -m evaluation --report evaluation/reports/intent-local-YYYYMMDD.json
```

Utilisez `--baseline <chemin_du_rapport_historique>` uniquement lorsqu’un ancien rapport JSON réellement comparable existe ; ce paramètre lit l’ancien rapport et effectue la comparaison, mais ne vérifie pas à votre place la qualité des labels. `--verbose` permet d’afficher davantage de détails cas par cas dans le terminal. Après une modification des règles d’Intent, regardez en priorité les classes avec un faible F1 et les exemples d’erreur, notamment les cas où une question générale masque un sujet métier, où deux domaines sont fusionnés à tort, ou encore où des paraphrases anglaises sont mal reconnues.

### 4.2 Sans Chat model : tester le RAG retrieval sur une Knowledge Base isolée

La version actuelle de `rag-smoke-v3` correspond **aux neuf documents de démonstration réindexés avec les règles de chunking actuelles**. Ajouter de nouveaux fichiers ne les fait pas automatiquement entrer dans une collection ChromaDB déjà non vide ; la méthode la plus sûre consiste donc à lancer une instance ChromaDB indépendante et vide, plutôt que de supprimer la Knowledge Base existante ou de réutiliser directement un ancien volume persistant. L’exemple ci-dessous utilise plusieurs terminaux ; les ports 8002 et 8010 peuvent être adaptés selon les ports déjà occupés.

Terminal A : lancer une instance ChromaDB temporaire sans monter de volume de données existant :

```bash
docker run --rm -p 8002:8000 chromadb/chroma:0.5.23
```

Terminal B : depuis la racine du repository, lancer l’API et faire pointer la baseline écrite par `/eval/run` vers **un répertoire temporaire unique** :

```bash
EVAL_SCRATCH_DIR=$(mktemp -d)
CHROMA_HOST=127.0.0.1 CHROMA_PORT=8002 \
ARCLUME_RAG_LLM_ENABLED=false \
ARCLUME_EVAL_BASELINE_PATH="$EVAL_SCRATCH_DIR/baseline.json" \
python -m uvicorn api.main:app --host 127.0.0.1 --port 8010
```

Lors du démarrage avec une Knowledge Base vide, l’application essaie d’importer `data/demo_docs/` ; le modèle Embedding par défaut peut nécessiter un téléchargement local lors de la première utilisation, mais cela ne correspond pas à un appel payant au Chat model. Dans le terminal C, vérifiez `knowledge_base.ready` et `rag_bm25_documents` dans `/health`, ainsi que le nombre total de chunks dans `/knowledge/stats`, puis exécutez :

```bash
curl http://127.0.0.1:8010/health
curl http://127.0.0.1:8010/knowledge/stats
curl -X POST http://127.0.0.1:8010/eval/run \
  -H 'Content-Type: application/json' \
  --data-binary @evaluation/data/rag_cases.json
```

Regardez `retrieval.metrics`, `retrieval.counts` et `retrieval.failures` dans la réponse, et non les scores de dialogue end-to-end. Dans `rag_cases.json`, les cas d’Intent et de dialogue sont vides et le RAG LLM est désactivé ; cet exemple n’a donc pas besoin d’un vrai Chat model. **Cependant, `/eval/run` écrit toujours d’abord une baseline end-to-end vide**, ce qui rend indispensable l’utilisation d’un chemin temporaire. Si les documents de démonstration n’ont pas été importés ou si d’anciens et de nouveaux chunks sont mélangés, il faut d’abord corriger la version de l’index avant de discuter du Recall@K. Sans Docker, il est aussi possible d’utiliser une autre instance ChromaDB isolée, à condition de respecter le même principe : « base vide + données actuelles + baseline temporaire ».

### 4.3 Avec un vrai modèle : commencer par quelques vérifications manuelles via `/chat`

Après avoir configuré `LLM_API_KEY`, `LLM_BASE_URL`, `LLM_MODEL`, Redis et la Knowledge Base nécessaire, il est recommandé de désactiver d’abord les trois options LLM supplémentaires afin que seuls les appels normaux des Agents consomment des requêtes modèle. Testez successivement un message de salutation, une question sur la politique de remboursement, une requête complexe combinant problème de connexion et double débit, puis une demande de transfert vers un humain ; conservez chaque `request_id` et consultez `/traces/{request_id}` ainsi que `/trace/tool/{request_id}`. Pour chaque cas, notez l’Intent, le primary Agent et les supporting Agents, si le système a planifié un besoin de connaissance ou de données temps réel, si le Tool a réellement été exécuté, quelles evidence ont été obtenues, si la réponse utilise les bons faits et si elle invente une opération non exécutée.

## 5. Résultats, rapports et pièges connus

### 5.1 Résultats existants sans modèle

| Date et périmètre | Intent Accuracy / Macro-F1 | Primary routing Accuracy / Macro-F1 | Interprétation |
|---|---|---|---|
| 2026-09-16, ancien run sur 500 exemples générés par LLM | 72.80% / 0.7380 | 80.20% / 0.8026 | Référence historique correspondant à l’implémentation de l’époque ; aucun JSON détaillé n’a été conservé, donc ce résultat ne doit pas être présenté comme celui du code actuel |
| 2026-10-04, même ensemble de 500 exemples générés par LLM sur le workspace actuel | 92.20% / 0.9213 | 96.60% / 0.9710 | Recognizer local + primary routing déterministe simplifié ; 39 erreurs d’Intent et 17 erreurs de primary routing ; aucun appel modèle/API/Redis/ChromaDB |

Ces deux runs montrent l’évolution sur ce même ensemble d’exemples générés par LLM, mais en l’absence de hidden test set indépendant, de validation humaine ou de trafic réel, ils ne permettent pas d’estimer l’Accuracy en production. Pour le RAG, `rag-smoke-v3` a actuellement seulement été vérifié pour confirmer la cohérence entre les IDs annotés et le chunking actuel ; **aucune métrique de retrieval réelle et valide n’est encore enregistrée dans ce protocole**. Il n’existe pas non plus encore de résultat confirmé pour les réponses d’un vrai modèle ou pour le LLM Judge.

Le même jour, les vérifications du code ont donné 69 unit tests réussis et 9 cas locaux de smoke test réussis ; cela inclut des regression tests vérifiant qu’une requête complexe est séparée en subtasks par domaine et que des sous-problèmes différents sont envoyés respectivement aux Agents General et Billing. Aucun de ces tests n’a appelé de vrai modèle. Les logs de pannes simulées visibles pendant les unit tests servent à vérifier les chemins de fallback et ne signifient pas que les tests ont échoué.

### 5.2 Attention particulière aux baselines et aux scores placeholder en cas d’échec

`EndToEndEvaluator.run()` sauvegarde son propre rapport à chaque exécution ; le chemin par défaut de l’API est `evaluation/baselines/baseline.json`, et il peut être modifié avec `ARCLUME_EVAL_BASELINE_PATH`. Même lorsqu’une requête contient uniquement des cas de retrieval, l’API lance d’abord une évaluation end-to-end vide et sauvegarde ce rapport, puis ajoute les résultats de retrieval **uniquement dans la réponse** ; la baseline sauvegardée ne contient donc pas les métriques RAG ajoutées ensuite. Avant de lancer une évaluation de retrieval, utilisez un chemin temporaire afin de ne pas écraser un rapport à conserver. À plus long terme, il serait préférable de séparer la sauvegarde des rapports de retrieval de celle des baselines end-to-end.

Lors de la lecture d’un rapport, il faut au minimum vérifier d’abord que le nombre de cas est correct, qu’aucune erreur d’exécution importante n’a eu lieu, que le Judge a réellement fonctionné, que les labels et l’index correspondent bien entre eux, et que la configuration utilisée est identique. Si les données, la Knowledge Base ou la configuration diffèrent, ou si le Judge a échoué, il ne faut pas décider qu’une version est meilleure qu’une autre uniquement à partir de deux `pass_rate` ou scores moyens.

## 6. Plan d’évaluation pour la prochaine étape — non encore implémenté

### 6.1 Commencer par améliorer les données avant d’ajouter des scores avancés

La priorité est de construire un petit gold standard en anglais, vérifié manuellement, pour les scénarios de service client. Il devrait couvrir les salutations simples, les politiques, les commandes/logistique, les problèmes de connexion, les doubles débits, les requêtes multi-domaines, les questions sans réponse disponible, les négations et questions rhétoriques, les demandes dépendant de l’historique, les opérations à haut risque et les demandes de transfert vers un humain. Pour chaque cas, il faut annoter le topic attendu, le primary Agent et les supporting Agents, le besoin d’information, les Tools autorisés ou interdits, les evidence pertinentes, les éléments attendus dans une réponse acceptable et les faits inventés qui doivent absolument être refusés. Il faut séparer un development set d’un held-out test set, enregistrer les désaccords d’annotation et, pour les effets de hasard liés au modèle ou au Prompt, répéter plusieurs fois l’exécution et rapporter la variance.

### 6.2 RAG : passer de « le document a été trouvé » à « la réponse est réellement fondée »

Les métriques actuelles Recall@K, MRR et nDCG peuvent rester la première couche de l’évaluation du retrieval. Il faut ensuite ajouter le taux de hit avant/après Query Rewriting, comparer BM25 seul, Dense seul et Hybrid Search, comparer différents Top-K et différentes méthodes de rerank, et mesurer le taux de mauvaise réponse lorsque la Knowledge Base ne contient pas l’information. Ensuite, pour chaque chaîne **question → passages récupérés → réponse finale**, il faut annoter **si les evidence sont suffisantes, si les claims de la réponse sont supportées par les passages, et si le système omet ou invente des politiques**. Une simple similarité entre la réponse et une référence peut mesurer une proximité de formulation ou de sens, mais elle ne permet pas à elle seule de détecter un mauvais montant ou un mauvais nombre de jours.

Il est possible de s’inspirer du [papier RAGChecker](https://arxiv.org/abs/2408.08067) pour un diagnostic plus fin du retrieval et de la génération, ou du [catalogue officiel des métriques Ragas](https://docs.ragas.io/en/latest/concepts/metrics/available_metrics/) avec des métriques comme context precision/recall, faithfulness, response relevancy et semantic similarity. Ces outils ne sont actuellement pas intégrés à Arclume et aucun score correspondant n’existe encore. Le choix d’un framework doit comparer sa cohérence avec les évaluations humaines, le coût des appels modèle supplémentaires et la reproductibilité, et non simplement chercher à produire un seul score.

### 6.3 Agent : évaluer la réponse finale, mais aussi la trajectoire d’action

L’évaluation locale actuelle du routing ne couvre que le primary Agent. La prochaine étape devrait mesurer séparément l’Accuracy de l’ensemble primary/supporting Agents, la Precision/Recall du déclenchement du RAG, le Tool Call Recall lorsque des Tools sont nécessaires, le taux de violation pour les Tools interdits, l’exactitude des paramètres, le taux de blocage correct par le Harness lors d’une approval, la continuité de l’état en multi-tour, le taux de succès des fallbacks après échec et la réussite réelle de l’objectif utilisateur. Pour un système de service client, il faut notamment vérifier que le système ne prétend pas avoir consulté une vraie commande ou un vrai paiement lorsqu’aucune donnée réelle n’est disponible, qu’il n’exécute pas d’opération à haut risque sans approval et qu’un message d’escalation ne prétend pas qu’un vrai ticket a déjà été créé.

La trajectoire d’action peut être évaluée avec des règles déterministes comparant les événements Agent/Tool/Policy/Trace attendus et observés, puis les réponses plus ouvertes peuvent être jugées par des humains ou un Judge préalablement calibré. Il est possible de s’inspirer des [métriques Agent/Tool de Ragas](https://docs.ragas.io/en/latest/concepts/metrics/available_metrics/) ou de la [documentation LangSmith sur les types d’évaluation](https://docs.langchain.com/langsmith/evaluation-types/) pour concevoir les cas, sans devoir migrer obligatoirement le runtime vers ces frameworks. Les performances doivent également inclure le taux de succès des requêtes, la latence p50/p95, le nombre d’appels modèle et Tool ainsi que le coût, puis être revérifiées dans des scénarios de timeout des dépendances, de retrieval vide et d’échec partiel en multi-Agent.

## 7. Modèle pour enregistrer de nouveaux résultats

Chaque fois qu’une baseline reproductible ou une comparaison importante est obtenue, ajoutez un court résumé dans ce document et conservez les détails cas par cas dans un fichier JSON séparé. N’écrasez pas les anciens résultats et n’écrivez jamais de vraie API Key, d’information client ou de conversation non anonymisée dans les rapports.

```text
Date / version du code :
Objectif de l’évaluation et statut actuel/futur :
Version du dataset, nombre de cas et méthode d’annotation :
Knowledge Base et version du chunking/Embedding :
Modèle, fournisseur, paramètres de sampling et options activées :
Commande ou requête exécutée, chemin du rapport :
Nombre de cas valides, erreurs d’exécution, échecs du Judge :
Métriques par couche et échecs par classe/scénario :
Évolution par rapport à l’ancienne version et comparabilité :
Conclusion de la vérification humaine, limites connues et prochaine étape :
```