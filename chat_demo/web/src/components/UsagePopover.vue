<script setup lang="ts">
import { computed } from 'vue'
import { SEGMENT_KEYS, type SegmentKey } from '../types'
import { useAppStore } from '../stores/app'
import { formatTokens } from '../utils'

const app = useAppStore()

const SEGMENT_LABELS: Record<SegmentKey, string> = {
  system_prompt: 'System prompt',
  tool_definitions: 'Tool definitions',
  rules: 'Rules',
  skills: 'Skills',
  mcp: 'MCP',
  subagent_definitions: 'Subagents',
  conversation: 'Conversation',
}

const segments = computed(() => {
  const usage = app.contextUsage
  return SEGMENT_KEYS.map((key) => ({
    key,
    label: SEGMENT_LABELS[key],
    tokens: usage?.segments?.[key] ?? 0,
  })).filter((row) => row.tokens > 0)
})

const segmentTotal = computed(() => segments.value.reduce((sum, row) => sum + row.tokens, 0))

const max = computed(() => app.contextMaxTokens)
const used = computed(() => app.contextUsedTokens)

function share(tokens: number): number {
  if (segmentTotal.value <= 0) return 0
  return tokens / segmentTotal.value
}

function barWidth(tokens: number): string {
  return `${Math.max(2, Math.round(share(tokens) * 100))}%`
}

const sourceLabel = computed(() =>
  app.contextUsage?.source === 'model_request' ? 'model_request' : 'empty',
)
</script>

<template>
  <div class="popover">
    <div class="pop-head">
      <span class="pop-title">Context usage</span>
      <span class="pop-source mono">{{ sourceLabel }}</span>
    </div>

    <div class="pop-summary mono">
      <span>{{ formatTokens(used) }} / {{ formatTokens(max) }} tokens</span>
      <span class="dim">({{ (app.contextRatio * 100).toFixed(1) }}%)</span>
    </div>

    <div class="turn mono">
      <span class="dim">本轮</span>
      <span>↑ {{ formatTokens(app.turnUsage.input) }}</span>
      <span>↓ {{ formatTokens(app.turnUsage.output) }}</span>
      <span class="dim">Σ {{ formatTokens(app.turnUsage.total) }}</span>
    </div>

    <div class="pop-body">
      <div v-if="segments.length === 0" class="pop-empty mono">暂无分段数据（尚无模型请求）</div>
      <div v-for="row in segments" :key="row.key" class="seg">
        <div class="seg-line">
          <span class="seg-label">{{ row.label }}</span>
          <span class="seg-tokens mono">{{ formatTokens(row.tokens) }}</span>
        </div>
        <div class="seg-track">
          <div class="seg-fill" :style="{ width: barWidth(row.tokens) }" />
        </div>
      </div>
    </div>

    <div v-if="app.contextUsage" class="pop-foot mono">
      <span>in {{ formatTokens(app.contextUsage.input_tokens) }}</span>
      <span>out {{ formatTokens(app.contextUsage.output_tokens) }}</span>
      <span v-if="segmentTotal > 0">segments Σ {{ formatTokens(segmentTotal) }}</span>
    </div>
  </div>
</template>

<style scoped>
.popover {
  position: absolute;
  right: 0;
  bottom: calc(100% + 10px);
  z-index: 30;
  width: 320px;
  padding: 12px;
  background: var(--bg-elevated);
  border: 1px solid var(--border-strong);
  border-radius: var(--radius);
  box-shadow: 0 12px 36px rgba(0, 0, 0, 0.55);
}

.pop-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
}

.pop-title {
  font-size: 13px;
  font-weight: 600;
}

.pop-source {
  color: var(--text-faint);
  font-size: 10.5px;
}

.pop-summary {
  margin-top: 4px;
  font-size: 12px;
}

.pop-summary .dim {
  margin-left: 6px;
  color: var(--text-faint);
}

.turn {
  display: flex;
  gap: 10px;
  margin-top: 3px;
  font-size: 11.5px;
  color: var(--text-dim);
}

.turn .dim {
  color: var(--text-faint);
}

.pop-body {
  margin-top: 10px;
  padding-top: 8px;
  border-top: 1px solid var(--border);
  max-height: 240px;
  overflow-y: auto;
}

.pop-empty {
  color: var(--text-faint);
  font-size: 11.5px;
}

.seg + .seg {
  margin-top: 7px;
}

.seg-line {
  display: flex;
  justify-content: space-between;
  font-size: 12px;
}

.seg-label {
  color: var(--text-dim);
}

.seg-tokens {
  color: var(--text);
  font-size: 11.5px;
}

.seg-track {
  margin-top: 3px;
  height: 5px;
  background: #1b2028;
  border-radius: 3px;
  overflow: hidden;
}

.seg-fill {
  height: 100%;
  background: linear-gradient(90deg, var(--accent-dim), var(--accent));
}

.pop-foot {
  display: flex;
  gap: 10px;
  margin-top: 10px;
  padding-top: 8px;
  border-top: 1px solid var(--border);
  color: var(--text-faint);
  font-size: 10.5px;
}
</style>
