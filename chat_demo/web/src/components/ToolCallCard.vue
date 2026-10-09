<script setup lang="ts">
import { computed, ref } from 'vue'
import type { ToolCallItem } from '../types'
import { formatDuration, parseJsonLoose, stringify } from '../utils'

const props = defineProps<{ call: ToolCallItem }>()

const expanded = ref(false)

const hasTiming = computed(() => props.call.endedAt !== undefined && props.call.startedAt > 0)

const elapsed = computed(() => {
  if (!hasTiming.value) return ''
  return formatDuration(Math.max(0, (props.call.endedAt ?? 0) - props.call.startedAt))
})

const statusIcon = computed(() => {
  if (props.call.status === 'running') return '◐'
  return props.call.status === 'error' ? '✗' : '✓'
})

const prettyArgs = computed(() => {
  const parsed = parseJsonLoose(props.call.argsText)
  return parsed === undefined ? props.call.argsText : stringify(parsed)
})

const hasDetails = computed(() => prettyArgs.value.length > 0 || !!props.call.result || !!props.call.error)
</script>

<template>
  <div class="tool-card" :class="[`is-${call.status}`, { expanded }]">
    <button class="tool-head" type="button" @click="hasDetails && (expanded = !expanded)">
      <span class="tool-icon" :class="{ spin: call.status === 'running' }">{{ statusIcon }}</span>
      <span class="tool-name mono">{{ call.name || 'tool' }}</span>
      <span class="tool-time mono">
        {{ call.status === 'running' ? 'running…' : hasTiming ? `(${elapsed})` : '' }}
      </span>
      <span v-if="call.status === 'error'" class="tool-flag">error</span>
      <span class="tool-spacer" />
      <span v-if="hasDetails" class="tool-chevron">{{ expanded ? '▾' : '▸' }}</span>
    </button>

    <div v-if="expanded" class="tool-body">
      <div class="tool-section">
        <div class="tool-section-label">args</div>
        <pre class="tool-pre mono">{{ prettyArgs || '(empty)' }}</pre>
      </div>
      <div v-if="call.result" class="tool-section">
        <div class="tool-section-label">result</div>
        <pre class="tool-pre mono">{{ call.result }}</pre>
      </div>
      <div v-else-if="call.error" class="tool-section">
        <div class="tool-section-label err">error</div>
        <pre class="tool-pre mono">{{ call.error }}</pre>
      </div>
    </div>
  </div>
</template>

<style scoped>
.tool-card {
  margin: 6px 0;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: #0e1319;
  overflow: hidden;
}

.tool-card.is-success {
  border-color: #1f3d2a;
}

.tool-card.is-error {
  border-color: #4a2320;
}

.tool-head {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  padding: 6px 10px;
  text-align: left;
  font-size: 12.5px;
}

.tool-head:hover {
  background: #131a22;
}

.tool-icon {
  font-size: 12px;
}

.is-success .tool-icon {
  color: var(--green);
}

.is-error .tool-icon {
  color: var(--red);
}

.is-running .tool-icon {
  color: var(--yellow);
}

.tool-icon.spin {
  display: inline-block;
  animation: chat-spin 1s linear infinite;
}

.tool-name {
  color: var(--text);
}

.tool-time {
  color: var(--text-faint);
  font-size: 11.5px;
}

.tool-flag {
  color: var(--red);
  font-size: 11px;
  border: 1px solid #6e2b28;
  border-radius: 999px;
  padding: 0 5px;
}

.tool-spacer {
  flex: 1;
}

.tool-chevron {
  color: var(--text-faint);
  font-size: 11px;
}

.tool-body {
  border-top: 1px solid var(--border);
  padding: 6px 10px 10px;
}

.tool-section + .tool-section {
  margin-top: 8px;
}

.tool-section-label {
  font-family: var(--mono);
  font-size: 10.5px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--text-faint);
  margin-bottom: 4px;
}

.tool-section-label.err {
  color: var(--red);
}

.tool-pre {
  margin: 0;
  padding: 8px 10px;
  max-height: 340px;
  overflow: auto;
  background: #0b0f14;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  font-size: 12px;
  line-height: 1.55;
  white-space: pre-wrap;
  word-break: break-word;
}
</style>
