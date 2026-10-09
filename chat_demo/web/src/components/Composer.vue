<script setup lang="ts">
import { computed, nextTick, ref } from 'vue'
import SlashPanel from './SlashPanel.vue'
import { useAppStore } from '../stores/app'
import { useChatStore } from '../stores/chat'
import { HELP_TEXT, filterCommands, type SlashCommand } from '../slash'

const props = defineProps<{ streaming: boolean }>()

const app = useAppStore()
const chat = useChatStore()

const text = ref('')
const textarea = ref<HTMLTextAreaElement | null>(null)
const slashIndex = ref(0)

const slashQuery = computed(() => {
  const value = text.value
  if (!value.startsWith('/')) return null
  return /^\/\S*$/.test(value) ? value : null
})

const slashOpen = computed(() => slashQuery.value !== null && !props.streaming)
const commands = computed<SlashCommand[]>(() => filterCommands(slashQuery.value ?? ''))

function autoGrow(): void {
  const el = textarea.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = `${Math.min(el.scrollHeight, 220)}px`
}

async function submit(): Promise<void> {
  const value = text.value.trim()
  if (!value || props.streaming) return
  text.value = ''
  slashIndex.value = 0
  await nextTick()
  autoGrow()
  await chat.send(value)
}

function applySlash(command: SlashCommand): void {
  text.value = ''
  slashIndex.value = 0
  void nextTick(() => autoGrow())
  switch (command.name) {
    case '/model':
      app.toggleModelMenu()
      break
    case '/new':
      chat.newSession()
      break
    case '/clear':
      chat.clearMessages()
      break
    case '/help':
      chat.addNotice(HELP_TEXT)
      break
    case '/stop':
      if (chat.streaming) void chat.stop()
      else void chat.send('/stop')
      break
    default:
      void chat.send(command.name)
      break
  }
}

function onKeydown(event: KeyboardEvent): void {
  if (slashOpen.value && commands.value.length > 0) {
    if (event.key === 'ArrowDown') {
      event.preventDefault()
      slashIndex.value = (slashIndex.value + 1) % commands.value.length
      return
    }
    if (event.key === 'ArrowUp') {
      event.preventDefault()
      slashIndex.value = (slashIndex.value - 1 + commands.value.length) % commands.value.length
      return
    }
    if (event.key === 'Enter' || event.key === 'Tab') {
      event.preventDefault()
      applySlash(commands.value[Math.min(slashIndex.value, commands.value.length - 1)])
      return
    }
    if (event.key === 'Escape') {
      event.preventDefault()
      text.value = ''
      return
    }
  }
  if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
    event.preventDefault()
    void submit()
  }
}

function onInput(): void {
  slashIndex.value = 0
  autoGrow()
}

function onStop(): void {
  void chat.stop()
}
</script>

<template>
  <div class="composer-wrap">
    <div class="composer">
      <SlashPanel
        v-if="slashOpen"
        :commands="commands"
        :active-index="slashIndex"
        @select="applySlash"
        @hover="(index) => (slashIndex = index)"
      />
      <textarea
        ref="textarea"
        v-model="text"
        class="input"
        rows="1"
        placeholder="输入消息，Enter 发送 / Shift+Enter 换行；输入 / 查看命令"
        spellcheck="false"
        @keydown="onKeydown"
        @input="onInput"
      />
      <div class="actions">
        <button
          v-if="streaming"
          class="btn btn-danger stop"
          type="button"
          title="停止当前运行"
          @click="onStop"
        >
          ■ 停止
        </button>
        <button
          v-else
          class="btn btn-primary send"
          type="button"
          :disabled="!text.trim()"
          title="发送 (Enter)"
          @click="submit"
        >
          ↑ 发送
        </button>
      </div>
    </div>
    <div class="hint mono">
      <span>{{ streaming ? '● 正在生成…' : '就绪' }}</span>
      <span class="sep">│</span>
      <span>Enter 发送 · Shift+Enter 换行 · / 命令</span>
    </div>
  </div>
</template>

<style scoped>
.composer-wrap {
  position: relative;
  padding: 10px 28px 14px;
  border-top: 1px solid var(--border);
  background: var(--bg-panel);
}

.composer {
  position: relative;
  display: flex;
  align-items: flex-end;
  gap: 8px;
  max-width: 940px;
  margin: 0 auto;
  padding: 8px 10px;
  background: var(--bg-input);
  border: 1px solid var(--border-strong);
  border-radius: var(--radius);
}

.composer:focus-within {
  border-color: var(--accent-dim);
}

.input {
  flex: 1;
  min-height: 24px;
  max-height: 220px;
  padding: 2px 2px;
  border: none;
  background: transparent;
  resize: none;
  line-height: 1.55;
  overflow-y: auto;
}

.input:focus {
  border: none;
}

.send,
.stop {
  white-space: nowrap;
}

.hint {
  display: flex;
  gap: 6px;
  max-width: 940px;
  margin: 6px auto 0;
  color: var(--text-faint);
  font-size: 11px;
}

.sep {
  opacity: 0.5;
}
</style>
