<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import MessageItem from './MessageItem.vue'
import ApprovalCard from './ApprovalCard.vue'
import { useChatStore } from '../stores/chat'
import { useAppStore } from '../stores/app'
import type { Decision } from '../types'

const chat = useChatStore()
const app = useAppStore()

const scroller = ref<HTMLElement | null>(null)
const follow = ref(true)

/** Any change that should push the viewport down while following. */
const tailSignal = computed(() => {
  const list = chat.messages
  const last = list[list.length - 1]
  if (!last) return '0:0:0'
  const toolBits = last.toolCalls.reduce((sum, call) => sum + call.argsText.length + (call.result?.length ?? 0), 0)
  return `${list.length}:${last.content.length}:${toolBits}:${last.reasoning?.length ?? 0}`
})

watch(tailSignal, async () => {
  if (!follow.value) return
  await nextTick()
  scrollToBottom()
})

watch(
  () => chat.activeThreadId,
  () => {
    follow.value = true
    void nextTick(() => scrollToBottom())
  },
)

function onScroll(): void {
  const el = scroller.value
  if (!el) return
  follow.value = el.scrollHeight - el.scrollTop - el.clientHeight < 80
}

function scrollToBottom(): void {
  const el = scroller.value
  if (!el) return
  el.scrollTop = el.scrollHeight
}

function onDecisions(decisions: Decision[]): void {
  void chat.resume(decisions)
}

const hasMessages = computed(() => chat.messages.length > 0)
</script>

<template>
  <div class="list-wrap">
    <div ref="scroller" class="list" @scroll.passive="onScroll">
      <div v-if="!hasMessages" class="welcome">
        <div class="welcome-mark mono">●</div>
        <h1 class="welcome-title">octop-harness chat demo</h1>
        <p class="welcome-sub">
          HarnessAgentManager 驱动的 SSE 聊天界面。选择左侧会话或直接输入开始对话。
        </p>
        <ul class="welcome-tips mono">
          <li><span class="key">Enter</span> 发送 · <span class="key">Shift+Enter</span> 换行</li>
          <li><span class="key">/</span> 打开命令面板（/model · /skills · /stop · /new · /clear · /help）</li>
          <li>工具调用、思维链与上下文用量会随流式事件实时展示</li>
        </ul>
        <p v-if="app.agentsError" class="welcome-error mono">无法连接后端: {{ app.agentsError }}</p>
        <p v-else-if="!app.loadingAgents && app.agents.length === 0" class="welcome-error mono">
          没有可用 agent —— 检查 chat_demo/agents.json 是否配置正确。
        </p>
      </div>

      <div v-else class="stream">
        <MessageItem v-for="message in chat.messages" :key="message.id" :message="message" />
        <ApprovalCard v-if="chat.visibleHitl" :request="chat.visibleHitl" @submit="onDecisions" />
      </div>
    </div>

    <button v-if="!follow && hasMessages" class="jump mono" type="button" @click="((follow = true), scrollToBottom())">
      ↓ 最新
    </button>
  </div>
</template>

<style scoped>
.list-wrap {
  position: relative;
  flex: 1;
  min-height: 0;
}

.list {
  height: 100%;
  overflow-y: auto;
  padding: 22px 28px 12px;
}

.stream {
  max-width: 940px;
  margin: 0 auto;
}

.welcome {
  max-width: 620px;
  margin: 8vh auto 0;
  text-align: left;
}

.welcome-mark {
  color: var(--green);
  font-size: 26px;
  animation: chat-pulse 1.6s ease-in-out infinite;
}

.welcome-title {
  margin: 10px 0 6px;
  font-size: 22px;
  font-weight: 600;
  letter-spacing: -0.01em;
}

.welcome-sub {
  margin: 0 0 18px;
  color: var(--text-dim);
}

.welcome-tips {
  margin: 0;
  padding: 14px 16px;
  list-style: none;
  background: #10161e;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  color: var(--text-dim);
  font-size: 12.5px;
}

.welcome-tips li + li {
  margin-top: 6px;
}

.key {
  display: inline-block;
  padding: 0 5px;
  border: 1px solid var(--border-strong);
  border-radius: 4px;
  background: #161b22;
  color: var(--text);
  font-size: 11.5px;
}

.welcome-error {
  margin-top: 16px;
  padding: 8px 10px;
  background: #2a1616;
  border: 1px solid #6e2b28;
  border-radius: var(--radius-sm);
  color: #ff9d94;
  font-size: 12.5px;
}

.jump {
  position: absolute;
  right: 26px;
  bottom: 16px;
  padding: 4px 10px;
  border: 1px solid var(--border-strong);
  border-radius: 999px;
  background: var(--bg-elevated);
  color: var(--text-dim);
  font-size: 11.5px;
  box-shadow: 0 4px 14px rgba(0, 0, 0, 0.45);
}

.jump:hover {
  color: var(--text);
  border-color: #4a5563;
}
</style>
