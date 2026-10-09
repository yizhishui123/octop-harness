<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import type { Decision, DecisionType, HitlActionRequest, HitlRequest } from '../types'
import { parseJsonLoose } from '../utils'

const props = defineProps<{ request: HitlRequest }>()
const emit = defineEmits<{ submit: [decisions: Decision[]] }>()

interface Row {
  action: HitlActionRequest
  allowed: DecisionType[]
  choice: DecisionType
  editText: string
  respondText: string
  rejectText: string
  argsOpen: boolean
}

const DEFAULT_DECISIONS: DecisionType[] = ['approve', 'reject']
const LABELS: Record<DecisionType, string> = {
  approve: 'Approve',
  reject: 'Reject',
  edit: 'Edit',
  respond: 'Respond',
}

const submitting = ref(false)

function buildRows(request: HitlRequest): Row[] {
  const actions = request.action_requests ?? []
  return actions.map((action) => {
    const config = (request.review_configs ?? []).find((c) => c.action_name === action.name)
    const allowed = config?.allowed_decisions?.length ? config.allowed_decisions : DEFAULT_DECISIONS
    const choice: DecisionType = allowed.includes('approve') ? 'approve' : allowed[0]
    return {
      action,
      allowed,
      choice,
      editText: JSON.stringify(action.args ?? {}, null, 2),
      respondText: '',
      rejectText: '',
      argsOpen: false,
    }
  })
}

const rows = reactive<Row[]>([])

watch(
  () => props.request,
  (request) => {
    submitting.value = false
    rows.splice(0, rows.length, ...buildRows(request))
  },
  { immediate: true, deep: false },
)

const title = computed(() => {
  const names = rows.map((row) => row.action.name).join(', ')
  return rows.some((row) => row.action.name === 'ask_user_question') ? 'Agent 需要你的回答' : `需要审批: ${names}`
})

const canSubmit = computed(() => {
  if (rows.length === 0) return false
  return rows.every((row) => {
    if (row.choice === 'edit') return parseJsonLoose(row.editText) !== undefined
    if (row.choice === 'respond') return row.respondText.trim().length > 0
    return true
  })
})

const canApproveAll = computed(() => rows.every((row) => row.allowed.includes('approve')))

function argsPreview(action: HitlActionRequest): string {
  try {
    return JSON.stringify(action.args ?? {}, null, 2)
  } catch {
    return String(action.args)
  }
}

function toDecision(row: Row): Decision {
  switch (row.choice) {
    case 'approve':
      return { type: 'approve' }
    case 'reject':
      return row.rejectText.trim() ? { type: 'reject', message: row.rejectText.trim() } : { type: 'reject' }
    case 'edit': {
      const parsed = parseJsonLoose(row.editText)
      const args = parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? (parsed as Record<string, unknown>) : {}
      return { type: 'edit', edited_action: { name: row.action.name, args } }
    }
    case 'respond':
      return { type: 'respond', message: row.respondText.trim() }
    default:
      return { type: 'approve' }
  }
}

function submit(): void {
  if (!canSubmit.value) return
  submitting.value = true
  emit('submit', rows.map(toDecision))
}

function approveAll(): void {
  for (const row of rows) {
    if (row.allowed.includes('approve')) row.choice = 'approve'
  }
  submit()
}
</script>

<template>
  <div class="approval">
    <div class="approval-head">
      <span class="approval-icon">⚠</span>
      <span class="approval-title">{{ title }}</span>
    </div>

    <div v-if="request.message" class="approval-message">{{ request.message }}</div>

    <div v-for="(row, index) in rows" :key="`${row.action.name}-${index}`" class="action">
      <div class="action-head">
        <span class="action-name mono">{{ row.action.name }}</span>
        <button class="action-toggle" type="button" @click="row.argsOpen = !row.argsOpen">
          {{ row.argsOpen ? '▾ 参数' : '▸ 参数' }}
        </button>
      </div>
      <div v-if="row.action.description" class="action-desc">{{ row.action.description }}</div>
      <pre v-if="row.argsOpen" class="action-args mono">{{ argsPreview(row.action) }}</pre>

      <div class="decisions">
        <button
          v-for="option in row.allowed"
          :key="option"
          type="button"
          class="decision"
          :class="[`is-${option}`, { active: row.choice === option }]"
          @click="row.choice = option"
        >
          {{ LABELS[option] }}
        </button>
      </div>

      <textarea
        v-if="row.choice === 'respond'"
        v-model="row.respondText"
        class="decision-input"
        rows="3"
        :placeholder="row.action.name === 'ask_user_question' ? '输入你的回答…' : '输入要回复给 agent 的内容…'"
      />

      <textarea
        v-if="row.choice === 'edit'"
        v-model="row.editText"
        class="decision-input mono"
        rows="5"
        spellcheck="false"
        placeholder='{"edited": "JSON args"}'
      />

      <input
        v-if="row.choice === 'reject'"
        v-model="row.rejectText"
        class="decision-input"
        type="text"
        placeholder="拒绝理由（可选）"
      />
    </div>

    <div class="approval-footer">
      <button v-if="canApproveAll && rows.length > 1" class="btn" type="button" :disabled="submitting" @click="approveAll">
        全部批准
      </button>
      <span class="spacer" />
      <button class="btn btn-primary" type="button" :disabled="!canSubmit || submitting" @click="submit">
        {{ submitting ? '提交中…' : '提交决定' }}
      </button>
    </div>
  </div>
</template>

<style scoped>
.approval {
  margin: 4px 0 12px;
  padding: 12px 14px;
  background: #1a1509;
  border: 1px solid #6b5320;
  border-radius: var(--radius);
}

.approval-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}

.approval-icon {
  color: var(--yellow);
}

.approval-title {
  font-weight: 600;
  font-size: 13.5px;
  color: #f0d68a;
}

.approval-message {
  margin-bottom: 8px;
  color: var(--text-dim);
  font-size: 13px;
  white-space: pre-wrap;
}

.action {
  padding: 8px 0;
  border-top: 1px solid #33280f;
}

.action-head {
  display: flex;
  align-items: center;
  gap: 10px;
}

.action-name {
  font-size: 13px;
  color: var(--text);
}

.action-toggle {
  font-size: 11.5px;
  color: var(--text-dim);
}

.action-toggle:hover {
  color: var(--text);
}

.action-desc {
  margin-top: 4px;
  color: var(--text-dim);
  font-size: 12.5px;
  white-space: pre-wrap;
}

.action-args {
  margin: 6px 0 0;
  padding: 8px 10px;
  max-height: 240px;
  overflow: auto;
  background: #0b0f14;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  font-size: 12px;
  white-space: pre-wrap;
  word-break: break-word;
}

.decisions {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 8px;
}

.decision {
  padding: 3px 10px;
  border: 1px solid var(--border-strong);
  border-radius: 999px;
  background: #12181f;
  color: var(--text-dim);
  font-size: 12.5px;
}

.decision:hover {
  color: var(--text);
  border-color: #4a5563;
}

.decision.active {
  color: #f0f6fc;
}

.decision.is-approve.active {
  background: var(--green-dim);
  border-color: #2ea043;
}

.decision.is-reject.active {
  background: #6e2b28;
  border-color: #8b3a36;
}

.decision.is-edit.active {
  background: #1f4d7a;
  border-color: var(--accent-dim);
}

.decision.is-respond.active {
  background: #5a3f8f;
  border-color: #7048b8;
}

.decision-input {
  display: block;
  width: 100%;
  margin-top: 8px;
  resize: vertical;
}

.approval-footer {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px solid #33280f;
}

.spacer {
  flex: 1;
}
</style>
