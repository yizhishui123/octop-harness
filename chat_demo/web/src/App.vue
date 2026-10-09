<script setup lang="ts">
import { computed, onMounted, watch } from 'vue'
import Sidebar from './components/Sidebar.vue'
import MessageList from './components/MessageList.vue'
import Composer from './components/Composer.vue'
import StatusBar from './components/StatusBar.vue'
import { useAppStore } from './stores/app'
import { useChatStore } from './stores/chat'

const app = useAppStore()
const chat = useChatStore()

const headerTitle = computed(() => chat.sessionTitle)
const headerAgent = computed(() => app.activeAgent?.name ?? '未选择 agent')

onMounted(async () => {
  await app.loadAgents()
  await chat.restore()
})

watch(
  () => app.activeModel,
  () => {
    void app.refreshContext(chat.activeThreadId)
  },
)
</script>

<template>
  <div class="shell">
    <div class="top">
      <Sidebar />
      <main class="main">
        <header class="header">
          <div class="header-left">
            <span class="header-title">{{ headerTitle }}</span>
            <span v-if="chat.activeSession" class="header-agent mono">{{ headerAgent }}</span>
          </div>
          <div class="header-right mono">
            <span class="pill">{{ app.activeModel ?? 'no-model' }}</span>
          </div>
        </header>
        <MessageList />
        <Composer :streaming="chat.streaming" />
      </main>
    </div>
    <StatusBar />
  </div>
</template>

<style scoped>
.shell {
  display: flex;
  flex-direction: column;
  height: 100%;
}

.top {
  display: flex;
  flex: 1;
  min-height: 0;
}

.main {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-width: 0;
  background: var(--bg);
}

.header {
  display: flex;
  align-items: center;
  gap: 12px;
  height: 46px;
  padding: 0 28px;
  border-bottom: 1px solid var(--border);
  background: var(--bg-panel);
}

.header-left {
  display: flex;
  align-items: baseline;
  gap: 10px;
  min-width: 0;
}

.header-title {
  font-size: 13.5px;
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.header-agent {
  color: var(--text-faint);
  font-size: 11px;
}

.header-right {
  margin-left: auto;
}
</style>
