<template>
  <section class="page" data-module="expense">
    <header class="page-head">
      <div>
        <h2>费用报销管理</h2>
        <p class="page-desc">维护报销单，围绕报销单号、报销人、费用类别、发生日期做登记、筛选与状态流转。</p>
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
      <label v-for="field in filterFields" :key="field" class="filter-item">
        <span>{{ field }}</span>
        <input v-model="filters[field]" :placeholder="`按${field}检索`" />
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
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
            <span v-if="!availableActions(row).length" class="muted">已打款，记录已封存</span>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无费用报销数据，可先登记报销单</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条费用报销记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>

const ENDPOINT = '/api/expense'
const columns = ["报销单号", "报销人", "费用类别", "发生日期", "报销金额", "票据张数", "所属科目", "报销状态", "最近说明"]
// 状态机与后端一致：每个状态只允许对应的动作，已打款为终态不可再操作。
const ACTIONS_BY_STATUS: Record<string, string[]> = {
  '待提交': ['提交报销'],
  '待审核': ['审核通过', '驳回报销'],
  '已驳回': ['提交报销'],
  '已通过': ['确认打款'],
  '已打款': [],
}
const statuses = ["待提交", "待审核", "已通过", "已驳回", "已打款"]
const stats = [{"label": "待审核报销", "value": 0}, {"label": "本月报销额", "value": 0}, {"label": "已驳回报销", "value": 0}]

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)

function availableActions(row: Row): string[] {
  return ACTIONS_BY_STATUS[String(row['报销状态'] ?? '')] ?? []
}

function resetFilters() {
  filters.value = {}
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  errorMessage.value = '报销单登记入口尚未接入审批流'
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  let remark = ''
  if (action === '驳回报销') {
    // 驳回必须留下说明，说明会写入流转记录，避免修改意见丢失。
    const input = window.prompt('请填写驳回说明（将写入流转记录）')
    if (input === null) return
    remark = input.trim()
    if (!remark) {
      errorMessage.value = '驳回报销必须填写说明'
      return
    }
  }
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action }, remark }),
    })
    const result = await response.json()
    if (!response.ok || !result.ok) {
      throw new Error(result.message ?? result.detail ?? '费用报销动作未生效，请稍后重试')
    }
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '费用报销操作失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams(filters.value as Record<string, string>).toString()
  try {
    const response = await request(`${ENDPOINT}?${query}`)
    if (!response.ok) {
      throw new Error('报销单列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '费用报销列表读取失败'
  }
}

onMounted(reload)
</script>
