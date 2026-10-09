<script setup lang="ts">
import type { SlashCommand } from '../slash'

defineProps<{ commands: SlashCommand[]; activeIndex: number }>()
const emit = defineEmits<{ select: [command: SlashCommand]; hover: [index: number] }>()
</script>

<template>
  <div class="slash-panel">
    <div class="slash-head mono">commands</div>
    <button
      v-for="(command, index) in commands"
      :key="command.name"
      type="button"
      class="slash-item"
      :class="{ active: index === activeIndex }"
      @mouseenter="emit('hover', index)"
      @mousedown.prevent="emit('select', command)"
    >
      <span class="slash-name mono">{{ command.name }}</span>
      <span class="slash-desc">{{ command.description }}</span>
      <span class="slash-tag mono">{{ command.local ? 'local' : 'runtime' }}</span>
    </button>
    <div v-if="commands.length === 0" class="slash-empty">没有匹配的命令</div>
  </div>
</template>

<style scoped>
.slash-panel {
  position: absolute;
  left: 0;
  right: 0;
  bottom: calc(100% + 8px);
  z-index: 20;
  max-height: 260px;
  overflow-y: auto;
  padding: 4px;
  background: var(--bg-elevated);
  border: 1px solid var(--border-strong);
  border-radius: var(--radius);
  box-shadow: 0 10px 30px rgba(0, 0, 0, 0.5);
}

.slash-head {
  padding: 4px 8px;
  color: var(--text-faint);
  font-size: 10.5px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.slash-item {
  display: flex;
  align-items: baseline;
  gap: 10px;
  width: 100%;
  padding: 5px 8px;
  border-radius: var(--radius-sm);
  text-align: left;
}

.slash-item.active {
  background: var(--bg-active);
}

.slash-name {
  color: var(--accent);
  font-size: 12.5px;
  min-width: 68px;
}

.slash-desc {
  flex: 1;
  color: var(--text-dim);
  font-size: 12.5px;
}

.slash-tag {
  color: var(--text-faint);
  font-size: 10.5px;
}

.slash-empty {
  padding: 8px;
  color: var(--text-faint);
  font-size: 12.5px;
}
</style>
