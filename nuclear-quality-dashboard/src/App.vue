<script setup>
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { api } from './api'
import CatalogPanel from './CatalogPanel.vue'

const navItems = [
  { id: 'overview', label: '质量计划总览', icon: 'grid' },
  { id: 'catalog', label: '质量计划清单', icon: 'list' },
  { id: 'ledger', label: '计划台账', icon: 'list' },
  { id: 'trace', label: '流程追踪', icon: 'nodes' },
  { id: 'analysis', label: '供方分析', icon: 'chart' },
  { id: 'governance', label: '数据治理', icon: 'shield' },
]

const activeNav = ref('overview')
const project = ref('全部')
const group = ref('全部')
const period = ref('全部')
const ledgerStatus = ref('全部')
const ledgerQuery = ref('')
const ledgerPage = ref(1)
const ledgerReportLevel = ref('全部')
const ledgerCompany = ref('')
const traceQuery = ref(''), tracePage = ref(1), selectedTraceCode = ref(''), changePage = ref(1)
const catalogCompany = ref(''), catalogRefreshKey = ref(0), catalogPanel = ref(null)
const noteEditor = ref(null), noteCode = ref(''), noteToken = ref(''), noteBusy = ref(false), noteError = ref('')
const noteDialog = ref(null), noteInput = ref(null)
const availableGroups = computed(() => project.value === '全部' ? filterOptions.value.groups : (filterOptions.value.projectGroups?.[project.value] || ['全部']))
const tracePages = computed(() => Math.max(1, Math.ceil((trace.value.total || 0) / 15)))
const changePages = computed(() => Math.max(1, Math.ceil((trace.value.changeTotal || 0) / 30)))
const selectedTraceName = computed(() => trace.value.inProgress.find(item => item.code === selectedTraceCode.value)?.name || '')
const traceSelectionReady = computed(() => Boolean(selectedTraceCode.value) && trace.value.selectedCode === selectedTraceCode.value)
const loading = ref(false)
const error = ref('')
const serviceOk = ref(false)
const syncStatus = ref({ ok: false, message: '尚未检查' })
const syncStatusNote = computed(() => {
  if (!syncStatus.value.ok) return syncStatus.value.message || '请检查公网采集端和网络配置'
  const count = Number(syncStatus.value.documentCount || 0)
  return `最近推送 ${syncStatus.value.receivedAt || '未知时间'} · ${count} 条质量计划`
})

const filterOptions = ref({
  projects: ['全部'],
  groups: ['全部'],
  periods: ['全部', '近30天', '本季度', '本年度'],
  statuses: ['全部', '完成', '审查/选点', '制造方编制', '制造方审核'],
  meta: {},
})

const overview = ref({
  metrics: [],
  statusStats: [],
  companyStats: [],
  companyFootnote: '',
  reportingStats: [],
  reportingFilled: 0,
  reportingRate: 0,
  plans: [],
  unitStats: [],
  meta: {},
})

const ledger = ref({ total: 0, page: 1, pageSize: 15, items: [] })
const trace = ref({ pipeline: [], inProgress: [], recentChanges: [] })
const suppliers = ref({ ranking: [], workModes: [], supplierLevels: [], totalCompanies: 0, totalPlans: 0 })
const governance = ref({ meta: {}, fillRates: [], syncBatches: [], recentChanges: [], generatedAt: '' })

const pageTitle = computed(() => navItems.find((item) => item.id === activeNav.value)?.label || '质量计划总览')
const visiblePlans = computed(() => overview.value.plans.slice(0, 5))
const dataDate = computed(() => overview.value.meta?.lastFetchedAt || filterOptions.value.meta?.lastFetchedAt || '暂无同步')
const ledgerTotalPages = computed(() => Math.max(1, Math.ceil((ledger.value.total || 0) / (ledger.value.pageSize || 15))))

const chartTotal = (items) => (items || []).reduce((sum, item) => sum + Number(item.value || 0), 0)

function donutStyle(items) {
  const list = items || []
  const total = chartTotal(list) || 1
  let current = 0
  const stops = list.map((item) => {
    const start = current
    current += (item.value / total) * 100
    return `${item.color} ${start.toFixed(2)}% ${current.toFixed(2)}%`
  })
  if (!list.length) return { background: 'conic-gradient(#edf2f6 0 100%)' }
  return { background: `conic-gradient(from -90deg, ${stops.join(', ')})` }
}

function commonParams() {
  return { project: project.value, group: group.value, period: period.value }
}

async function loadFilters() {
  filterOptions.value = await api.filters()
  if (!filterOptions.value.projects.includes(project.value)) project.value = '全部'
  if (!availableGroups.value.includes(group.value)) group.value = '全部'
}

async function loadOverview() {
  overview.value = await api.overview(commonParams())
}

let ledgerRequest = 0, traceRequest = 0
async function loadLedger() {
  const id = ++ledgerRequest
  const data = await api.documents({
    ...commonParams(),
    status: ledgerStatus.value,
    q: ledgerQuery.value,
    reportLevel: ledgerReportLevel.value, company: ledgerCompany.value,
    page: ledgerPage.value,
    pageSize: 15,
  })
  if (id === ledgerRequest) ledger.value = data
}

async function loadTrace() {
  const id = ++traceRequest
  const data = await api.trace({ ...commonParams(), q: traceQuery.value, code: selectedTraceCode.value, page: tracePage.value, pageSize: 15, changePage: changePage.value })
  if (id === traceRequest) {
    trace.value = data
    if (selectedTraceCode.value !== data.selectedCode) selectedTraceCode.value = data.selectedCode
  }
}
function openLedger({ status = '全部', reportLevel = '全部', company = '', q = '' } = {}) {
  ledgerStatus.value = status; ledgerReportLevel.value = reportLevel; ledgerCompany.value = company; ledgerQuery.value = q; ledgerPage.value = 1
  activeNav.value = 'ledger'
}
function openCatalog(company = '') { catalogCompany.value = company; activeNav.value = 'catalog' }
function metricAction(item) {
  if (item.icon === 'check') openLedger({ status: '完成' })
  else if (item.icon === 'clock') openLedger({ status: '处理中' })
  else if (item.icon === 'document') openLedger()
  else activeNav.value = 'analysis'
}
function selectTrace(code) { selectedTraceCode.value = code; changePage.value = 1 }
async function editNote(item) {
  noteEditor.value = item; noteCode.value = item.internalCode || ''; noteError.value = ''
  await nextTick(); noteDialog.value.showModal(); noteInput.value.focus()
}
function openCatalogDocument(code) { period.value = '全部'; openLedger({ q: code }) }
async function saveNote() {
  noteBusy.value = true; noteError.value = ''
  try {
    await api.saveNote({ code: noteEditor.value.code, internalCode: noteCode.value }, noteToken.value)
    noteEditor.value = null; await loadLedger()
  } catch (err) { noteError.value = err.message }
  finally { noteBusy.value = false }
}

async function loadSuppliers() {
  suppliers.value = await api.suppliers(commonParams())
}

async function loadGovernance() {
  governance.value = await api.governance()
}

async function refreshActive() {
  loading.value = true
  error.value = ''
  try {
    const health = await api.health()
    serviceOk.value = Boolean(health.ok)
    try { syncStatus.value = await api.syncStatus() }
    catch (syncError) { syncStatus.value = { ok: false, message: syncError?.message || '连接失败' } }
    await loadFilters()
    if (activeNav.value === 'catalog') catalogRefreshKey.value++
    if (activeNav.value === 'overview') await loadOverview()
    if (activeNav.value === 'ledger') await loadLedger()
    if (activeNav.value === 'trace') await loadTrace()
    if (activeNav.value === 'analysis') await loadSuppliers()
    if (activeNav.value === 'governance') await loadGovernance()
  } catch (err) {
    serviceOk.value = false
    error.value = err?.message || String(err)
  } finally {
    loading.value = false
  }
}

function exportReport() {
  if (activeNav.value === 'catalog') { catalogPanel.value?.exportRows(); return }
  const url = api.exportUrl({
    ...commonParams(),
    status: activeNav.value === 'ledger' ? ledgerStatus.value : '全部',
    q: activeNav.value === 'ledger' ? ledgerQuery.value : '',
    reportLevel: activeNav.value === 'ledger' ? ledgerReportLevel.value : '',
    company: activeNav.value === 'ledger' ? ledgerCompany.value : '',
  })
  const link = document.createElement('a')
  link.href = url
  link.download = '质量计划台账.csv'
  link.click()
}

watch(project, () => { if (!availableGroups.value.includes(group.value)) group.value = '全部' })
watch([traceQuery, tracePage], () => { selectedTraceCode.value = ''; changePage.value = 1; if (activeNav.value === 'trace') loadTrace().catch(err => { error.value = err.message }) })
watch(traceQuery, () => { tracePage.value = 1 })
watch([selectedTraceCode, changePage], () => { if (activeNav.value === 'trace') loadTrace().catch(err => { error.value = err.message }) })
watch([project, group, period], () => {
  ledgerPage.value = 1
  tracePage.value = 1; selectedTraceCode.value = ''; changePage.value = 1
  refreshActive()
})

watch(activeNav, () => {
  refreshActive()
})

watch([ledgerStatus, ledgerQuery, ledgerReportLevel, ledgerCompany], () => {
  ledgerPage.value = 1
  if (activeNav.value === 'ledger') loadLedger().catch((err) => { error.value = err.message })
})

watch(ledgerPage, () => {
  if (activeNav.value === 'ledger') loadLedger().catch((err) => { error.value = err.message })
})

let refreshTimer
onMounted(() => {
  refreshActive()
  refreshTimer = setInterval(() => { if (!loading.value) refreshActive() }, 60000)
})
onUnmounted(() => clearInterval(refreshTimer))
</script>

<template>
  <div class="app-shell">
    <aside class="sidebar">
      <div class="brand">
        <div class="brand-mark" aria-hidden="true">
          <svg viewBox="0 0 32 32" fill="none"><path d="M16 3.5 27 8v7.3c0 6.5-4.3 10.7-11 13.2C9.3 26 5 21.8 5 15.3V8l11-4.5Z"/><path d="m11.5 15.7 3 3 6.3-6.8"/></svg>
        </div>
        <div>
          <div class="brand-title">核电质量</div>
          <div class="brand-subtitle">DATA PLATFORM</div>
        </div>
      </div>

      <div class="nav-caption">工作台</div>
      <nav class="nav-list" aria-label="主导航">
        <button
          v-for="item in navItems"
          :key="item.id"
          class="nav-item"
          :class="{ active: activeNav === item.id }"
          @click="activeNav = item.id"
        >
          <svg class="nav-icon" viewBox="0 0 24 24" fill="none" aria-hidden="true">
            <template v-if="item.icon === 'grid'">
              <rect x="3" y="3" width="7" height="7" rx="2" fill="currentColor" stroke="none"/><rect x="14" y="3" width="7" height="7" rx="2" fill="currentColor" stroke="none"/><rect x="3" y="14" width="7" height="7" rx="2" fill="currentColor" stroke="none"/><rect x="14" y="14" width="7" height="7" rx="2" fill="currentColor" stroke="none"/>
            </template>
            <template v-else-if="item.icon === 'list'"><path d="M9 5h12M9 12h12M9 19h12"/><circle cx="4" cy="5" r="1"/><circle cx="4" cy="12" r="1"/><circle cx="4" cy="19" r="1"/></template>
            <template v-else-if="item.icon === 'nodes'"><circle cx="5" cy="5" r="2"/><circle cx="19" cy="19" r="2"/><circle cx="19" cy="5" r="2"/><path d="m7 6 10 11M7 5h10"/></template>
            <template v-else-if="item.icon === 'chart'"><path d="M3 20V11l5 3V8l5 4V5l8 4v11H3Z"/><path d="M7 20v-3m5 3v-4m5 4v-3"/></template>
            <template v-else><path d="m12 2 9 4v6c0 5.4-3.5 8.9-9 11-5.5-2.1-9-5.6-9-11V6l9-4Z"/><path d="m8.5 12 2.2 2.2 4.8-5"/></template>
          </svg>
          <span>{{ item.label }}</span>
          <span v-if="activeNav === item.id" class="active-dot"></span>
        </button>
      </nav>

      <div class="sidebar-bottom">
        <div class="service-card relay-service-card">
          <div class="service-title">
            <span class="service-dot" :class="{ offline: !syncStatus.ok }"></span>
            {{ syncStatus.ok ? '公网数据同步正常' : '等待公网数据同步' }}
          </div>
          <div class="service-note">{{ syncStatusNote }}</div>
        </div>
        <div class="service-card">
          <div class="service-title">
            <span class="service-dot" :class="{ offline: !serviceOk }"></span>
            {{ serviceOk ? '数据服务正常' : '数据服务异常' }}
          </div>
          <div class="service-note">{{ serviceOk ? '已连接内网 SQLite 看板库' : '请检查看板 API' }}</div>
        </div>
        <div class="sidebar-footer"><span>核电质量计划平台</span><span>v1.0</span></div>
      </div>
    </aside>

    <main class="dashboard">
      <header class="topbar">
        <div>
          <p class="eyebrow">质量数据中心</p>
          <h1>核电质量计划数据汇聚平台</h1>
          <div class="breadcrumb">{{ pageTitle }} <span>/</span> 项目 {{ project }}</div>
        </div>
        <div class="data-date"><span class="live-dot" :class="{ offline: !serviceOk }"></span>数据截至 {{ dataDate }}</div>
      </header>

      <section class="toolbar" aria-label="筛选条件">
        <div class="filters">
          <label class="filter-control">
            <span>项目</span>
            <select v-model="project">
              <option v-for="item in filterOptions.projects" :key="item" :value="item">{{ item }}</option>
            </select>
          </label>
          <label class="filter-control">
            <span>机组</span>
            <select v-model="group">
              <option v-for="item in availableGroups" :key="item" :value="item">{{ item }}</option>
            </select>
          </label>
          <label v-if="activeNav !== 'catalog'" class="filter-control">
            <span>时间</span>
            <select v-model="period">
              <option v-for="item in filterOptions.periods" :key="item" :value="item">{{ item }}</option>
            </select>
          </label>
        </div>
        <div class="toolbar-actions">
          <button class="ghost-button" :disabled="loading" @click="refreshActive">刷新</button>
          <button class="primary-button" @click="exportReport">
            <svg viewBox="0 0 20 20" fill="none" aria-hidden="true"><path d="M10 3v9m0 0 3.5-3.5M10 12 6.5 8.5M4 14v2h12v-2"/></svg>
            导出报表
          </button>
        </div>
      </section>

      <div v-if="error" class="error-banner">加载失败：{{ error }}</div>
      <div v-else-if="loading" class="loading-banner">正在加载真实库数据…</div>

      <template v-if="activeNav === 'overview'">
        <section class="metric-grid" aria-label="关键指标">
          <button v-for="item in overview.metrics" :key="item.label" class="metric-card panel metric-button" :aria-label="`${item.label}，点击查看明细`" @click="metricAction(item)">
            <div class="metric-topline">
              <div class="metric-icon" :class="`tone-${item.tone}`">
                <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
                  <template v-if="item.icon === 'document'"><path d="M6 3h8l5 5v13H6a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2Z"/><path d="M14 3v5h5M8 13h8M8 17h6"/></template>
                  <template v-else-if="item.icon === 'check'"><path d="m5 12 4.2 4.2L19 6.5"/><circle cx="12" cy="12" r="9"/></template>
                  <template v-else-if="item.icon === 'clock'"><circle cx="12" cy="12" r="9"/><path d="M12 6.5v6l4 2.5"/></template>
                  <template v-else><rect x="4" y="4" width="16" height="16" rx="2"/><path d="M8 8h2v2H8zm6 0h2v2h-2zm-6 6h2v2H8zm6 0h2v2h-2z" fill="currentColor" stroke="none"/></template>
                </svg>
              </div>
              <span class="metric-label">{{ item.label }}</span>
            </div>
            <div class="metric-number-row"><strong>{{ item.value }}</strong><span>{{ item.unit }}</span></div>
            <div class="metric-note">{{ item.note }}</div>
            <div v-if="item.progress" class="progress-track"><span :class="`progress-${item.tone}`" :style="{ width: `${item.progress}%` }"></span></div>
          </button>
        </section>

        <section class="middle-grid">
          <article class="panel status-panel">
            <div class="panel-heading">
              <div><h2>流程状态分布</h2><p>按当前流程节点统计</p></div>
              <span class="panel-kicker">{{ chartTotal(overview.statusStats) }} 份计划</span>
            </div>
            <div class="status-content">
              <div class="donut" :style="donutStyle(overview.statusStats)">
                <div class="donut-hole"><strong>{{ chartTotal(overview.statusStats) }}</strong><span>份计划</span></div>
              </div>
              <div class="legend-list">
                <button v-for="item in overview.statusStats" :key="item.label" class="legend-row legend-button" :aria-label="`${item.label} ${item.value} 份，查看明细`" @click="openLedger({ status: item.label })">
                  <span class="legend-label"><i :style="{ background: item.color }"></i>{{ item.label }}</span>
                  <strong>{{ item.value }}</strong>
                  <span class="legend-percent">{{ chartTotal(overview.statusStats) ? (item.value / chartTotal(overview.statusStats) * 100).toFixed(1) : '0.0' }}%</span>
                </button>
              </div>
            </div>
          </article>

          <article class="panel company-panel">
            <div class="panel-heading">
              <div><h2>重点制造单位</h2><p>质量计划数量 · 前 5 家</p></div>
              <button class="text-button" @click="activeNav = 'analysis'">查看分析 <span>›</span></button>
            </div>
            <div class="bar-list">
              <div v-for="item in overview.companyStats" :key="item.fullLabel || item.label" class="bar-row">
                <span class="bar-label" :title="item.fullLabel">{{ item.label }}</span>
                <div class="bar-track"><span :style="{ width: `${overview.companyStats[0] ? item.value / overview.companyStats[0].value * 100 : 0}%`, background: item.color }"></span></div>
                <strong>{{ item.value }}</strong>
              </div>
            </div>
            <div class="chart-footnote">{{ overview.companyFootnote }}</div>
          </article>
        </section>

        <section class="bottom-grid">
          <article class="panel plans-panel">
            <div class="panel-heading plans-heading">
              <div><h2>最新质量计划记录</h2><p>平台已接入的实际记录</p></div>
              <div class="toolbar-actions"><button class="text-button" @click="openCatalog()">清单对比</button><button class="text-button" @click="openLedger()">查看台账 <span>›</span></button></div>
            </div>
            <div class="table-scroll">
              <table>
                <thead><tr><th>文件名称</th><th>文件编号</th><th>制造单位</th><th>流程状态</th><th>创建时间</th></tr></thead>
                <tbody>
                  <tr v-for="plan in visiblePlans" :key="plan.code">
                    <td class="plan-name">{{ plan.name }}</td>
                    <td class="muted-cell">{{ plan.code }}</td>
                    <td class="muted-cell">{{ plan.company }}</td>
                    <td><span class="status-badge" :class="`badge-${plan.tone}`">{{ plan.status }}</span></td>
                    <td class="muted-cell date-cell">{{ plan.date }}</td>
                  </tr>
                  <tr v-if="!visiblePlans.length"><td colspan="5" class="empty-cell">暂无数据</td></tr>
                </tbody>
              </table>
            </div>
          </article>

          <article class="panel reporting-panel">
            <div class="panel-heading">
              <div><h2>核安全报告级别</h2><p>字段填报分布</p></div>
            </div>
            <div class="reporting-content">
              <div class="donut reporting-donut" :style="donutStyle(overview.reportingStats)">
                <div class="donut-hole"><strong>{{ overview.reportingFilled }}</strong><span>已填报</span></div>
              </div>
              <div class="legend-list reporting-legend">
                <button v-for="item in overview.reportingStats" :key="item.label" class="legend-row legend-button" :aria-label="`${item.label} ${item.value} 份，查看明细`" @click="openLedger({ reportLevel: item.label })">
                  <span class="legend-label"><i :style="{ background: item.color }"></i>{{ item.label }}</span>
                  <strong>{{ item.value }}</strong>
                </button>
              </div>
            </div>
            <div class="reporting-rate"><span>报告级别字段填报率</span><strong>{{ overview.reportingRate }}%</strong></div>
          </article>
        </section>
      </template>

      <CatalogPanel v-else-if="activeNav === 'catalog'" ref="catalogPanel" :project="project" :group="group" :company="catalogCompany" :refresh-key="catalogRefreshKey" @imported="loadFilters" @clear-company="catalogCompany = ''" @open-document="openCatalogDocument" />

      <template v-else-if="activeNav === 'ledger'">
        <section class="panel page-panel">
          <div class="panel-heading plans-heading">
            <div><h2>计划台账</h2><p>共 {{ ledger.total }} 条，支持搜索与分页</p></div>
            <div class="ledger-tools"><label class="filter-control wide"><span>报送级别</span><select v-model="ledgerReportLevel"><option v-for="item in filterOptions.reportLevels || ['全部']" :key="item">{{ item }}</option></select></label>
              <label class="filter-control wide">
                <span>状态</span>
                <select v-model="ledgerStatus">
                  <option v-for="item in filterOptions.statuses" :key="item" :value="item">{{ item }}</option>
                </select>
              </label>
              <label class="search-control">
                <span>搜索</span>
                <input v-model.trim="ledgerQuery" placeholder="名称 / 编号 / 内部编号 / 制造单位" />
              </label>
            </div>
          </div>
          <p v-if="ledgerCompany" class="filter-summary">制造单位：{{ ledgerCompany }} <button class="text-button" @click="ledgerCompany = ''">清除</button></p>
          <p class="help-text">内部编号可点击备注；最新审批流程时间由源平台或导入清单提供，未提供时留空。创建时间和采集时间不作为审批时间。</p>
          <div class="table-scroll">
            <table class="dense-table">
              <thead>
                <tr>
                  <th>文件名称</th><th>文件编号</th><th>内部编号</th><th>项目 / 机组</th><th>制造单位</th><th>流程状态</th><th>报送级别</th><th>创建时间</th><th>最新审批流程时间</th><th>发起人</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="item in ledger.items" :key="item.code">
                  <td class="plan-name">{{ item.name }}</td>
                  <td class="muted-cell">{{ item.code }}</td>
                  <td><button class="inline-link" @click="editNote(item)">{{ item.internalCode || '添加备注' }}</button><small v-if="item.internalCodeSource" class="cell-secondary">{{ item.internalCodeSource }}</small></td>
                  <td class="muted-cell">{{ item.project }}<small class="cell-secondary">{{ item.unit }}</small></td>
                  <td class="muted-cell">{{ item.company }}</td>
                  <td><span class="status-badge" :class="`badge-${item.tone}`">{{ item.statusShort }}</span></td>
                  <td class="muted-cell">{{ item.reportLevel || '未填写' }}</td>
                  <td class="muted-cell">{{ item.createdAt }}</td>
                  <td class="muted-cell">{{ item.latestApprovalAt || '未提供' }}<small v-if="item.latestApprovalSource" class="cell-secondary">{{ item.latestApprovalSource }}</small></td>
                  <td class="muted-cell">{{ item.initiator }}</td>
                </tr>
                <tr v-if="!ledger.items.length"><td colspan="10" class="empty-cell">暂无匹配记录</td></tr>
              </tbody>
            </table>
          </div>
          <div class="pager">
            <button class="ghost-button" :disabled="ledgerPage <= 1" @click="ledgerPage -= 1">上一页</button>
            <span>第 {{ ledger.page }} / {{ ledgerTotalPages }} 页</span>
            <button class="ghost-button" :disabled="ledgerPage >= ledgerTotalPages" @click="ledgerPage += 1">下一页</button>
          </div>
        </section>
      </template>

      <template v-else-if="activeNav === 'trace'">
        <section class="metric-grid pipeline-grid">
          <article v-for="item in trace.pipeline" :key="item.label" class="metric-card panel">
            <div class="metric-topline">
              <div class="metric-icon" :class="`tone-${item.tone === 'purple' ? 'blue' : item.tone}`"></div>
              <span class="metric-label">{{ item.label }}</span>
            </div>
            <div class="metric-number-row"><strong>{{ item.value }}</strong><span>份</span></div>
            <div class="metric-note">当前停留在该节点</div>
          </article>
        </section>

        <section class="middle-grid">
          <article class="panel page-panel">
            <div class="panel-heading"><div><h2>处理中计划</h2><p>共 {{ trace.total || 0 }} 条 · 选择记录查看对应字段变更</p></div><label class="search-control">检索<input v-model.trim="traceQuery" placeholder="名称 / 编号 / 内部编号 / 制造单位" /></label></div>
            <div class="table-scroll">
              <table class="dense-table">
                <thead><tr><th>文件名称</th><th>文件编号</th><th>制造单位</th><th>当前节点</th><th>发起人</th><th>创建时间</th></tr></thead>
                <tbody>
                  <tr v-for="item in trace.inProgress" :key="item.code" :class="{ 'selected-row': selectedTraceCode === item.code }">
                    <td class="plan-name" :title="item.name"><button class="inline-link" :aria-pressed="selectedTraceCode === item.code" @click="selectTrace(item.code)">{{ item.name }}</button></td>
                    <td class="muted-cell">{{ item.code }}</td>
                    <td class="muted-cell">{{ item.company }}</td>
                    <td><span class="status-badge" :class="`badge-${item.tone}`">{{ item.statusShort }}</span></td>
                    <td class="muted-cell">{{ item.initiator }}</td>
                    <td class="muted-cell">{{ item.date }}</td>
                  </tr>
                  <tr v-if="!trace.inProgress.length"><td colspan="6" class="empty-cell">当前筛选下没有处理中计划</td></tr>
                </tbody>
              </table>
            </div>
            <div class="pager"><button class="ghost-button" :disabled="tracePage <= 1" @click="tracePage--">上一页</button><span>{{ tracePage }} / {{ tracePages }}</span><button class="ghost-button" :disabled="tracePage >= tracePages" @click="tracePage++">下一页</button></div>
          </article>

          <article class="panel page-panel">
            <div class="panel-heading"><div><h2>对应计划的字段变更</h2><p>{{ selectedTraceCode ? selectedTraceName : '请先选择左侧的一条计划' }}</p><p v-if="traceSelectionReady">{{ selectedTraceCode }} · 共 {{ trace.changeTotal || 0 }} 条变更</p></div></div>
            <div class="change-list">
              <div v-for="(item, index) in (traceSelectionReady ? trace.recentChanges : [])" :key="index" class="change-item">
                <div class="change-title">{{ item.code }} · {{ item.fieldName }}</div>
                <div class="change-body">{{ item.oldValue || '（空）' }} → {{ item.newValue || '（空）' }}</div>
                <div class="change-meta">{{ item.changedAt }} · {{ selectedTraceName }}<span v-if="item.sourceFile"> · {{ item.sourceFile }}</span></div>
              </div>
              <div v-if="!traceSelectionReady || !trace.recentChanges.length" class="empty-cell">{{ !selectedTraceCode ? '选择左侧计划后展开对应变更' : !traceSelectionReady ? '正在加载对应变更…' : '此计划暂无字段变更记录' }}</div>
            </div>
            <div v-if="traceSelectionReady && changePages > 1" class="pager"><button class="ghost-button" :disabled="changePage <= 1" @click="changePage--">上一页</button><span>{{ changePage }} / {{ changePages }}</span><button class="ghost-button" :disabled="changePage >= changePages" @click="changePage++">下一页</button></div>
          </article>
        </section>
      </template>

      <template v-else-if="activeNav === 'analysis'">
        <section class="metric-grid">
          <article class="metric-card panel">
            <div class="metric-topline"><span class="metric-label">制造单位数</span></div>
            <div class="metric-number-row"><strong>{{ suppliers.totalCompanies }}</strong><span>家</span></div>
          </article>
          <article class="metric-card panel">
            <div class="metric-topline"><span class="metric-label">关联计划数</span></div>
            <div class="metric-number-row"><strong>{{ suppliers.totalPlans }}</strong><span>份</span></div>
          </article>
          <article class="metric-card panel">
            <div class="metric-topline"><span class="metric-label">工作模式种类</span></div>
            <div class="metric-number-row"><strong>{{ suppliers.workModes.length }}</strong><span>类</span></div>
          </article>
          <article class="metric-card panel">
            <div class="metric-topline"><span class="metric-label">供方级别种类</span></div>
            <div class="metric-number-row"><strong>{{ suppliers.supplierLevels.length }}</strong><span>类</span></div>
          </article>
        </section>

        <section class="middle-grid">
          <article class="panel page-panel">
            <div class="panel-heading"><div><h2>供方排行</h2><p>按质量计划数量</p></div></div>
            <div class="bar-list tall-bars">
              <div v-for="item in suppliers.ranking.slice(0, 12)" :key="item.fullLabel" class="bar-row wide-bar">
                <span class="bar-label" :title="item.fullLabel">{{ item.rank }}. {{ item.label }}</span>
                <div class="bar-track"><span :style="{ width: `${suppliers.ranking[0] ? item.value / suppliers.ranking[0].value * 100 : 0}%`, background: item.color }"></span></div>
                <strong>{{ item.value }}</strong>
                <button class="text-button" @click="openCatalog(item.fullLabel)">清单对比</button>
              </div>
            </div>
          </article>

          <article class="panel page-panel">
            <div class="panel-heading"><div><h2>供方工作模式</h2><p>相关供方工作模式分布</p></div></div>
            <div class="status-content compact-status">
              <div class="donut" :style="donutStyle(suppliers.workModes)">
                <div class="donut-hole"><strong>{{ chartTotal(suppliers.workModes) }}</strong><span>份</span></div>
              </div>
              <div class="legend-list">
                <div v-for="item in suppliers.workModes" :key="item.label" class="legend-row wrap-legend">
                  <span class="legend-label"><i :style="{ background: item.color }"></i>{{ item.label }}</span>
                  <strong>{{ item.value }}</strong>
                </div>
              </div>
            </div>
          </article>
        </section>
      </template>

      <template v-else>
        <section class="metric-grid">
          <article class="metric-card panel">
            <div class="metric-topline"><span class="metric-label">库内计划</span></div>
            <div class="metric-number-row"><strong>{{ governance.meta.totalDocuments || 0 }}</strong><span>份</span></div>
            <div class="metric-note">{{ governance.meta.dbPath }}</div>
          </article>
          <article class="metric-card panel">
            <div class="metric-topline"><span class="metric-label">变更明细</span></div>
            <div class="metric-number-row"><strong>{{ governance.meta.changeCount || 0 }}</strong><span>条</span></div>
            <div class="metric-note">字段级变更累计</div>
          </article>
          <article class="metric-card panel">
            <div class="metric-topline"><span class="metric-label">最近同步</span></div>
            <div class="metric-number-row"><strong class="small-strong">{{ governance.meta.lastFetchedAt || '-' }}</strong></div>
            <div class="metric-note">documents.fetched_at</div>
          </article>
          <article class="metric-card panel">
            <div class="metric-topline"><span class="metric-label">生成时间</span></div>
            <div class="metric-number-row"><strong class="small-strong">{{ governance.generatedAt || '-' }}</strong></div>
            <div class="metric-note">治理页刷新时刻</div>
          </article>
        </section>

        <section class="middle-grid">
          <article class="panel page-panel">
            <div class="panel-heading"><div><h2>关键字段完整率</h2><p>空值视为缺失</p></div></div>
            <div class="fill-list">
              <div v-for="item in governance.fillRates" :key="item.field" class="fill-row">
                <div class="fill-label"><span>{{ item.field }}</span><strong>{{ item.rate }}%</strong></div>
                <div class="bar-track"><span :style="{ width: `${item.rate}%`, background: item.rate >= 95 ? '#27b99a' : item.rate >= 80 ? '#f4ad48' : '#e36b6b' }"></span></div>
                <div class="fill-meta">已填 {{ item.filled }} · 缺失 {{ item.missing }}</div>
              </div>
            </div>
          </article>

          <article class="panel page-panel">
            <div class="panel-heading"><div><h2>同步批次</h2><p>每次产生字段变更的同步批次</p></div></div>
            <div class="table-scroll">
              <table class="dense-table">
                <thead><tr><th>批次号</th><th>变更字段数</th><th>涉及文件</th><th>时间</th></tr></thead>
                <tbody>
                  <tr v-for="item in governance.syncBatches" :key="item.batchId">
                    <td class="muted-cell">{{ item.batchId }}</td>
                    <td>{{ item.changeCount }}</td>
                    <td>{{ item.documentCount }}</td>
                    <td class="muted-cell">{{ item.finishedAt }}</td>
                  </tr>
                  <tr v-if="!governance.syncBatches.length"><td colspan="4" class="empty-cell">还没有变更批次</td></tr>
                </tbody>
              </table>
            </div>
            <div class="change-list compact-changes">
              <div v-for="(item, index) in governance.recentChanges.slice(0, 12)" :key="index" class="change-item">
                <div class="change-title">{{ item.code }} · {{ item.fieldName }}</div>
                <div class="change-body">{{ item.oldValue || '（空）' }} → {{ item.newValue || '（空）' }}</div>
                <div class="change-meta">{{ item.changedAt }} · {{ item.syncBatchId }}</div>
              </div>
            </div>
          </article>
        </section>
      </template>

      <footer class="page-footer">
        核电质量计划数据汇聚平台
        <span>{{ loading ? '加载中' : '已连接 SQLite 实时数据' }}</span>
      </footer>
        <dialog v-if="noteEditor" ref="noteDialog" aria-labelledby="note-title" class="panel note-dialog" @cancel.prevent="!noteBusy && (noteEditor = null)">
          <h2 id="note-title">内部编号备注</h2><p>{{ noteEditor.name }}</p><p class="help-text">{{ noteEditor.code }}</p>
          <label>内部编号<input ref="noteInput" v-model.trim="noteCode" maxlength="200" placeholder="例如 0EA.657.XXXX" /></label>
          <label>维护口令<input v-model="noteToken" type="password" autocomplete="off" placeholder="向平台管理员获取" /></label>
          <p class="help-text">留空保存可清除手动备注。该备注会保留，不受后续数据同步影响。</p>
          <p v-if="noteError" class="error-banner" role="alert">{{ noteError }}</p>
          <div class="toolbar-actions"><button class="ghost-button" :disabled="noteBusy" @click="noteEditor = null">取消</button><button class="primary-button" :disabled="noteBusy || !noteToken" @click="saveNote">{{ noteBusy ? '保存中…' : '保存备注' }}</button></div>
        </dialog>
    </main>
  </div>
</template>
