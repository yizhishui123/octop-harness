/**
 * HTTP + SSE client for the chat demo backend (FastAPI, prefix `/api`).
 *
 * Chat streams are `POST` + `text/event-stream`, so `EventSource` cannot be
 * used (it is GET-only); we read the body through `ReadableStream` and split
 * frames on blank lines instead.
 */
import type { ApiAgent, ContextUsage, Decision, HistoryMessage, SSEEvent } from './types'

const API_BASE = '/api'

export interface StreamHandlers {
  onEvent: (event: SSEEvent) => void
  signal?: AbortSignal
}

export interface StreamChatBody {
  agent_id: string
  message: string
  thread_id?: string | null
  model?: string | null
}

export interface ResumeChatBody {
  agent_id: string
  thread_id: string
  decisions: Decision[]
}

async function readError(res: Response): Promise<string> {
  let detail = `${res.status} ${res.statusText}`
  try {
    const text = await res.text()
    if (text) {
      const parsed: unknown = JSON.parse(text)
      if (parsed && typeof parsed === 'object' && 'detail' in parsed) {
        detail = String((parsed as { detail: unknown }).detail)
      } else {
        detail = text.slice(0, 500)
      }
    }
  } catch {
    /* keep the status line */
  }
  return detail
}

async function getJson<T>(path: string, params?: Record<string, string | number>): Promise<T> {
  const url = new URL(API_BASE + path, window.location.origin)
  for (const [key, value] of Object.entries(params ?? {})) {
    url.searchParams.set(key, String(value))
  }
  const res = await fetch(url.toString(), { headers: { Accept: 'application/json' } })
  if (!res.ok) throw new Error(await readError(res))
  return (await res.json()) as T
}

export async function fetchAgents(): Promise<ApiAgent[]> {
  const data = await getJson<{ agents?: ApiAgent[] }>('/agents')
  return data.agents ?? []
}

export async function fetchHistory(threadId: string, agentId: string, limit = 50): Promise<HistoryMessage[]> {
  const data = await getJson<{ messages?: HistoryMessage[] }>(`/threads/${encodeURIComponent(threadId)}/history`, {
    agent_id: agentId,
    limit,
  })
  return data.messages ?? []
}

export async function fetchContextUsage(threadId: string, agentId: string): Promise<ContextUsage> {
  return await getJson<ContextUsage>(`/threads/${encodeURIComponent(threadId)}/context`, { agent_id: agentId })
}

export async function postStop(agentId: string, threadId: string): Promise<void> {
  const res = await fetch(`${API_BASE}/chat/stop`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ agent_id: agentId, thread_id: threadId }),
  })
  if (!res.ok) throw new Error(await readError(res))
}

/** Emit every complete SSE frame found in `block`. */
function emitBlock(block: string, onEvent: (event: SSEEvent) => void): void {
  const dataLines: string[] = []
  for (const line of block.split(/\r?\n/)) {
    if (line.startsWith('data:')) {
      dataLines.push(line.slice(5).replace(/^ /, ''))
    }
  }
  if (dataLines.length === 0) return
  const payload = dataLines.join('\n')
  if (!payload.trim()) return
  try {
    onEvent(JSON.parse(payload) as SSEEvent)
  } catch {
    console.warn('[sse] skipping unparsable frame', payload)
  }
}

/** Consume the buffered text, returning whatever is left of an incomplete frame. */
function drainFrames(buffer: string, onEvent: (event: SSEEvent) => void, flush = false): string {
  const parts = buffer.split(/\r?\n\r?\n/)
  const remainder = flush ? '' : (parts.pop() ?? '')
  for (const part of parts) emitBlock(part, onEvent)
  return remainder
}

async function postSSE(path: string, body: unknown, handlers: StreamHandlers): Promise<void> {
  const res = await fetch(API_BASE + path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
    body: JSON.stringify(body),
    signal: handlers.signal ?? null,
  })
  if (!res.ok) throw new Error(await readError(res))
  if (!res.body) throw new Error('响应没有可读流（response.body 为空）')

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  try {
    for (;;) {
      const { value, done } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      buffer = drainFrames(buffer, handlers.onEvent)
    }
    buffer += decoder.decode()
    drainFrames(buffer, handlers.onEvent, true)
  } finally {
    reader.releaseLock()
  }
}

export function streamChat(body: StreamChatBody, handlers: StreamHandlers): Promise<void> {
  return postSSE('/chat/stream', body, handlers)
}

export function resumeChat(body: ResumeChatBody, handlers: StreamHandlers): Promise<void> {
  return postSSE('/chat/resume', body, handlers)
}

export function isAbortError(err: unknown): boolean {
  return err instanceof DOMException ? err.name === 'AbortError' : (err as { name?: string } | null)?.name === 'AbortError'
}
