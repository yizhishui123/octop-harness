/** Global app state: agent registry, selected model, context-window usage. */
import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { fetchAgents, fetchContextUsage } from '../api'
import type { ApiAgent, ApiModel, ContextUsage, RawUsage, TurnUsage } from '../types'

function emptyTurnUsage(): TurnUsage {
  return { input: 0, output: 0, total: 0 }
}

export const useAppStore = defineStore('app', () => {
  const agents = ref<ApiAgent[]>([])
  const activeAgentId = ref<string | null>(null)
  const activeModel = ref<string | null>(null)
  const contextUsage = ref<ContextUsage | null>(null)
  const turnUsage = ref<TurnUsage>(emptyTurnUsage())
  const loadingAgents = ref(false)
  const agentsError = ref<string | null>(null)
  const modelMenuOpen = ref(false)

  const activeAgent = computed<ApiAgent | null>(
    () => agents.value.find((a) => a.agent_id === activeAgentId.value) ?? null,
  )

  const availableModels = computed<ApiModel[]>(() => activeAgent.value?.models ?? [])

  const activeModelInfo = computed<ApiModel | null>(
    () => availableModels.value.find((m) => m.ref === activeModel.value) ?? null,
  )

  /** Context cap: backend-reported window wins, else the selected model's. */
  const contextMaxTokens = computed<number>(() => {
    const fromUsage = contextUsage.value?.max_tokens ?? 0
    if (fromUsage > 0) return fromUsage
    return activeModelInfo.value?.context_window ?? 128_000
  })

  const contextUsedTokens = computed<number>(() => contextUsage.value?.used_tokens ?? 0)

  const contextRatio = computed<number>(() => {
    const max = contextMaxTokens.value
    if (max <= 0) return 0
    return Math.min(1, contextUsedTokens.value / max)
  })

  async function loadAgents(): Promise<void> {
    loadingAgents.value = true
    agentsError.value = null
    try {
      agents.value = await fetchAgents()
      const stillThere = agents.value.some((a) => a.agent_id === activeAgentId.value)
      if (!stillThere) {
        activeAgentId.value = agents.value[0]?.agent_id ?? null
      }
      if (!activeModel.value) {
        activeModel.value = activeAgent.value?.default_model ?? availableModels.value[0]?.ref ?? null
      }
    } catch (err) {
      agentsError.value = err instanceof Error ? err.message : String(err)
    } finally {
      loadingAgents.value = false
    }
  }

  function setActiveAgent(agentId: string | null): void {
    if (agentId === activeAgentId.value) return
    activeAgentId.value = agentId
    const agent = agents.value.find((a) => a.agent_id === agentId)
    activeModel.value = agent?.default_model ?? agent?.models[0]?.ref ?? null
    contextUsage.value = null
    turnUsage.value = emptyTurnUsage()
  }

  function setActiveModel(model: string | null): void {
    activeModel.value = model
    modelMenuOpen.value = false
  }

  function toggleModelMenu(): void {
    modelMenuOpen.value = !modelMenuOpen.value
  }

  function closeModelMenu(): void {
    modelMenuOpen.value = false
  }

  function setContextUsage(usage: ContextUsage | null): void {
    contextUsage.value = usage
  }

  function beginTurn(): void {
    turnUsage.value = emptyTurnUsage()
  }

  function accumulateUsage(raw: RawUsage): void {
    const input = Number(raw.input_tokens ?? 0) || 0
    const output = Number(raw.output_tokens ?? 0) || 0
    const total = Number(raw.total_tokens ?? 0) || input + output
    turnUsage.value = {
      input: turnUsage.value.input + input,
      output: turnUsage.value.output + output,
      total: turnUsage.value.total + total,
    }
  }

  /** Refresh the context ring from the backend (best effort; 404 = no thread yet). */
  async function refreshContext(threadId: string | null): Promise<void> {
    if (!threadId || !activeAgentId.value || threadId.startsWith('pending-')) {
      if (!threadId) contextUsage.value = null
      return
    }
    try {
      contextUsage.value = await fetchContextUsage(threadId, activeAgentId.value)
    } catch {
      /* thread may not exist server-side yet; keep the previous stamp */
    }
  }

  return {
    agents,
    activeAgentId,
    activeAgent,
    availableModels,
    activeModel,
    activeModelInfo,
    modelMenuOpen,
    contextUsage,
    contextMaxTokens,
    contextUsedTokens,
    contextRatio,
    turnUsage,
    loadingAgents,
    agentsError,
    loadAgents,
    setActiveAgent,
    setActiveModel,
    toggleModelMenu,
    closeModelMenu,
    setContextUsage,
    beginTurn,
    accumulateUsage,
    refreshContext,
  }
})
