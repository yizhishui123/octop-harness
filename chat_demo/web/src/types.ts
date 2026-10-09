/** Wire types for the chat demo backend (`chat_demo/server`) plus UI models. */

/* ------------------------------------------------------------------ */
/* REST payloads                                                       */
/* ------------------------------------------------------------------ */

export interface ApiModel {
  ref: string
  provider: string
  id: string
  name: string
  context_window: number
}

export interface ApiAgent {
  agent_id: string
  name: string
  default_model: string | null
  models: ApiModel[]
}

export interface HistoryToolCall {
  id: string
  name: string
  args: unknown
}

export interface HistoryMessage {
  role: 'user' | 'assistant' | 'tool' | 'system'
  content: string
  reasoning?: string
  tool_calls?: HistoryToolCall[]
  name?: string
  tool_call_id?: string
}

export const SEGMENT_KEYS = [
  'system_prompt',
  'tool_definitions',
  'rules',
  'skills',
  'mcp',
  'subagent_definitions',
  'conversation',
] as const

export type SegmentKey = (typeof SEGMENT_KEYS)[number]

export type ContextSegments = Partial<Record<SegmentKey, number>>

export interface ContextUsage {
  max_tokens: number
  used_tokens: number
  input_tokens: number
  output_tokens: number
  segments: ContextSegments
  source: 'model_request' | 'empty'
}

export interface RawUsage {
  input_tokens?: number
  output_tokens?: number
  total_tokens?: number
  [key: string]: unknown
}

/* ------------------------------------------------------------------ */
/* SSE events                                                          */
/* ------------------------------------------------------------------ */

export interface ToolResultItem {
  name: string
  tool_call_id: string
  status: 'success' | 'error'
  content: string
}

export interface HitlActionRequest {
  name: string
  args: Record<string, unknown>
  description?: string
}

export interface HitlReviewConfig {
  action_name: string
  allowed_decisions: DecisionType[]
}

export interface HitlRequest {
  action_requests: HitlActionRequest[]
  review_configs: HitlReviewConfig[]
  /** Some harness versions stamp a message for the approval card. */
  message?: string
}

export type SSEEvent =
  | { type: 'thread'; thread_id: string }
  | { type: 'token'; content: string; node?: string }
  | { type: 'reasoning'; content: string; node?: string }
  | { type: 'tool_call_chunk'; id: string; name?: string; args?: string; index?: number; node?: string }
  | { type: 'tool_result'; node?: string; results: ToolResultItem[] }
  | { type: 'state_update'; node?: string }
  | { type: 'state_snapshot'; usage?: RawUsage; context_usage?: ContextUsage }
  | { type: 'usage'; usage: RawUsage; model?: string; call_id?: string; node?: string }
  | { type: 'custom'; data: unknown }
  | { type: 'hitl_required'; request: HitlRequest }
  | { type: 'done' }
  | { type: 'error'; message: string }

/* ------------------------------------------------------------------ */
/* HITL decisions (POST /api/chat/resume)                              */
/* ------------------------------------------------------------------ */

export type DecisionType = 'approve' | 'reject' | 'edit' | 'respond'

export type Decision =
  | { type: 'approve' }
  | { type: 'reject'; message?: string }
  | { type: 'edit'; edited_action: { name: string; args: Record<string, unknown> } }
  | { type: 'respond'; message: string }

/* ------------------------------------------------------------------ */
/* UI models                                                          */
/* ------------------------------------------------------------------ */

export type MessageRole = 'user' | 'assistant' | 'tool' | 'system'

export type ToolCallStatus = 'running' | 'success' | 'error'

export interface ToolCallItem {
  id: string
  name: string
  /** Raw JSON fragments accumulated from `tool_call_chunk` events. */
  argsText: string
  status: ToolCallStatus
  result?: string
  error?: string
  startedAt: number
  endedAt?: number
}

export interface MessageUsage {
  input: number
  output: number
  total: number
}

export interface ChatMessage {
  id: string
  role: MessageRole
  content: string
  reasoning?: string
  toolCalls: ToolCallItem[]
  createdAt: number
  /** True while SSE deltas are still landing in this message. */
  streaming?: boolean
  /** Set when the user hit stop before the stream finished. */
  stopped?: boolean
  error?: string
  /** Small grey system/notice line (custom events, /help output, ...). */
  notice?: boolean
  usage?: MessageUsage
  durationMs?: number
  reasoningStartedAt?: number
  reasoningEndedAt?: number
}

export interface SessionMeta {
  thread_id: string
  agent_id: string
  title: string
  updateTime: number
}

export interface TurnUsage {
  input: number
  output: number
  total: number
}
