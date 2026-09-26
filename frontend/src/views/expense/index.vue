<template>
  <section class="page" data-module="expense">
    <header class="page-head">
      <div>
        <h2>费用报销管理</h2>
        <p class="page-desc">报销单从登记(待提交) → 提交报销(待审核) → 审核通过(已通过) → 确认打款(已打款)逐级流转；待审核时可驳回，修改说明后重新提交。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记报销单</button>
        <button class="btn" type="button" @click="exportRows">导出费用报销清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label class="filter-item">
        <span>报销单号</span>
        <input v-model="filters.keyword" placeholder="按报销单号检索" />
      </label>
      <label class="filter-item">
        <span>报销状态</span>
        <select v-model="filters.status">
          <option value="">全部状态</option>
          <option v-for="status in statuses" :key="status" :value="status">{{ status }}</option>
        </select>
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
          <td class="row-actions">
            <button
              v-for="action in availableActions(row)"
              :key="action"
              class="link"
              type="button"
              :disabled="busy"
              @click="openReview(action, row)"
            >
              {{ action }}
            </button>
            <span v-if="!availableActions(row).length" class="muted-text">已归档</span>
            <button class="link" type="button" @click="openDetail(row)">详情</button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无费用报销数据，可先登记报销单</td>
        </tr>
      </tbody>
    </table>

    <section v-if="reviewDraft" class="panel" data-panel="review">
      <h3>审核操作：{{ reviewDraft.action }}</h3>
      <p class="muted-text">
        报销单 {{ reviewDraft.row['报销单号'] }}（{{ reviewDraft.row['报销人'] }}），
        当前状态「{{ reviewDraft.row['报销状态'] }}」。
        <template v-if="reviewDraft.action === '驳回报销'">驳回后需修改并重新提交，才能再次审核。</template>
      </p>
      <label class="panel-field">
        <span>修改说明{{ reviewDraft.action === '驳回报销' ? '（必填）' : '（选填）' }}</span>
        <textarea
          v-model="reviewDraft.remark"
          rows="3"
          placeholder="说明会写入审核记录，随单据永久保留"
        ></textarea>
      </label>
      <div class="panel-actions">
        <button class="btn primary" type="button" :disabled="busy" @click="confirmReview">
          {{ busy ? '提交中…' : '确认执行' }}
        </button>
        <button class="btn ghost" type="button" :disabled="busy" @click="reviewDraft = null">取消</button>
      </div>
    </section>

    <section v-if="detail" class="panel" data-panel="detail">
      <h3>报销单详情：{{ detail['报销单号'] }}</h3>
      <dl class="detail-grid">
        <template v-for="column in columns" :key="column">
          <dt>{{ column }}</dt>
          <dd>{{ detail[column] ?? '—' }}</dd>
        </template>
      </dl>
      <h4>审核记录</h4>
      <table v-if="detailHistory.length" class="data-table">
        <thead>
          <tr><th>时间</th><th>动作</th><th>操作前状态</th><th>操作后状态</th><th>修改说明</th></tr>
        </thead>
        <tbody>
          <tr v-for="(record, index) in detailHistory" :key="index">
            <td>{{ record['时间'] }}</td>
            <td>{{ record['动作'] }}</td>
            <td>{{ record['操作前状态'] }}</td>
            <td>{{ record['操作后状态'] }}</td>
            <td>{{ record['修改说明'] || '—' }}</td>
          </tr>
        </tbody>
      </table>
      <p v-else class="muted-text">还没有审核记录，提交报销后开始留痕。</p>
      <div class="panel-actions">
        <button class="btn ghost" type="button" @click="detail = null">关闭</button>
      </div>
    </section>

    <section v-if="createOpen" class="panel" data-panel="create">
      <h3>登记报销单</h3>
      <form class="create-grid" @submit.prevent="submitCreate">
        <label v-for="field in createFields" :key="field.name" class="panel-field">
          <span>{{ field.label }}{{ field.required ? '（必填）' : '' }}</span>
          <input v-model="createForm[field.name]" :placeholder="`请输入${field.label}`" />
        </label>
        <div class="panel-actions">
          <button class="btn primary" type="submit" :disabled="busy">{{ busy ? '提交中…' : '提交登记' }}</button>
          <button class="btn ghost" type="button" :disabled="busy" @click="createOpen = false">取消</button>
        </div>
      </form>
    </section>

    <footer class="page-foot">
      <span>共 {{ total }} 条费用报销记录</span>
      <span v-if="noticeMessage" class="muted-text">{{ noticeMessage }}</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null> & { id?: number }
type HistoryRecord = Record<string, string>

const ENDPOINT = '/api/expense'
const columns = ["报销单号", "报销人", "费用类别", "发生日期", "报销金额", "票据张数", "所属科目", "报销状态"]
const statuses = ["待提交", "待审核", "已通过", "已驳回", "已打款"]
// 与后端状态机一致：每个状态允许执行的动作；已打款为终态，不再出现任何动作
const ACTIONS_BY_STATUS: Record<string, string[]> = {
  "待提交": ["提交报销"],
  "待审核": ["审核通过", "驳回报销"],
  "已驳回": ["提交报销"],
  "已通过": ["确认打款"],
  "已打款": [],
}
const createFields = [
  { name: "报销单号", label: "报销单号", required: true },
  { name: "报销人", label: "报销人", required: true },
  { name: "费用类别", label: "费用类别", required: true },
  { name: "发生日期", label: "发生日期", required: false },
  { name: "报销金额", label: "报销金额", required: false },
  { name: "票据张数", label: "票据张数", required: false },
  { name: "所属科目", label: "所属科目", required: false },
]

const rows = ref<Row[]>([])
const total = ref(0)
const busy = ref(false)
const errorMessage = ref('')
const noticeMessage = ref('')
const filters = ref<Record<string, string>>({ keyword: '', status: '' })
const reviewDraft = ref<{ action: string; row: Row; remark: string } | null>(null)
const detail = ref<Row | null>(null)
const createOpen = ref(false)
const createForm = ref<Record<string, string>>({})

const stats = computed(() => [
  { label: '待审核报销', value: rows.value.filter((row) => row['报销状态'] === '待审核').length },
  { label: '报销金额合计', value: rows.value.reduce((sum, row) => sum + (Number(row['报销金额']) || 0), 0).toFixed(2) },
  { label: '已驳回报销', value: rows.value.filter((row) => row['报销状态'] === '已驳回').length },
])

const detailHistory = computed<HistoryRecord[]>(() => {
  const records = detail.value?.['审核记录']
  return Array.isArray(records) ? (records as HistoryRecord[]) : []
})

function availableActions(row: Row): string[] {
  return ACTIONS_BY_STATUS[String(row['报销状态'] ?? '')] ?? []
}

function resetFilters() {
  filters.value = { keyword: '', status: '' }
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  createForm.value = {}
  createOpen.value = true
}

function openReview(action: string, row: Row) {
  errorMessage.value = ''
  noticeMessage.value = ''
  reviewDraft.value = { action, row, remark: '' }
}

async function openDetail(row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}`)
    const payload = await parseBody(response)
    if (!response.ok) {
      throw new Error(String(payload?.detail ?? '报销单详情读取失败'))
    }
    detail.value = payload as Row
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '报销单详情读取失败'
  }
}

async function parseBody(response: Response): Promise<Record<string, unknown> | null> {
  return (await response.json().catch(() => null)) as Record<string, unknown> | null
}

async function confirmReview() {
  const draft = reviewDraft.value
  if (!draft || busy.value) return
  if (draft.action === '驳回报销' && !draft.remark.trim()) {
    errorMessage.value = '驳回报销必须填写修改说明，说明会随单据保留'
    return
  }
  busy.value = true
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${draft.row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action: draft.action }, remark: draft.remark.trim() }),
    })
    const payload = await parseBody(response)
    if (!response.ok || payload?.ok === false) {
      throw new Error(String(payload?.detail ?? payload?.message ?? '费用报销动作未生效，请稍后重试'))
    }
    noticeMessage.value = String(payload?.message ?? '操作已完成')
    reviewDraft.value = null
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '费用报销操作失败'
  } finally {
    busy.value = false
  }
}

async function submitCreate() {
  if (busy.value) return
  busy.value = true
  errorMessage.value = ''
  try {
    const response = await request(ENDPOINT, {
      method: 'POST',
      body: JSON.stringify({ values: createForm.value }),
    })
    const payload = await parseBody(response)
    if (!response.ok || payload?.ok === false) {
      throw new Error(String(payload?.detail ?? payload?.message ?? '报销单登记失败'))
    }
    noticeMessage.value = String(payload?.message ?? '报销单已登记')
    createOpen.value = false
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '报销单登记失败'
  } finally {
    busy.value = false
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams()
  if (filters.value.keyword) query.set('keyword', filters.value.keyword)
  if (filters.value.status) query.set('status', filters.value.status)
  try {
    const response = await request(`${ENDPOINT}?${query.toString()}`)
    const payload = await parseBody(response)
    if (!response.ok) {
      throw new Error(String(payload?.detail ?? '报销单列表读取失败'))
    }
    rows.value = (payload?.items as Row[]) ?? []
    total.value = Number(payload?.total ?? rows.value.length)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '费用报销列表读取失败'
  }
}

onMounted(reload)
</script>

<style scoped>
.panel {
  background: #fff;
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 12px 16px;
  margin-top: 12px;
}
.panel h3 { margin: 0 0 8px; font-size: 15px; }
.panel h4 { margin: 12px 0 6px; font-size: 13px; }
.panel-field span { display: block; font-size: 12px; color: var(--muted); margin-bottom: 4px; }
.panel-field input, .panel-field textarea {
  width: 100%;
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 6px 8px;
  font-size: 13px;
}
.panel-actions { display: flex; gap: 8px; margin-top: 10px; }
.detail-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 6px 16px;
  margin: 0;
  font-size: 13px;
}
.detail-grid dt { color: var(--muted); }
.detail-grid dd { margin: 0 0 6px; }
.create-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px 16px; }
.create-grid .panel-actions { grid-column: 1 / -1; }
.muted-text { color: var(--muted); font-size: 12px; }
.link:disabled { color: var(--muted); cursor: not-allowed; }
</style>
