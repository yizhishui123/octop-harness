/**
 * Conversation state: sessions (localStorage metadata), per-thread message
 * lists, the live SSE reducer and the send/stop/resume commands.
 *
 * Message *content* is never persisted locally — switching sessions rehydrates
 * it from `GET /api/threads/{id}/history`.
 */
import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { fetchHistory, isAbortError, postStop, resumeChat, streamChat } from '../api'
import { useAppStore } from './app'
import type {
  ChatMessage,
  ContextUsage,
  Decision,
  HistoryMessage,
  HitlRequest,
  RawUsage,
  SSEEvent,
  SessionMeta,
  ToolCallItem,
  ToolResultItem,
} from '../types'
import { stringify, truncate, uid } from '../utils'

const SESSIONS_KEY = 'chat-demo:sessions'
const ACTIVE_KEY = 'chat-demo:active-thread'

function loadSessions(): SessionMeta[] {
  try {
    const raw = localStorage.getItem(SESSIONS_KEY)
    if (!raw) return []
    const parsed: unknown = JSON.parse(raw)
    if (!Array.isArray(parsed)) return []
    return parsed
      .filter((item): item is Record<string, unknown> => !!item && typeof item === 'object')
      .map((item) => ({
        thread_id: String(item.thread_id ?? ''),
        agent_id: String(item.agent_id ?? ''),
        title: String(item.title ?? '新会话'),
        updateTime: Number(item.update_time ?? item.updateTime ?? Date.now()),
      }))
      .filter((item) => item.thread_id.length > 0)
  } catch {
    return []
  }
}

function loadActiveThread(): string | null {
  try {
    return localStorage.getItem(ACTIVE_KEY)
  } catch {
    return null
  }
}

function newAssistant(): ChatMessage {
  return {
    id: uid(),
    role: 'assistant',
    content: '',
    toolCalls: [],
    createdAt: Date.now(),
    streaming: true,
  }
}

function newNotice(text: string, role: ChatMessage['role'] = 'system'): ChatMessage {
  return { id: uid(), role, content: text, toolCalls: [], createdAt: Date.now(), notice: true }
}

export const useChatStore = defineStore('chat', () => {
  const sessions = ref<SessionMeta[]>(loadSessions())
  const activeThreadId = ref<string | null>(loadActiveThread())
  const messagesByThread = ref<Record<string, ChatMessage[]>>({})
  const streaming = ref(false)
  /** Thread the in-flight stream belongs to (may differ from activeThreadId). */
  const streamThreadId = ref<string | null>(null)
  const pendingHitl = ref<HitlRequest | null>(null)
  const pendingHitlThreadId = ref<string | null>(null)

  let abortController: AbortController | null = null

  /* ---------------------------------------------------------------- */
  /* Derived                                                          */
  /* ---------------------------------------------------------------- */

  const messages = computed<ChatMessage[]>(() =>
    activeThreadId.value ? (messagesByThread.value[activeThreadId.value] ?? []) : [],
  )

  const activeSession = computed<SessionMeta | null>(
    () => sessions.value.find((s) => s.thread_id === activeThreadId.value) ?? null,
  )

  const sessionTitle = computed<string>(() => {
    const session = activeSession.value
    if (session) return session.title
    return messages.value.length > 0 ? '新会话' : 'octop-harness chat demo'
  })

  const sortedSessions = computed<SessionMeta[]>(() =>
    [...sessions.value].sort((a, b) => b.updateTime - a.updateTime),
  )

  const visibleHitl = computed<HitlRequest | null>(() =>
    pendingHitlThreadId.value === activeThreadId.value ? pendingHitl.value : null,
  )

  /* ---------------------------------------------------------------- */
  /* Persistence                                                      */
  /* ---------------------------------------------------------------- */

  function persistSessions(): void {
    try {
      localStorage.setItem(
        SESSIONS_KEY,
        JSON.stringify(
          sessions.value.map((s) => ({
            thread_id: s.thread_id,
            agent_id: s.agent_id,
            title: s.title,
            update_time: s.updateTime,
          })),
        ),
      )
    } catch {
      /* quota / private mode: the demo keeps working in memory */
    }
  }

  function persistActive(): void {
    try {
      if (activeThreadId.value) localStorage.setItem(ACTIVE_KEY, activeThreadId.value)
      else localStorage.removeItem(ACTIVE_KEY)
    } catch {
      /* ignore */
    }
  }

  /* ---------------------------------------------------------------- */
  /* Low-level helpers                                                */
  /* ---------------------------------------------------------------- */

  function ensureMessages(threadId: string): ChatMessage[] {
    if (!messagesByThread.value[threadId]) {
      messagesByThread.value[threadId] = []
    }
    return messagesByThread.value[threadId]
  }

  function lastAssistant(threadId: string): ChatMessage | null {
    const list = messagesByThread.value[threadId]
    if (!list) return null
    for (let i = list.length - 1; i >= 0; i -= 1) {
      const msg = list[i]
      if (msg.role === 'assistant') return msg
    }
    return null
  }

  /** The assistant bubble that should receive stream deltas, creating one if needed. */
  function openAssistant(threadId: string): ChatMessage {
    const target = lastAssistant(threadId)
    if (target && target.streaming) return target
    const msg = newAssistant()
    ensureMessages(threadId).push(msg)
    return msg
  }

  function pushNotice(threadId: string, text: string, role: ChatMessage['role'] = 'system'): void {
    ensureMessages(threadId).push(newNotice(text, role))
  }

  function finishMessage(msg: ChatMessage, stopped = false): void {
    msg.streaming = false
    msg.durationMs = Math.max(0, Date.now() - msg.createdAt)
    if (stopped) msg.stopped = true
    for (const call of msg.toolCalls) {
      if (call.status === 'running') {
        call.status = stopped ? 'error' : 'success'
        call.endedAt = Date.now()
        if (stopped && !call.error) call.error = '已中止'
      }
    }
  }

  function findToolCall(threadId: string, callId: string): ToolCallItem | null {
    const list = messagesByThread.value[threadId]
    if (!list) return null
    for (let i = list.length - 1; i >= 0; i -= 1) {
      const msg = list[i]
      for (let j = msg.toolCalls.length - 1; j >= 0; j -= 1) {
        if (msg.toolCalls[j].id === callId) return msg.toolCalls[j]
      }
    }
    return null
  }

  function createSession(threadId: string, agentId: string, title = '新会话'): void {
    if (sessions.value.some((s) => s.thread_id === threadId)) return
    sessions.value.push({ thread_id: threadId, agent_id: agentId, title, updateTime: Date.now() })
    persistSessions()
  }

  function touchSession(threadId: string, firstUserText?: string): void {
    const session = sessions.value.find((s) => s.thread_id === threadId)
    if (!session) return
    session.updateTime = Date.now()
    if (firstUserText && (session.title === '新会话' || !session.title)) {
      session.title = truncate(firstUserText, 32)
    }
    persistSessions()
  }

  function migrateThread(oldId: string, newId: string): void {
    if (!oldId || oldId === newId) return
    const list = messagesByThread.value[oldId]
    if (list) {
      messagesByThread.value[newId] = list
      delete messagesByThread.value[oldId]
    }
    const session = sessions.value.find((s) => s.thread_id === oldId)
    if (session) session.thread_id = newId
    if (activeThreadId.value === oldId) {
      activeThreadId.value = newId
      persistActive()
    }
    if (streamThreadId.value === oldId) streamThreadId.value = newId
    if (pendingHitlThreadId.value === oldId) pendingHitlThreadId.value = newId
    persistSessions()
  }

  /* ---------------------------------------------------------------- */
  /* SSE reducer                                                      */
  /* ---------------------------------------------------------------- */

  function applyUsage(threadId: string, usage: RawUsage): void {
    const app = useAppStore()
    app.accumulateUsage(usage)
    const msg = lastAssistant(threadId)
    if (!msg) return
    const input = Number(usage.input_tokens ?? 0) || 0
    const output = Number(usage.output_tokens ?? 0) || 0
    msg.usage = {
      input: input || msg.usage?.input || 0,
      output: output || msg.usage?.output || 0,
      total: Number(usage.total_tokens ?? 0) || input + output || msg.usage?.total || 0,
    }
  }

  function applyToolResults(threadId: string, results: ToolResultItem[]): void {
    for (const result of results) {
      const call = findToolCall(threadId, result.tool_call_id)
      if (!call) {
        pushNotice(threadId, `[${result.name || 'tool'}] ${truncate(result.content, 200)}`, 'tool')
        continue
      }
      call.result = result.content
      call.status = result.status === 'error' ? 'error' : 'success'
      call.endedAt = Date.now()
      if (result.name && !call.name) call.name = result.name
    }
  }

  function appendError(threadId: string, message: string): void {
    const list = ensureMessages(threadId)
    const last = list[list.length - 1]
    if (last && last.role === 'assistant') {
      last.error = message
      last.streaming = false
      return
    }
    const msg = newAssistant()
    msg.streaming = false
    msg.error = message
    msg.createdAt = Date.now()
    list.push(msg)
  }

  function handleEvent(threadId: string, event: SSEEvent): void {
    const tid = streamThreadId.value ?? threadId
    switch (event.type) {
      case 'thread': {
        if (event.thread_id && event.thread_id !== tid) migrateThread(tid, event.thread_id)
        break
      }
      case 'token': {
        const msg = openAssistant(tid)
        msg.content += event.content ?? ''
        if (msg.reasoning && !msg.reasoningEndedAt) msg.reasoningEndedAt = Date.now()
        break
      }
      case 'reasoning': {
        const msg = openAssistant(tid)
        if (!msg.reasoningStartedAt) msg.reasoningStartedAt = Date.now()
        msg.reasoningEndedAt = Date.now()
        msg.reasoning = (msg.reasoning ?? '') + (event.content ?? '')
        break
      }
      case 'tool_call_chunk': {
        const msg = openAssistant(tid)
        const callId = event.id || `call_${event.index ?? msg.toolCalls.length}`
        let call = msg.toolCalls.find((c) => c.id === callId)
        if (!call) {
          call = { id: callId, name: event.name ?? '', argsText: '', status: 'running', startedAt: Date.now() }
          msg.toolCalls.push(call)
        }
        if (event.name) call.name = event.name
        if (event.args) call.argsText += event.args
        break
      }
      case 'tool_result': {
        applyToolResults(tid, event.results ?? [])
        break
      }
      case 'state_update':
        break
      case 'state_snapshot': {
        const app = useAppStore()
        if (event.context_usage) app.setContextUsage(event.context_usage as ContextUsage)
        if (event.usage) applyUsage(tid, event.usage)
        break
      }
      case 'usage': {
        applyUsage(tid, event.usage ?? {})
        break
      }
      case 'custom': {
        pushNotice(tid, typeof event.data === 'string' ? event.data : stringify(event.data))
        break
      }
      case 'hitl_required': {
        pendingHitl.value = event.request
        pendingHitlThreadId.value = tid
        const msg = lastAssistant(tid)
        if (msg) msg.streaming = false
        break
      }
      case 'error': {
        appendError(tid, event.message || '未知错误')
        break
      }
      case 'done': {
        const msg = lastAssistant(tid)
        if (msg) finishMessage(msg)
        break
      }
      default:
        break
    }
  }

  /* ---------------------------------------------------------------- */
  /* Stream driver                                                    */
  /* ---------------------------------------------------------------- */

  /** Drop a trailing empty assistant placeholder (e.g. resume produced nothing). */
  function pruneEmptyAssistant(threadId: string): void {
    const list = messagesByThread.value[threadId]
    if (!list || list.length === 0) return
    const last = list[list.length - 1]
    if (last.role === 'assistant' && !last.content && !last.error && last.toolCalls.length === 0) {
      list.pop()
    }
  }

  async function runStream(threadId: string, starter: (signal: AbortSignal, onEvent: (e: SSEEvent) => void) => Promise<void>): Promise<void> {
    streaming.value = true
    streamThreadId.value = threadId
    const controller = new AbortController()
    abortController = controller
    try {
      await starter(controller.signal, (event) => handleEvent(threadId, event))
    } catch (err) {
      if (isAbortError(err)) {
        const msg = lastAssistant(threadId)
        if (msg && msg.streaming) finishMessage(msg, true)
      } else {
        appendError(threadId, err instanceof Error ? err.message : String(err))
      }
    } finally {
      const tid = streamThreadId.value ?? threadId
      const msg = lastAssistant(tid)
      if (msg && msg.streaming) finishMessage(msg, controller.signal.aborted)
      pruneEmptyAssistant(tid)
      streaming.value = false
      streamThreadId.value = null
      abortController = null
      touchSession(tid)
      await useAppStore().refreshContext(tid)
    }
  }

  /* ---------------------------------------------------------------- */
  /* Commands                                                         */
  /* ---------------------------------------------------------------- */

  async function send(text: string): Promise<void> {
    const content = text.trim()
    if (!content || streaming.value) return
    const app = useAppStore()
    const agentId = app.activeAgentId
    if (!agentId) return

    let threadId = activeThreadId.value
    let isPendingThread = false
    if (!threadId) {
      threadId = `pending-${uid()}`
      isPendingThread = true
      activeThreadId.value = threadId
      persistActive()
    } else if (threadId.startsWith('pending-')) {
      isPendingThread = true
    }

    createSession(threadId, agentId)
    const list = ensureMessages(threadId)
    list.push({ id: uid(), role: 'user', content, toolCalls: [], createdAt: Date.now() })
    list.push(newAssistant())
    touchSession(threadId, content)
    app.beginTurn()
    pendingHitl.value = null
    pendingHitlThreadId.value = null
    app.setContextUsage(null)

    const requestThreadId = isPendingThread ? null : threadId
    await runStream(threadId, (signal, onEvent) =>
      streamChat(
        { agent_id: agentId, message: content, thread_id: requestThreadId, model: app.activeModel },
        { onEvent, signal },
      ),
    )
  }

  async function resume(decisions: Decision[]): Promise<void> {
    if (streaming.value) return
    const app = useAppStore()
    const agentId = app.activeAgentId
    const threadId = pendingHitlThreadId.value ?? activeThreadId.value
    pendingHitl.value = null
    pendingHitlThreadId.value = null
    if (!threadId || !agentId || threadId.startsWith('pending-')) return

    ensureMessages(threadId).push(newAssistant())
    touchSession(threadId)
    app.beginTurn()

    await runStream(threadId, (signal, onEvent) =>
      resumeChat({ agent_id: agentId, thread_id: threadId, decisions }, { onEvent, signal }),
    )
  }

  async function stop(): Promise<void> {
    const app = useAppStore()
    const threadId = streamThreadId.value ?? activeThreadId.value
    if (!streaming.value || !threadId) return
    if (app.activeAgentId && !threadId.startsWith('pending-')) {
      try {
        await postStop(app.activeAgentId, threadId)
      } catch (err) {
        console.warn('[chat] stop request failed', err)
      }
    }
    abortController?.abort()
  }

  async function loadHistory(threadId: string, opts: { force?: boolean } = {}): Promise<void> {
    const app = useAppStore()
    const agentId = app.activeAgentId
    if (!agentId || threadId.startsWith('pending-')) return
    if (!opts.force && (messagesByThread.value[threadId]?.length ?? 0) > 0) return
    try {
      const items = await fetchHistory(threadId, agentId)
      messagesByThread.value[threadId] = fromHistory(items)
    } catch (err) {
      messagesByThread.value[threadId] = []
      pushNotice(threadId, `无法加载历史: ${err instanceof Error ? err.message : String(err)}`)
    }
    touchSession(threadId)
  }

  /** Fold raw history entries into UI messages (tool rows become tool cards). */
  function fromHistory(items: HistoryMessage[]): ChatMessage[] {
    const out: ChatMessage[] = []
    const byCallId = new Map<string, ToolCallItem>()
    for (const item of items) {
      if (item.role === 'system') continue
      if (item.role === 'tool') {
        const call = item.tool_call_id ? byCallId.get(item.tool_call_id) : undefined
        if (call) {
          call.result = item.content
          call.status = 'success'
        } else {
          out.push(newNotice(`[${item.name || 'tool'}] ${truncate(item.content ?? '', 300)}`, 'tool'))
        }
        continue
      }
      const msg: ChatMessage = {
        id: uid(),
        role: item.role,
        content: item.content ?? '',
        reasoning: item.reasoning,
        toolCalls: [],
        createdAt: Date.now(),
      }
      if (msg.reasoning) msg.reasoningEndedAt = msg.createdAt
      for (const call of item.tool_calls ?? []) {
        const entry: ToolCallItem = {
          id: call.id || uid(),
          name: call.name,
          argsText: stringify(call.args ?? {}),
          status: 'success',
          startedAt: 0,
        }
        msg.toolCalls.push(entry)
        byCallId.set(entry.id, entry)
      }
      out.push(msg)
    }
    return out
  }

  /* ---------------------------------------------------------------- */
  /* Sessions                                                         */
  /* ---------------------------------------------------------------- */

  function dropSession(threadId: string): void {
    sessions.value = sessions.value.filter((s) => s.thread_id !== threadId)
    delete messagesByThread.value[threadId]
    if (pendingHitlThreadId.value === threadId) {
      pendingHitl.value = null
      pendingHitlThreadId.value = null
    }
    persistSessions()
  }

  async function switchSession(threadId: string): Promise<void> {
    if (streaming.value && streamThreadId.value !== threadId) return
    activeThreadId.value = threadId
    persistActive()
    if (pendingHitlThreadId.value !== threadId) pendingHitl.value = null
    await loadHistory(threadId)
    await useAppStore().refreshContext(threadId)
  }

  function newSession(): void {
    if (streaming.value) return
    const current = activeThreadId.value
    if (current && (messagesByThread.value[current]?.length ?? 0) === 0) dropSession(current)
    activeThreadId.value = null
    persistActive()
    pendingHitl.value = null
    pendingHitlThreadId.value = null
    useAppStore().setContextUsage(null)
  }

  function deleteSession(threadId: string): void {
    const wasActive = activeThreadId.value === threadId
    dropSession(threadId)
    if (wasActive) {
      activeThreadId.value = null
      persistActive()
      useAppStore().setContextUsage(null)
    }
  }

  function clearMessages(): void {
    if (streaming.value) return
    const threadId = activeThreadId.value
    if (!threadId) return
    messagesByThread.value[threadId] = [newNotice('已清空当前会话的本地显示（服务端历史仍保留）。')]
  }

  /** Append a local-only notice (slash-command feedback such as /help). */
  function addNotice(text: string): void {
    let threadId = activeThreadId.value
    if (!threadId) {
      threadId = `pending-${uid()}`
      activeThreadId.value = threadId
      persistActive()
    }
    pushNotice(threadId, text)
  }

  /** Rehydrate the persisted active session on app boot. */
  async function restore(): Promise<void> {
    const threadId = activeThreadId.value
    if (!threadId) return
    if (!sessions.value.some((s) => s.thread_id === threadId)) {
      activeThreadId.value = null
      persistActive()
      return
    }
    await loadHistory(threadId)
    await useAppStore().refreshContext(threadId)
  }

  return {
    sessions,
    sortedSessions,
    activeThreadId,
    activeSession,
    sessionTitle,
    messages,
    messagesByThread,
    streaming,
    streamThreadId,
    pendingHitl,
    pendingHitlThreadId,
    visibleHitl,
    send,
    resume,
    stop,
    newSession,
    switchSession,
    loadHistory,
    deleteSession,
    clearMessages,
    addNotice,
    restore,
    applyEvent: handleEvent,
  }
})
