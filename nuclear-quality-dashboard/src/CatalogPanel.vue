<script setup>
import { computed, ref, watch } from 'vue'
import { api } from './api'
const props = defineProps({ project: String, group: String, company: { type: String, default: '' }, refreshKey: Number })
const emit = defineEmits(['imported', 'open-document', 'clear-company'])
const result = ref({ items: [], summary: {}, plannedTotal: 0, total: 0, completionRate: 0, extraCount: 0 })
const status = ref('全部'), query = ref(''), page = ref(1), loading = ref(false), error = ref('')
const importOpen = ref(false), token = ref(''), file = ref(null), preview = ref(null), busy = ref(false), notice = ref(''), importError = ref('')
const totalPages = computed(() => Math.max(1, Math.ceil(result.value.total / 20)))
const states = [
  { value: '全部', label: '全部' }, { value: '已完成', label: '已完成' },
  { value: '处理中', label: '正在办理' }, { value: '未接入', label: '平台还没有这份计划' },
  { value: '待核对', label: '需要核对' }, { value: '清单外记录', label: '平台有、清单未列出' },
]
const stateLabel = value => states.find(item => item.value === value)?.label || value
let sequence = 0
async function load() {
  const id = ++sequence
  loading.value = true; error.value = ''
  try { const data = await api.catalog({ project: props.project, group: props.group, company: props.company, q: query.value, status: status.value, page: page.value, pageSize: 20 }); if (id === sequence) result.value = data }
  catch (err) { if (id === sequence) error.value = err.message }
  finally { if (id === sequence) loading.value = false }
}
watch(() => [props.project, props.group, props.company, props.refreshKey], () => { page.value = 1; load() }, { immediate: true })
watch([status, query], () => { page.value = 1; load() })
watch(page, load)
async function previewFile(sheet = '') {
  if (!file.value || !token.value) { importError.value = '请选择清单文件并输入导入口令'; return }
  busy.value = true; importError.value = ''; notice.value = ''
  try { preview.value = await api.previewCatalog(file.value, token.value, sheet) }
  catch (err) { preview.value = null; importError.value = err.message }
  finally { busy.value = false }
}
function chooseFile(event) { file.value = event.target.files[0] || null; preview.value = null; importError.value = '' }
async function commit() {
  busy.value = true; importError.value = ''
  try {
    const data = await api.importCatalog({ rows: preview.value.rows, mapping: preview.value.mapping, filename: file.value.name }, token.value)
    notice.value = `导入完成：新增 ${data.inserted} 条，更新 ${data.updated} 条。`
    preview.value = null; status.value = '全部'; page.value = 1
    emit('imported'); await load()
  } catch (err) { importError.value = err.message }
  finally { busy.value = false }
}
function downloadTemplate() {
  const blob = new Blob(['\ufeff计划名称,文件编号,内部编号,所属项目,适用机组号,制造单位,计划完成时间,最近审批时间\r\n'], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob), link = document.createElement('a')
  link.href = url; link.download = '质量计划清单模板.csv'; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000)
}
function exportRows() { window.location.href = api.catalogExportUrl({ project: props.project, group: props.group, company: props.company, q: query.value, status: status.value }) }
defineExpose({ exportRows })
</script>
<template>
  <section class="panel page-panel catalog-intro">
    <div class="panel-heading">
      <div><h2>质量计划清单与执行对比</h2><p>导入计划清单，对照平台已接入的计划查看执行情况。</p></div>
      <div class="toolbar-actions"><button class="ghost-button" @click="downloadTemplate">下载表头模板</button><button class="primary-button" @click="importOpen = !importOpen">{{ importOpen ? '收起导入' : '导入清单' }}</button></div>
    </div>
    <p class="help-text">先按文件编号查找；没有文件编号时按内部编号查找；如果也没有，就一起核对计划名称、项目和机组。可能对应多份计划时会标为“需要核对”。完成率按清单里的计划总数计算。</p>
    <p v-if="props.company" class="filter-summary">当前供方：{{ props.company }} <button class="text-button" @click="emit('clear-company')">清除供方筛选</button></p>
    <div v-if="notice" class="success-banner" role="status">{{ notice }}</div>
    <div v-if="importOpen" class="import-form">
      <div class="import-controls">
        <label>清单文件（Excel / CSV）<input type="file" accept=".xlsx,.xls,.csv" :disabled="busy" @change="chooseFile" /></label>
        <label>维护密码<input v-model="token" type="password" autocomplete="off" placeholder="向平台管理员获取" :disabled="busy" /></label>
        <button class="primary-button" :disabled="busy || !file || !token" @click="previewFile()">{{ busy ? '处理中…' : '查看表格并对应列' }}</button>
      </div>
      <p class="help-text">同一项目、机组和编号的计划会更新，其他计划保留。内部编号和审批时间按清单原样保存。</p>
      <div v-if="importError" class="error-banner" role="alert">{{ importError }}</div>
      <div v-if="preview">
        <label v-if="preview.sheets.length > 1" class="filter-control sheet-select">工作表<select :value="preview.sheet" :disabled="busy" @change="previewFile($event.target.value)"><option v-for="sheet in preview.sheets" :key="sheet">{{ sheet }}</option></select></label>
        <p class="help-text">表头在第 {{ preview.headerRow }} 行，共 {{ preview.rows.length }} 条。请核对每列对应的信息，并检查前 5 条内容后导入。</p>
        <div class="mapping-grid"><label v-for="field in preview.fields" :key="field.key">{{ field.label }}{{ field.key === 'name' ? ' *' : '' }}<select v-model="preview.mapping[field.key]" :disabled="busy"><option :value="-1">不在表格中</option><option v-for="(header, i) in preview.headers" :value="i" :key="i">{{ header }}（第 {{ i+1 }} 列）</option></select></label></div>
        <div class="table-scroll"><table><thead><tr><th v-for="field in preview.fields" :key="field.key">{{ field.label }}</th></tr></thead><tbody><tr v-for="(row, i) in preview.rows.slice(0,5)" :key="i"><td v-for="field in preview.fields" :key="field.key">{{ row[preview.mapping[field.key]] || '未提供' }}</td></tr></tbody></table></div>
        <button class="primary-button import-submit" :disabled="busy || preview.mapping.name < 0" @click="commit">确认导入 {{ preview.rows.length }} 条</button>
      </div>
    </div>
  </section>
  <section class="metric-grid catalog-metrics">
    <button class="metric-card panel metric-button" @click="status = '全部'"><span class="metric-label">清单中的计划</span><div class="metric-number-row"><strong>{{ result.plannedTotal }}</strong><span>项</span></div><div class="metric-note">完成率 {{ result.completionRate }}%</div></button>
    <button v-for="state in ['已完成','处理中','未接入']" :key="state" class="metric-card panel metric-button" @click="status = state"><span class="metric-label">{{ stateLabel(state) }}</span><div class="metric-number-row"><strong>{{ result.summary[state] || 0 }}</strong><span>项</span></div><div class="metric-note">点击查看计划</div></button>
  </section>
  <section class="panel page-panel">
    <div class="panel-heading plans-heading"><div><h2>计划对照明细</h2><p>需要核对 {{ result.summary['待核对'] || 0 }} 项 · 平台有、清单未列出 {{ result.extraCount }} 项</p></div><div class="ledger-tools"><label class="filter-control wide">查看<select v-model="status"><option v-for="state in states" :key="state.value" :value="state.value">{{ state.label }}</option></select></label><label class="search-control">搜索<input v-model.trim="query" placeholder="名称 / 编号 / 内部编号 / 制造单位" /></label><button class="ghost-button" @click="exportRows">导出对照结果</button></div></div>
      <div v-if="error" class="error-banner" role="alert">{{ error }}</div><p v-if="loading" class="help-text" role="status">正在对照计划清单…</p>
    <div class="table-scroll"><table class="dense-table comparison-table"><thead><tr><th>计划名称</th><th>文件编号 / 内部编号</th><th>项目 / 机组</th><th>制造单位</th><th>计划完成时间</th><th>对照结果</th><th>当前流程</th><th>最近审批时间</th><th>对应方式</th></tr></thead><tbody>
      <tr v-for="item in result.items" :key="item.id"><td class="plan-name" :title="item.name"><button v-if="item.actual" class="inline-link" @click="emit('open-document', item.actual.code)">{{ item.name }}</button><span v-else>{{ item.name }}</span></td><td>{{ item.code || '未提供' }}<small class="cell-secondary">{{ item.actual?.internalCode || item.internalCode || '还没有内部编号' }}</small></td><td>{{ item.project || '未提供' }}<small class="cell-secondary">{{ item.unit || '未提供' }}</small></td><td>{{ item.company || item.actual?.company || '未提供' }}</td><td>{{ item.plannedDate || '未提供' }}</td><td><span class="status-badge" :class="item.comparisonStatus === '已完成' ? 'badge-green' : 'badge-orange'">{{ stateLabel(item.comparisonStatus) }}</span></td><td>{{ item.actual?.statusShort || '—' }}</td><td>{{ item.actual?.latestApprovalAt || item.latestApprovalAt || '未提供' }}</td><td>{{ item.comparisonStatus === '待核对' ? '有多条可能记录，请核对' : item.matchMethod === '文件编号' ? '文件编号相同' : item.matchMethod === '内部编号' ? '内部编号相同' : item.matchMethod === '名称＋项目＋机组' ? '名称、项目和机组相同' : '—' }}</td></tr>
      <tr v-if="!result.items.length"><td colspan="9" class="empty-cell">{{ result.plannedTotal ? '没有符合筛选条件的记录' : '还没有计划清单，请先导入。未列入清单的平台计划可在“清单外记录”中查看。' }}</td></tr>
    </tbody></table></div>
    <div class="pager"><span>共 {{ result.total }} 条</span><button class="ghost-button" :disabled="page <= 1" @click="page--">上一页</button><span>{{ page }} / {{ totalPages }}</span><button class="ghost-button" :disabled="page >= totalPages" @click="page++">下一页</button></div>
  </section>
</template>
