<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import UsagePopover from './UsagePopover.vue'
import { useAppStore } from '../stores/app'
import { useChatStore } from '../stores/chat'
import { formatTokens } from '../utils'

const app = useAppStore()
const chat = useChatStore()

const usageOpen = ref(false)
const root = ref<HTMLElement | null>(null)

const modelLabel = computed(() => app.activeModelInfo?.name ?? app.activeModel ?? '未选择模型')
const agentLabel = computed(() => app.activeAgent?.name ?? '—')

const ratioPercent = computed(() => app.contextRatio * 100)

const barClass = computed(() => {
  const ratio = app.contextRatio
  if (ratio < 0.6) return 'ok'
  if (ratio < 0.85) return 'warn'
  return 'danger'
})

const usageLabel = computed(() => `${formatTokens(app.contextUsedTokens)} / ${formatTokens(app.contextMaxTokens)}`)

function selectModel(ref_: string): void {
  app.setActiveModel(ref_)
}

function toggleUsage(): void {
  usageOpen.value = !usageOpen.value
}

function onDocumentClick(event: MouseEvent): void {
  if (!root.value) return
  if (!root.value.contains(event.target as Node)) {
    usageOpen.value = false
    app.closeModelMenu()
  }
}

onMounted(() => document.addEventListener('click', onDocumentClick))
onBeforeUnmount(() => document.removeEventListener('click', onDocumentClick))
</script>

<template>
  <footer ref="root" class="statusbar mono">
    <span class="item agent">
      <span class="key">agent</span>
      <span class="value">{{ agentLabel }}</span>
    </span>

    <span class="divider">│</span>

    <span class="item model-item">
      <span class="key">model</span>
      <button class="model-btn" type="button" @click="app.toggleModelMenu()">
        {{ modelLabel }} <span class="chev">{{ app.modelMenuOpen ? '▾' : '▸' }}</span>
      </button>
      <div v-if="app.modelMenuOpen" class="model-menu">
        <div class="menu-head">选择模型</div>
        <button
          v-for="model in app.availableModels"
          :key="model.ref"
          type="button"
          class="menu-item"
          :class="{ active: model.ref === app.activeModel }"
          @click="selectModel(model.ref)"
        >
          <span class="menu-name">{{ model.name }}</span>
          <span class="menu-ref">{{ model.ref }}</span>
          <span class="menu-ctx">{{ formatTokens(model.context_window) }}</span>
        </button>
        <div v-if="app.availableModels.length === 0" class="menu-empty">该 agent 没有可用模型</div>
      </div>
    </span>

    <span class="divider">│</span>

    <span class="item thread">
      <span class="key">thread</span>
      <span class="value dim">{{ chat.activeThreadId ? chat.activeThreadId.slice(0, 12) : '—' }}</span>
    </span>

    <span class="spacer" />

    <span v-if="chat.streaming" class="item streaming">
      <span class="pulse">●</span> 生成中
    </span>

    <button class="item ctx" type="button" :title="`上下文用量 ${ratioPercent.toFixed(1)}%`" @click="toggleUsage">
      <span class="key">ctx</span>
      <span class="ctx-track">
        <span class="ctx-fill" :class="barClass" :style="{ width: `${Math.max(1, ratioPercent)}%` }" />
      </span>
      <span class="ctx-label">{{ usageLabel }}</span>
      <span class="ctx-pct" :class="barClass">{{ ratioPercent.toFixed(0) }}%</span>
    </button>

    <UsagePopover v-if="usageOpen" />
  </footer>
</template>

<style scoped>
.statusbar {
  position: relative;
  display: flex;
  align-items: center;
  gap: 8px;
  height: var(--statusbar-height);
  padding: 0 14px;
  background: var(--bg-panel);
  border-top: 1px solid var(--border);
  font-size: 11.5px;
  color: var(--text-dim);
}

.item {
  display: flex;
  align-items: center;
  gap: 6px;
}

.key {
  color: var(--text-faint);
  font-size: 10.5px;
  letter-spacing: 0.06em;
  text-transform: uppercase;
}

.value {
  color: var(--text);
}

.dim {
  color: var(--text-faint);
}

.divider {
  color: #2c333c;
}

.spacer {
  flex: 1;
}

.model-item {
  position: relative;
}

.model-btn {
  color: var(--text);
  font-family: var(--mono);
  font-size: 11.5px;
}

.model-btn:hover {
  color: var(--accent);
}

.chev {
  color: var(--text-faint);
  font-size: 10px;
}

.model-menu {
  position: absolute;
  left: 0;
  bottom: calc(100% + 10px);
  z-index: 30;
  min-width: 300px;
  padding: 4px;
  background: var(--bg-elevated);
  border: 1px solid var(--border-strong);
  border-radius: var(--radius);
  box-shadow: 0 12px 36px rgba(0, 0, 0, 0.55);
}

.menu-head {
  padding: 5px 8px;
  color: var(--text-faint);
  font-size: 10.5px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.menu-item {
  display: flex;
  align-items: baseline;
  gap: 8px;
  width: 100%;
  padding: 5px 8px;
  border-radius: var(--radius-sm);
  text-align: left;
}

.menu-item:hover {
  background: var(--bg-hover);
}

.menu-item.active {
  background: var(--bg-active);
}

.menu-name {
  color: var(--text);
}

.menu-ref {
  flex: 1;
  color: var(--text-faint);
  font-size: 10.5px;
}

.menu-ctx {
  color: var(--text-faint);
  font-size: 10.5px;
}

.menu-empty {
  padding: 8px;
  color: var(--text-faint);
}

.streaming {
  color: var(--green);
}

.pulse {
  animation: chat-pulse 1.1s ease-in-out infinite;
  font-size: 9px;
}

.ctx {
  gap: 7px;
  padding: 2px 6px;
  border-radius: var(--radius-sm);
}

.ctx:hover {
  background: var(--bg-hover);
}

.ctx-track {
  display: inline-block;
  width: 90px;
  height: 6px;
  background: #1b2028;
  border-radius: 3px;
  overflow: hidden;
}

.ctx-fill {
  display: block;
  height: 100%;
  transition: width 0.25s ease;
}

.ctx-fill.ok {
  background: var(--green);
}

.ctx-fill.warn {
  background: var(--yellow);
}

.ctx-fill.danger {
  background: var(--red);
}

.ctx-label {
  color: var(--text-dim);
}

.ctx-pct.ok {
  color: var(--green);
}

.ctx-pct.warn {
  color: var(--yellow);
}

.ctx-pct.danger {
  color: var(--red);
}
</style>
