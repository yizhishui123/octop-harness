<script setup lang="ts">
import { computed } from 'vue'
import { useAppStore } from '../stores/app'
import { useChatStore } from '../stores/chat'
import { formatDayTime } from '../utils'

const app = useAppStore()
const chat = useChatStore()

const agentName = computed(() => app.activeAgent?.name ?? '—')

function agentLabel(agentId: string): string {
  return app.agents.find((agent) => agent.agent_id === agentId)?.name ?? agentId.slice(0, 6)
}

function onAgentChange(event: Event): void {
  const value = (event.target as HTMLSelectElement).value
  const previousAgent = chat.activeSession?.agent_id ?? null
  app.setActiveAgent(value)
  if (previousAgent && previousAgent !== value) chat.newSession()
}

async function open(threadId: string): Promise<void> {
  await chat.switchSession(threadId)
}

function remove(threadId: string, event: MouseEvent): void {
  event.stopPropagation()
  chat.deleteSession(threadId)
}

function create(): void {
  chat.newSession()
}
</script>

<template>
  <aside class="sidebar">
    <div class="brand">
      <span class="brand-mark mono">●</span>
      <span class="brand-text">octop-harness</span>
      <span class="brand-sub mono">chat demo</span>
    </div>

    <div class="agent">
      <label class="agent-label mono" for="agent-select">agent</label>
      <select id="agent-select" class="agent-select" :value="app.activeAgentId ?? ''" @change="onAgentChange">
        <option v-if="app.agents.length === 0" value="" disabled>未检测到 agent</option>
        <option v-for="agent in app.agents" :key="agent.agent_id" :value="agent.agent_id">
          {{ agent.name }}
        </option>
      </select>
      <div class="agent-meta mono">{{ app.agents.length }} 个 agent · 当前 {{ agentName }}</div>
    </div>

    <button class="new-btn" type="button" :disabled="chat.streaming" @click="create">
      <span class="plus">+</span> 新建会话
    </button>

    <div class="section mono">sessions</div>

    <div class="sessions">
      <button
        v-for="session in chat.sortedSessions"
        :key="session.thread_id"
        type="button"
        class="session"
        :class="{ active: session.thread_id === chat.activeThreadId }"
        @click="open(session.thread_id)"
      >
        <span class="session-main">
          <span class="session-title">{{ session.title || '新会话' }}</span>
          <span class="session-meta mono">
            {{ formatDayTime(session.updateTime) }} · {{ agentLabel(session.agent_id) }}
          </span>
        </span>
        <span class="session-delete" title="删除会话" @click="remove(session.thread_id, $event)">✕</span>
      </button>
      <div v-if="chat.sortedSessions.length === 0" class="empty mono">暂无会话</div>
    </div>

    <div class="foot mono">
      <span v-if="app.agentsError" class="offline">后端离线</span>
      <span v-else>SSE · /api</span>
    </div>
  </aside>
</template>

<style scoped>
.sidebar {
  display: flex;
  flex-direction: column;
  width: var(--sidebar-width);
  min-width: var(--sidebar-width);
  height: 100%;
  padding: 14px 12px 10px;
  background: var(--bg-panel);
  border-right: 1px solid var(--border);
}

.brand {
  display: flex;
  align-items: baseline;
  gap: 6px;
  padding: 0 4px 12px;
}

.brand-mark {
  color: var(--green);
  font-size: 12px;
}

.brand-text {
  font-weight: 600;
  letter-spacing: -0.01em;
}

.brand-sub {
  color: var(--text-faint);
  font-size: 11px;
}

.agent {
  padding: 0 4px 12px;
}

.agent-label,
.section {
  display: block;
  color: var(--text-faint);
  font-size: 10.5px;
  letter-spacing: 0.09em;
  text-transform: uppercase;
}

.agent-select {
  width: 100%;
  margin-top: 5px;
}

.agent-meta {
  margin-top: 5px;
  color: var(--text-faint);
  font-size: 10.5px;
}

.new-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  width: 100%;
  padding: 7px 10px;
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-sm);
  background: var(--bg-elevated);
  font-size: 13px;
}

.new-btn:hover:not(:disabled) {
  background: var(--bg-hover);
  border-color: #3d444d;
}

.new-btn:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.plus {
  color: var(--green);
}

.section {
  margin: 16px 4px 6px;
}

.sessions {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  margin: 0 -4px;
  padding: 0 4px;
}

.session {
  display: flex;
  align-items: center;
  gap: 6px;
  width: 100%;
  padding: 6px 8px;
  border-radius: var(--radius-sm);
  text-align: left;
}

.session:hover {
  background: var(--bg-hover);
}

.session.active {
  background: var(--bg-active);
  box-shadow: inset 2px 0 0 var(--accent);
}

.session-main {
  display: flex;
  flex-direction: column;
  min-width: 0;
  flex: 1;
}

.session-title {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 13px;
}

.session-meta {
  color: var(--text-faint);
  font-size: 10.5px;
}

.session-delete {
  color: var(--text-faint);
  font-size: 11px;
  padding: 0 3px;
  opacity: 0;
}

.session:hover .session-delete {
  opacity: 1;
}

.session-delete:hover {
  color: var(--red);
}

.empty {
  padding: 6px 8px;
  color: var(--text-faint);
  font-size: 11.5px;
}

.foot {
  padding: 8px 4px 0;
  border-top: 1px solid var(--border);
  color: var(--text-faint);
  font-size: 10.5px;
}

.offline {
  color: var(--red);
}
</style>
