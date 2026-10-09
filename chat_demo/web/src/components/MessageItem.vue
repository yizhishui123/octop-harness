<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import ToolCallCard from './ToolCallCard.vue'
import type { ChatMessage } from '../types'
import { renderMarkdown } from '../markdown'
import { formatDuration, formatTokens } from '../utils'

const props = defineProps<{ message: ChatMessage }>()

const showReasoning = ref(false)
const now = ref(Date.now())
let timer: number | null = null

/** Live-tick only while the reasoning block is still growing. */
function syncTimer(): void {
  const active = !!props.message.reasoning && !props.message.reasoningEndedAt
  if (active && timer === null) {
    timer = window.setInterval(() => {
      now.value = Date.now()
    }, 500)
  } else if (!active && timer !== null) {
    window.clearInterval(timer)
    timer = null
  }
}

watch(() => [props.message.reasoning, props.message.reasoningEndedAt], syncTimer, { immediate: true })
onBeforeUnmount(() => {
  if (timer !== null) window.clearInterval(timer)
})

const isUser = computed(() => props.message.role === 'user')
const isNotice = computed(() => props.message.notice === true)
const showStreamDot = computed(() => props.message.streaming === true)

const reasoningSeconds = computed(() => {
  const start = props.message.reasoningStartedAt
  if (!start) return 0
  const end = props.message.reasoningEndedAt ?? now.value
  return Math.max(0, end - start) / 1000
})

const reasoningLabel = computed(() => {
  const start = props.message.reasoningStartedAt
  if (!start) return '💭 Thought'
  if (props.message.reasoningEndedAt) return `💭 Thought for ${reasoningSeconds.value.toFixed(1)}s`
  return `💭 Thinking… ${reasoningSeconds.value.toFixed(1)}s`
})

const rendered = computed(() => (props.message.streaming ? '' : renderMarkdown(props.message.content)))

const stats = computed(() => {
  const parts: string[] = []
  if (props.message.usage) {
    parts.push(`↑ ${formatTokens(props.message.usage.input)} ↓ ${formatTokens(props.message.usage.output)} tokens`)
  }
  if (props.message.durationMs !== undefined) parts.push(formatDuration(props.message.durationMs))
  if (props.message.stopped) parts.push('已停止')
  return parts
})
</script>

<template>
  <div class="msg" :class="[`role-${message.role}`, { notice: isNotice }]">
    <template v-if="isNotice">
      <div class="notice-line mono">{{ message.content }}</div>
    </template>

    <template v-else-if="isUser">
      <div class="bubble">{{ message.content }}</div>
    </template>

    <template v-else>
      <div class="head">
        <span class="dot" :class="{ live: showStreamDot }">●</span>
        <span class="who mono">assistant</span>
        <span v-if="message.error" class="err-flag">error</span>
      </div>

      <button v-if="message.reasoning" class="reasoning-toggle" type="button" @click="showReasoning = !showReasoning">
        <span>{{ reasoningLabel }}</span>
        <span class="chev">{{ showReasoning ? '▾' : '▸' }}</span>
      </button>
      <pre v-if="message.reasoning && showReasoning" class="reasoning-body mono">{{ message.reasoning }}</pre>

      <div
        v-if="message.content || showStreamDot"
        class="body"
        :class="{ plain: showStreamDot }"
      >
        <span v-if="showStreamDot" class="caret">●</span>
        <span v-if="showStreamDot">{{ message.content }}</span>
        <div v-else class="md-body" v-html="rendered" />
      </div>

      <div v-if="message.toolCalls.length" class="tools">
        <ToolCallCard v-for="call in message.toolCalls" :key="call.id" :call="call" />
      </div>

      <div v-if="message.error" class="error-bar mono">⚠ {{ message.error }}</div>

      <div v-if="stats.length" class="stats mono">
        <span v-for="(part, index) in stats" :key="part">
          <span v-if="index > 0" class="sep">│</span>{{ part }}
        </span>
      </div>
    </template>
  </div>
</template>

<style scoped>
.msg {
  margin: 0 0 18px;
}

.role-user {
  display: flex;
  justify-content: flex-end;
}

.bubble {
  max-width: min(680px, 82%);
  padding: 8px 12px;
  background: #1b2430;
  border: 1px solid var(--border-strong);
  border-radius: var(--radius);
  white-space: pre-wrap;
  word-break: break-word;
}

.notice {
  display: flex;
  justify-content: center;
}

.notice-line {
  max-width: 100%;
  padding: 3px 10px;
  color: var(--text-faint);
  font-size: 12px;
  border-left: 2px solid var(--border-strong);
  background: #11161d;
  border-radius: 4px;
  white-space: pre-wrap;
  word-break: break-word;
}

.head {
  display: flex;
  align-items: center;
  gap: 7px;
  margin-bottom: 3px;
}

.dot {
  color: var(--green);
  font-size: 10px;
  line-height: 1;
}

.dot.live {
  animation: chat-pulse 1.1s ease-in-out infinite;
}

.who {
  font-size: 11.5px;
  color: var(--text-faint);
  letter-spacing: 0.04em;
}

.err-flag {
  font-size: 10.5px;
  color: var(--red);
  border: 1px solid #6e2b28;
  border-radius: 999px;
  padding: 0 5px;
}

.reasoning-toggle {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 2px 0;
  color: var(--text-dim);
  font-size: 12px;
}

.reasoning-toggle:hover {
  color: var(--text);
}

.chev {
  font-size: 10px;
}

.reasoning-body {
  margin: 4px 0 8px;
  padding: 8px 10px;
  max-height: 260px;
  overflow: auto;
  background: #0e1319;
  border: 1px dashed var(--border-strong);
  border-radius: var(--radius-sm);
  color: var(--text-dim);
  font-size: 12px;
  line-height: 1.55;
  white-space: pre-wrap;
  word-break: break-word;
}

.body.plain {
  white-space: pre-wrap;
  word-break: break-word;
}

.caret {
  color: var(--green);
  font-size: 10px;
  margin-right: 6px;
  animation: chat-pulse 1.1s ease-in-out infinite;
}

.tools {
  margin-top: 4px;
}

.error-bar {
  margin: 6px 0 0;
  padding: 6px 10px;
  background: #2a1616;
  border: 1px solid #6e2b28;
  border-radius: var(--radius-sm);
  color: #ff9d94;
  font-size: 12.5px;
  white-space: pre-wrap;
  word-break: break-word;
}

.stats {
  display: flex;
  gap: 6px;
  margin-top: 6px;
  color: var(--text-faint);
  font-size: 11px;
}

.sep {
  margin-right: 6px;
  opacity: 0.6;
}
</style>
