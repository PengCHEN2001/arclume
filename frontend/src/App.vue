<template>
  <main class="app-shell">
    <header class="topbar">
      <div class="topbar-brand">
        <div class="brand-mark">A</div>
        <strong>Arclume</strong>
      </div>
      <nav class="topnav" aria-label="Main navigation">
        <button :class="['nav-item', { active: activeTab === 'conversation' }]" @click="navigateTo('conversation')">{{ text('Conversation', '对话') }}</button>
        <button :class="['nav-item', { active: activeTab === 'knowledge' }]" @click="navigateTo('knowledge')">{{ text('Knowledge Base', '知识库') }}</button>
        <button :class="['nav-item', { active: activeTab === 'evaluation' }]" @click="navigateTo('evaluation')">{{ text('Evaluation', '评测') }}</button>
      </nav>
      <div class="topbar-actions">
        <span class="runtime-indicator"><span :class="['status-dot', healthOk ? 'online' : 'offline']"></span> Python</span>
        <a href="http://127.0.0.1:8000/docs" target="_blank" rel="noreferrer">API Docs</a>
        <button class="language-toggle" @click="toggleLocale">{{ locale === 'en' ? '中文' : 'EN' }}</button>
        <div class="avatar">CP</div>
      </div>
    </header>

    <section v-if="activeTab === 'conversation'" class="workspace">
      <header class="workspace-header">
        <div>
          <p class="eyebrow">Conversation Lab</p>
          <h1>{{ text('Customer Support Agent', '客服 Agent 对话') }}</h1>
          <p class="muted">{{ text('Send a request, inspect intent routing, and review the generated response.', '发送一条请求，查看意图识别、Agent 路由与生成回复。') }}</p>
        </div>
        <div class="workspace-actions">
          <span v-if="conversationId" class="conversation-id">{{ conversationId }}</span>
          <button class="clear-button" @click="startNewConversation">{{ text('Clear', '清空') }}</button>
        </div>
      </header>

      <section class="dashboard-grid">
        <section class="main-column">
          <article id="conversation" class="chat-panel panel">
            <div class="chat-toolbar">
              <div class="endpoint"><span :class="['status-dot', healthOk ? 'online' : 'offline']"></span><span>/chat · FastAPI</span></div>
              <div class="toolbar-right"><span class="route-chip">{{ latest.primaryAgent || 'Orchestrator' }}</span><span class="message-count">{{ messages.length }} {{ text('messages', '条消息') }}</span></div>
            </div>
            <div ref="messageList" class="messages">
              <div v-if="messages.length === 0" class="empty-state">
                <div class="empty-icon">A</div>
                <h3>{{ text('Start a support conversation', '开始一次客服对话') }}</h3>
                <p>{{ text('Try “I want a refund” or “I get a 401 error when signing in.”', '试试输入“我想申请退款”或“登录时出现 401 错误”。') }}</p>
              </div>
              <article v-for="item in messages" :key="item.id" :class="['message', item.role]">
                <div class="message-meta">
                  <span>{{ item.role === 'user' ? text('You', '用户') : 'Arclume Agent' }}</span>
                  <small v-if="item.meta">{{ item.meta }}</small>
                </div>
                <p>{{ item.content }}</p>
              </article>
            </div>
            <form class="composer" @submit.prevent="sendMessage">
              <textarea v-model="draft" rows="3" :placeholder="text('Type a customer request...', '输入一个客服问题...')" @keydown.enter.exact.prevent="sendMessage"></textarea>
              <div class="composer-footer">
                <span class="muted">{{ text('⌘ / Ctrl + Enter to send', '⌘ / Ctrl + Enter 发送') }}</span>
                <button class="primary-button" :disabled="busy || !draft.trim()">{{ busy ? text('Sending...', '发送中...') : text('Send', '发送') }}</button>
              </div>
            </form>
          </article>

        </section>

        <aside class="right-rail">
          <article class="rail-panel panel connection-panel">
            <div class="panel-heading"><div><p class="eyebrow">Connection</p><h2>{{ text('Connection settings', '连接配置') }}</h2></div><strong :class="healthOk ? 'ok' : 'rail-muted'">{{ healthOk ? 'ok' : '—' }}</strong></div>
            <div class="backend-switch"><span>Python</span><span class="selected-backend">FastAPI</span></div>
            <label><span>{{ text('User ID', '用户 ID') }}</span><input v-model="userId" placeholder="u1001" /></label>
            <label><span>{{ text('Conversation ID', '会话 ID') }}</span><input v-model="conversationId" :placeholder="text('Generated after first message', '发送后自动生成')" /></label>
            <div class="actions"><button class="primary-button" @click="refreshStatus" :disabled="loadingStatus">{{ loadingStatus ? text('Checking...', '检查中...') : text('Check connection', '检查连接') }}</button><button class="secondary-button" @click="refreshStatus">{{ text('Refresh', '刷新') }}</button></div>
          </article>

          <article id="trace" class="rail-panel panel trace-panel">
            <div class="panel-heading"><div><p class="eyebrow">Last Trace</p><h2>{{ text('Latest request', '最近一次请求') }}</h2></div><span :class="['trace-light', healthOk ? 'online' : 'offline']"></span></div>
            <div class="trace-highlight"><span>{{ text('Routing confidence', '路由置信度') }}</span><strong>{{ latest.intent ? '—' : '—' }}</strong></div>
            <dl class="details-list">
              <div><dt>{{ text('Primary Agent', '主 Agent') }}</dt><dd>{{ latest.primaryAgent || '—' }}</dd></div>
              <div><dt>{{ text('Intent', '意图') }}</dt><dd>{{ latest.intent || '—' }}</dd></div>
              <div><dt>{{ text('Supporting', '辅助 Agent') }}</dt><dd>{{ latest.supportingAgents || '—' }}</dd></div>
              <div><dt>{{ text('Tools', '工具') }}</dt><dd>{{ latest.tools || '—' }}</dd></div>
              <div><dt>{{ text('Escalated', '转人工') }}</dt><dd>{{ latest.escalated ? text('Yes', '是') : text('No', '否') }}</dd></div>
            </dl>
          </article>

          <article class="rail-panel panel runtime-panel">
            <div class="panel-heading"><div><p class="eyebrow">Runtime</p><h2>{{ text('Runtime status', '运行状态') }}</h2></div><button class="mini-button" @click="refreshStatus">{{ text('Refresh', '刷新') }}</button></div>
            <div class="runtime-grid">
              <div><strong>{{ knowledgeCount }}</strong><span>{{ text('chunks', '知识片段') }}</span></div>
              <div><strong>{{ statusLabel(modelStatus) }}</strong><span>{{ text('model', '模型') }}</span></div>
              <div><strong>{{ statusLabel(monitorStatus) }}</strong><span>Monitor</span></div>
            </div>
            <div class="runtime-bar"><span :style="{ width: monitorStatus === 'Active' ? '76%' : '18%' }"></span></div>
          </article>
        </aside>
      </section>
    </section>

    <section v-else-if="activeTab === 'knowledge'" class="workspace page-workspace knowledge-page">
      <header class="page-hero">
        <div>
          <p class="eyebrow">Knowledge Base</p>
          <h1>{{ text('Knowledge Base', '知识库') }}</h1>
          <p class="muted">{{ text('Search, add, and maintain the knowledge used by Arclume Agents.', '搜索、补充和维护 Arclume Agent 使用的知识片段。') }}</p>
        </div>
        <div class="page-count"><strong>{{ knowledgeCount }}</strong><span>chunks</span></div>
      </header>

      <section class="knowledge-grid">
        <article class="page-card panel">
          <div class="panel-heading"><div><p class="eyebrow">Retrieval</p><h2>{{ text('Search knowledge', '检索知识') }}</h2></div><span class="pill">GET /search</span></div>
          <div class="large-search"><input v-model="searchQuery" :placeholder="text('How long does a refund take?', '退款多久能到账')" @keydown.enter="searchKnowledge" /><button class="primary-button" @click="searchKnowledge" :disabled="searching || !searchQuery.trim()">{{ searching ? '...' : text('Search', '搜索') }}</button></div>
          <div v-if="searchResults.length === 0" class="page-empty">{{ text('Enter a customer question to search.', '输入客户问题开始搜索。') }}</div>
          <article v-for="item in searchResults" :key="item.id || item.title" class="knowledge-result">
            <div class="result-title"><strong>{{ item.title || text('Untitled document', '未命名文档') }}</strong><span>{{ formatScore(item.score) }}</span></div>
            <p>{{ item.content }}</p>
          </article>
        </article>

        <article class="page-card panel ingestion-card">
          <div class="panel-heading"><div><p class="eyebrow">Ingestion</p><h2>{{ text('Add knowledge', '添加知识') }}</h2></div><span class="pill soft">ChromaDB</span></div>
          <label><span>{{ text('Title', '标题') }}</span><input v-model="docTitle" :placeholder="text('Refund policy update', '退款补充政策')" /></label>
          <label><span>{{ text('Content', '内容') }}</span><textarea v-model="docContent" rows="6" :placeholder="text('Enter content for the knowledge base', '输入要加入知识库的内容')"></textarea></label>
          <div class="actions"><button class="primary-button" @click="addDocument" :disabled="ingesting || !docTitle.trim() || !docContent.trim()">{{ ingesting ? text('Adding...', '处理中...') : text('Add document', '添加文档') }}</button><label class="file-button">{{ text('Upload file', '上传文件') }}<input type="file" accept=".txt,.md,.json" @change="handleUpload" /></label></div>
          <p v-if="ingestMessage" class="ingest-message">{{ ingestMessage }}</p>
        </article>
      </section>

      <section class="skills-panel panel">
        <div class="panel-heading"><div><p class="eyebrow">Loaded Skills</p><h2>{{ text('Loaded skills', '已加载能力') }}</h2></div><button class="mini-button" @click="reloadSkillList" :disabled="skillsLoading">{{ skillsLoading ? text('Loading...', '加载中...') : text('Reload', '重新加载') }}</button></div>
        <div v-if="skills.length === 0" class="page-empty">{{ skillsMessage || text('No Skills loaded yet.', '暂未加载 Skills。') }}</div>
        <div v-for="skill in skills" :key="skill.name" class="skill-row">
          <span class="skill-dot"></span><strong>{{ skill.name }}</strong><p>{{ skill.description || text('Runtime instruction set for the Agent.', 'Agent 的运行规范。') }}</p><small>{{ skill.content_chars || 0 }} chars</small>
        </div>
      </section>
    </section>

    <section v-else class="workspace page-workspace evaluation-page">
      <header class="page-hero evaluation-hero">
        <div>
          <p class="eyebrow">Evaluation Lab</p>
          <h1>{{ text('Agent Evaluation', '评测 Agent') }}</h1>
          <p class="muted">{{ text('Run the FastAPI evaluation suite and inspect intent, dialog quality, and regression results.', '运行 FastAPI 内置评测，查看意图识别、对话质量与回归结果。') }}</p>
        </div>
        <button class="primary-button hero-button" @click="runEvaluation" :disabled="evaluationBusy">{{ evaluationBusy ? text('Running...', '评测中...') : text('Run evaluation', '运行评测') }}</button>
      </header>

      <section class="eval-stat-grid">
        <article class="stat-card featured"><span>Pass rate</span><strong>{{ evaluationResult ? formatPercent(evaluationResult.pass_rate) : '—' }}</strong><small v-if="evaluationResult">{{ evaluationResult.passed }} / {{ evaluationResult.total }} cases passed</small><small v-else>{{ text('Run an evaluation to generate a report.', '运行评测后生成报告。') }}</small></article>
        <article class="stat-card"><span>{{ text('Passed', '通过') }}</span><strong>{{ evaluationResult?.passed ?? '—' }}</strong></article>
        <article class="stat-card"><span>{{ text('Total cases', '总数') }}</span><strong>{{ evaluationResult?.total ?? '—' }}</strong></article>
        <article class="stat-card"><span>{{ text('Regressions', '回归') }}</span><strong>{{ evaluationResult?.regressions?.length ?? '—' }}</strong></article>
      </section>

      <section class="eval-content-grid">
        <article class="eval-card panel">
          <div class="panel-heading"><div><p class="eyebrow">Scores</p><h2>{{ text('Average scores', '平均评分') }}</h2></div></div>
          <div v-if="!evaluationResult" class="page-empty">{{ text('Evaluation scores will appear here.', '评测得分会显示在这里。') }}</div>
          <div v-for="(score, name) in (evaluationResult?.avg_scores || {})" :key="name" class="score-row"><span>{{ name }}</span><div class="score-track"><i :style="{ width: `${Math.round(score * 100)}%` }"></i></div><strong>{{ Number(score).toFixed(2) }}</strong></div>
        </article>
        <article class="eval-card panel">
          <div class="panel-heading"><div><p class="eyebrow">Recommendations</p><h2>{{ text('Optimization suggestions', '优化建议') }}</h2></div></div>
          <div v-if="evaluationResult?.recommendations?.length" class="recommendation-list"><p v-for="item in evaluationResult.recommendations" :key="item">{{ item }}</p></div>
          <div v-else class="page-empty">{{ evaluationMessage || text('Run the evaluation suite to receive recommendations.', '运行评测后查看优化建议。') }}</div>
        </article>
      </section>
    </section>
  </main>
</template>

<script setup>
import { nextTick, onMounted, reactive, ref } from 'vue'
import {
  addKnowledge,
  getHealth,
  getKnowledgeStats,
  getMonitor,
  getSkills,
  reloadSkills,
  runEvaluation as requestEvaluation,
  sendChat,
  searchKnowledge as fetchKnowledge,
  uploadKnowledge
} from './api'

const userId = ref('u1001')
const conversationId = ref('')
const locale = ref('en')
const activeTab = ref('conversation')
const draft = ref('')
const messages = ref([])
const busy = ref(false)
const messageList = ref(null)

const healthOk = ref(false)
const healthLabel = ref('未检查')
const loadingStatus = ref(false)
const knowledgeCount = ref('-')
const modelStatus = ref('—')
const monitorStatus = ref('—')
const monitorSummary = ref(null)
const skills = ref([])
const skillsLoading = ref(false)
const skillsMessage = ref('')

const searchQuery = ref('How long does a refund take?')
const searchResults = ref([])
const searching = ref(false)
const docTitle = ref('Refund policy update')
const docContent = ref('Refund reviews may take 3-5 business days during peak periods.')
const ingesting = ref(false)
const ingestMessage = ref('')
const evaluationBusy = ref(false)
const evaluationResult = ref(null)
const evaluationMessage = ref('')

const latest = reactive({
  intent: '',
  primaryAgent: '',
  supportingAgents: '',
  tools: '',
  escalated: false
})

function text(english, chinese) {
  return locale.value === 'en' ? english : chinese
}

function toggleLocale() {
  locale.value = locale.value === 'en' ? 'zh' : 'en'
}

function navigateTo(tabName) {
  activeTab.value = tabName
  const target = tabName === 'conversation' ? '#conversation' : tabName === 'knowledge' ? '#knowledge' : '#evaluation'
  document.querySelector(target)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

function statusLabel(value) {
  const labels = {
    'Not checked': '未检查',
    Healthy: '服务正常',
    'Service error': '服务异常',
    'Backend unavailable': '后端不可用',
    Configured: '已配置',
    'Not configured': '未配置',
    Unavailable: '不可用',
    Active: '运行中',
    Inactive: '未启动'
  }
  return locale.value === 'en' ? value : (labels[value] || value)
}

onMounted(() => {
  refreshStatus()
  loadSkills()
})

async function refreshStatus() {
  loadingStatus.value = true
  try {
    const [healthResult, statsResult, monitorResult] = await Promise.allSettled([
      getHealth(),
      getKnowledgeStats(),
      getMonitor()
    ])
    if (healthResult.status === 'fulfilled') {
      const health = healthResult.value
      healthOk.value = health?.status === 'ok'
      healthLabel.value = healthOk.value ? 'Healthy' : (health?.status || 'Service error')
      modelStatus.value = health?.llm_configured ? 'Configured' : 'Not configured'
    } else {
      healthOk.value = false
      healthLabel.value = 'Backend unavailable'
      modelStatus.value = 'Unavailable'
    }
    if (statsResult.status === 'fulfilled') {
      knowledgeCount.value = statsResult.value?.total_chunks ?? '-'
    }
    if (monitorResult.status === 'fulfilled') {
      monitorSummary.value = monitorResult.value
      monitorStatus.value = monitorResult.value?.active ? 'Active' : 'Inactive'
    } else {
      monitorStatus.value = 'Unavailable'
    }
  } catch (error) {
    healthOk.value = false
    healthLabel.value = 'Backend unavailable'
    modelStatus.value = 'Unavailable'
    monitorStatus.value = 'Unavailable'
  } finally {
    loadingStatus.value = false
  }
}

async function loadSkills() {
  skillsLoading.value = true
  skillsMessage.value = ''
  try {
    const result = await getSkills()
    skills.value = result?.skills || []
  } catch (error) {
    skillsMessage.value = error.message
  } finally {
    skillsLoading.value = false
  }
}

async function reloadSkillList() {
  skillsLoading.value = true
  skillsMessage.value = ''
  try {
    const result = await reloadSkills()
    skills.value = (result?.skills || []).map((name) => ({ name }))
    await loadSkills()
  } catch (error) {
    skillsMessage.value = error.message
  } finally {
    skillsLoading.value = false
  }
}

function startNewConversation() {
  conversationId.value = ''
  messages.value = []
  latest.intent = ''
  latest.primaryAgent = ''
  latest.supportingAgents = ''
  latest.tools = ''
  latest.escalated = false
}

async function sendMessage() {
  const content = draft.value.trim()
  if (!content || busy.value) return

  messages.value.push({ id: crypto.randomUUID(), role: 'user', content })
  draft.value = ''
  busy.value = true

  try {
    const result = await sendChat({
      message: content,
      userId: userId.value,
      conversationId: conversationId.value
    })
    conversationId.value = result.conversation_id || conversationId.value
    latest.intent = result.intent || ''
    latest.primaryAgent = result.primary_agent || ''
    latest.supportingAgents = result.supporting_agents?.join(', ') || ''
    latest.tools = result.tools_used?.join(', ') || ''
    latest.escalated = Boolean(result.escalated)
    messages.value.push({
      id: crypto.randomUUID(),
      role: 'assistant',
      content: result.message || '后端没有返回消息。',
      meta: [result.intent, result.primary_agent].filter(Boolean).join(' · ')
    })
  } catch (error) {
    messages.value.push({
      id: crypto.randomUUID(),
      role: 'assistant',
      content: error.message,
      meta: '请求失败'
    })
  } finally {
    busy.value = false
    await nextTick()
    messageList.value?.scrollTo({ top: messageList.value.scrollHeight, behavior: 'smooth' })
  }
}

async function searchKnowledge() {
  if (!searchQuery.value.trim() || searching.value) return
  searching.value = true
  try {
    const result = await fetchKnowledge(searchQuery.value.trim(), 5)
    searchResults.value = result?.results || []
  } catch (error) {
    searchResults.value = [{ title: '检索失败', content: error.message }]
  } finally {
    searching.value = false
  }
}

async function addDocument() {
  if (!docTitle.value.trim() || !docContent.value.trim() || ingesting.value) return
  ingesting.value = true
  ingestMessage.value = ''
  try {
    const result = await addKnowledge({
      title: docTitle.value.trim(),
      content: docContent.value.trim()
    })
    ingestMessage.value = result?.message || '文档已加入知识库。'
    await refreshStatus()
  } catch (error) {
    ingestMessage.value = error.message
  } finally {
    ingesting.value = false
  }
}

async function handleUpload(event) {
  const file = event.target.files?.[0]
  event.target.value = ''
  if (!file || ingesting.value) return
  ingesting.value = true
  ingestMessage.value = ''
  try {
    const result = await uploadKnowledge(file)
    ingestMessage.value = result?.message || `${file.name} 已加入知识库。`
    await refreshStatus()
  } catch (error) {
    ingestMessage.value = error.message
  } finally {
    ingesting.value = false
  }
}

async function runEvaluation() {
  if (evaluationBusy.value) return
  evaluationBusy.value = true
  evaluationMessage.value = ''
  try {
    evaluationResult.value = await requestEvaluation()
  } catch (error) {
    evaluationMessage.value = error.message
  } finally {
    evaluationBusy.value = false
  }
}

function formatScore(score) {
  return typeof score === 'number' ? score.toFixed(3) : '—'
}

function formatPercent(value) {
  return typeof value === 'number' ? `${(value * 100).toFixed(1)}%` : '—'
}
</script>
