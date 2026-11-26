<script setup>
import { computed, ref, watch } from 'vue'
import { api } from './api'
import PdfComparisonGroup from './PdfComparisonGroup.vue'
const props = defineProps({ source: String, project: String, group: String, company: { type: String, default: '' }, refreshKey: Number })
const emit = defineEmits(['imported', 'open-document', 'clear-company'])
const importOpen = ref(false), token = ref(''), file = ref(null), preview = ref(null), busy = ref(false), notice = ref(''), importError = ref('')
const pdfOpen = ref(false), pdfList = ref({ headers: [], batch: null, rows: [], total: 0 }), pdfPage = ref(1), pdfLoading = ref(false), pdfError = ref('')
const comparison = ref({ hasPdf: false, batch: null, sections: {} })
const compareQuery = ref(''), compareLoading = ref(false), compareError = ref('')
const sectionPages = ref({ oneToMany: 1, otherMatched: 1, mineOnly: 1, ownerOnly: 1, review: 1 })
const section = key => comparison.value.sections?.[key] || { total: 0, groups: [], page: 1, pageSize: 20 }
const isPdf = computed(() => file.value?.name.toLowerCase().endsWith('.pdf'))
const pdfTotalPages = computed(() => Math.max(1, Math.ceil(pdfList.value.total / 50)))
watch(() => props.refreshKey, () => loadComparison(), { immediate: true })
let compareSequence = 0
async function loadComparison() {
  const id = ++compareSequence
  compareLoading.value = true; compareError.value = ''
  try {
    const pages = sectionPages.value
    const data = await api.comparePdfSections({ q: compareQuery.value, oneToManyPage: pages.oneToMany, otherMatchedPage: pages.otherMatched, mineOnlyPage: pages.mineOnly, ownerOnlyPage: pages.ownerOnly, reviewPage: pages.review })
    if (id === compareSequence) comparison.value = data
  } catch (err) { if (id === compareSequence) compareError.value = err.message }
  finally { if (id === compareSequence) compareLoading.value = false }
}
watch(compareQuery, () => { sectionPages.value = { oneToMany: 1, otherMatched: 1, mineOnly: 1, ownerOnly: 1, review: 1 }; loadComparison() })
function changeSectionPage(key, delta) { sectionPages.value = { ...sectionPages.value, [key]: sectionPages.value[key] + delta }; loadComparison() }
async function previewFile(sheet = '') {
  if (!file.value || !token.value) { importError.value = '请选择清单文件并输入导入口令'; return }
  busy.value = true; importError.value = ''; notice.value = ''
  try { preview.value = isPdf.value ? await api.previewPdfCatalog(file.value, token.value) : await api.previewCatalog(file.value, token.value, sheet, props.source) }
  catch (err) { preview.value = null; importError.value = err.message }
  finally { busy.value = false }
}
function chooseFile(event) { file.value = event.target.files[0] || null; preview.value = null; importError.value = ''; if (isPdf.value && token.value) previewFile() }
function maybePreviewPdf() { if (isPdf.value && token.value && !preview.value && !busy.value) previewFile() }
function toggleImport() { importOpen.value = !importOpen.value; if (!importOpen.value) { file.value = null; preview.value = null; importError.value = '' } }
async function loadPdf() {
  pdfLoading.value = true; pdfError.value = ''
  try { pdfList.value = await api.latestPdfCatalog({ page: pdfPage.value, pageSize: 50 }) }
  catch (err) { pdfError.value = err.message }
  finally { pdfLoading.value = false }
}
function togglePdf() { pdfOpen.value = !pdfOpen.value; if (pdfOpen.value) { pdfPage.value = 1; loadPdf() } }
watch(pdfPage, () => { if (pdfOpen.value) loadPdf() })
async function commit() {
  busy.value = true; importError.value = ''
  try {
    if (isPdf.value) {
      const data = await api.importPdfCatalog(file.value, token.value)
      notice.value = `PDF 清单已保存：${data.rowCount} 行，命中 ${data.matchedPages.length} 页。`
      if (pdfOpen.value) { pdfPage.value = 1; await loadPdf() }
      sectionPages.value = { oneToMany: 1, otherMatched: 1, mineOnly: 1, ownerOnly: 1, review: 1 }; await loadComparison()
    } else {
      const data = await api.importCatalog({ source: props.source, rows: preview.value.rows, mapping: preview.value.mapping, filename: file.value.name }, token.value)
      notice.value = `导入完成：新增 ${data.inserted} 条，更新 ${data.updated} 条。`
      emit('imported')
    }
    preview.value = null
  } catch (err) { importError.value = err.message }
  finally { busy.value = false }
}
function downloadTemplate() {
  const blob = new Blob(['\ufeff计划名称,文件编号,内部编号,所属项目,适用机组号,制造单位,计划完成时间,最近审批时间,数据平台\r\n'], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob), link = document.createElement('a')
  link.href = url; link.download = '质量计划清单模板.csv'; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000)
}
function exportRows() { window.location.href = api.catalogExportUrl({ source: props.source, project: props.project, group: props.group, company: props.company }) }
defineExpose({ exportRows })
</script>
<template>
  <section class="panel page-panel catalog-intro">
    <div class="panel-heading">
      <div><h2>质量计划清单与执行对比</h2><p>导入计划清单，对照平台已接入的计划查看执行情况。</p></div>
      <div class="toolbar-actions"><button class="ghost-button" @click="downloadTemplate">下载表头模板</button><button class="ghost-button" @click="togglePdf">{{ pdfOpen ? '收起完整清单' : '查看完整清单' }}</button><button class="primary-button" :disabled="busy" @click="toggleImport">{{ importOpen ? '取消导入' : '导入清单' }}</button></div>
    </div>
    <p class="help-text">本页按最近一次成功导入的 PDF 清单与 AE、广核记录对比；同一文件编号分为一组，各版本分别保留。Excel/CSV 导入仍可使用，但不参与下方 PDF 对比。</p>
    <p v-if="props.company" class="filter-summary">当前供方：{{ props.company }} <button class="text-button" @click="emit('clear-company')">清除供方筛选</button></p>
    <div v-if="notice" class="success-banner" role="status">{{ notice }}</div>
    <div v-if="importOpen" class="import-form">
      <div class="import-controls">
        <label>清单文件（PDF / Excel / CSV）<input type="file" accept=".pdf,.xlsx,.xls,.csv" :disabled="busy" @change="chooseFile" /></label>
        <label>维护密码<input v-model="token" type="password" autocomplete="off" placeholder="向平台管理员获取" :disabled="busy" @change="maybePreviewPdf" /></label>
        <button class="primary-button" :disabled="busy || !file || !token" @click="previewFile()">{{ busy ? '处理中…' : isPdf ? '重新识别 PDF' : '查看表格并对应列' }}</button>
      </div>
      <p class="help-text" v-if="isPdf">PDF 按固定 11 列识别，确认后作为独立批次保存；不会改变现有计划对照统计。扫描件暂不支持。</p>
      <p class="help-text" v-else>同一平台、项目、机组和编号的计划会更新，其他计划保留。内部编号和审批时间按清单原样保存。</p>
      <div v-if="importError" class="error-banner" role="alert">{{ importError }}</div>
      <div v-if="preview && isPdf">
        <p class="help-text">识别到 {{ preview.matchedPageCount }} 页，共 {{ preview.rowCount }} 条（PDF 共 {{ preview.totalPages }} 页；命中第 {{ preview.matchedPages.join('、') }} 页）。请从首行检查到末行，再确认导入。</p>
        <div class="table-scroll pdf-preview-scroll" tabindex="0" aria-label="PDF 清单全部识别结果，可上下和左右滚动"><table class="dense-table pdf-full-table"><thead><tr><th v-for="header in preview.headers" :key="header">{{ header }}</th></tr></thead><tbody><tr v-for="(row, i) in preview.rows" :key="i"><td v-for="(cell, j) in row.values" :key="j">{{ cell }}</td></tr></tbody></table></div>
        <button class="primary-button import-submit" :disabled="busy" @click="commit">确认导入 {{ preview.rowCount }} 行</button>
      </div>
      <div v-else-if="preview">
        <label v-if="preview.sheets.length > 1" class="filter-control sheet-select">工作表<select :value="preview.sheet" :disabled="busy" @change="previewFile($event.target.value)"><option v-for="sheet in preview.sheets" :key="sheet">{{ sheet }}</option></select></label>
        <p class="help-text">表头在第 {{ preview.headerRow }} 行，共 {{ preview.rows.length }} 条。请核对每列对应的信息，并检查前 5 条内容后导入。</p>
        <div class="mapping-grid"><label v-for="field in preview.fields" :key="field.key">{{ field.label }}{{ field.key === 'name' ? ' *' : '' }}<select v-model="preview.mapping[field.key]" :disabled="busy"><option :value="-1">不在表格中</option><option v-for="(header, i) in preview.headers" :value="i" :key="i">{{ header }}（第 {{ i+1 }} 列）</option></select></label></div>
        <div class="table-scroll"><table><thead><tr><th v-for="field in preview.fields" :key="field.key">{{ field.label }}</th></tr></thead><tbody><tr v-for="(row, i) in preview.rows.slice(0,5)" :key="i"><td v-for="field in preview.fields" :key="field.key">{{ row[preview.mapping[field.key]] || '未提供' }}</td></tr></tbody></table></div>
        <button class="primary-button import-submit" :disabled="busy || preview.mapping.name < 0" @click="commit">确认导入 {{ preview.rows.length }} 条</button>
      </div>
    </div>
  </section>
  <section v-if="pdfOpen" class="panel page-panel">
    <div class="panel-heading"><div><h2>最近一次 PDF 完整清单</h2><p v-if="pdfList.batch">{{ pdfList.batch.filename }} · {{ pdfList.batch.importedAt }} · 共 {{ pdfList.total }} 行 · 命中第 {{ pdfList.batch.matchedPages.join('、') }} 页</p><p v-else>还没有成功导入的 PDF 清单。</p></div></div>
    <p v-if="pdfLoading" class="help-text" role="status">正在读取完整清单…</p>
    <div v-if="pdfError" class="error-banner" role="alert">{{ pdfError }}</div>
    <div v-if="pdfList.batch" class="table-scroll"><table class="dense-table pdf-full-table"><thead><tr><th v-for="header in pdfList.headers" :key="header">{{ header }}</th></tr></thead><tbody><tr v-for="row in pdfList.rows" :key="row.index"><td v-for="(cell, i) in row.values" :key="i">{{ cell }}</td></tr></tbody></table></div>
    <div v-if="pdfList.batch" class="pager"><span>共 {{ pdfList.total }} 行</span><button class="ghost-button" :disabled="pdfPage <= 1 || pdfLoading" @click="pdfPage--">上一页</button><span>{{ pdfPage }} / {{ pdfTotalPages }}</span><button class="ghost-button" :disabled="pdfPage >= pdfTotalPages || pdfLoading" @click="pdfPage++">下一页</button></div>
  </section>
  <article class="panel page-panel compare-bucket">
    <div class="panel-heading plans-heading">
      <div><h2>我方一对多 <span class="compare-count">{{ section('oneToMany').total }} 组</span></h2><p>我方一条 PDF 清单，对应多条 AE／广核记录。</p></div>
      <label class="search-control">文件编号<input v-model.trim="compareQuery" placeholder="按文件编号查找" /></label>
    </div>
    <div v-if="compareError" class="error-banner" role="alert">{{ compareError }}</div>
    <p v-if="compareLoading" class="help-text" role="status">正在读取计划对比…</p>
    <p v-if="!comparison.hasPdf && !compareLoading" class="help-text">请先导入 PDF 清单。</p>
    <div class="compare-groups">
      <PdfComparisonGroup v-for="group in section('oneToMany').groups" :key="group.key" :group="group" />
      <p v-if="!section('oneToMany').total" class="empty-cell">暂无记录</p>
    </div>
    <div v-if="section('oneToMany').total > 20" class="pager"><span>第 {{ section('oneToMany').page }} / {{ Math.ceil(section('oneToMany').total / 20) }} 页</span><button class="ghost-button" :disabled="sectionPages.oneToMany <= 1 || compareLoading" @click="changeSectionPage('oneToMany', -1)">上一页</button><button class="ghost-button" :disabled="sectionPages.oneToMany * 20 >= section('oneToMany').total || compareLoading" @click="changeSectionPage('oneToMany', 1)">下一页</button></div>
    <details class="compare-extra"><summary>其他已匹配记录（{{ section('otherMatched').total }} 组）</summary>
      <div class="compare-groups"><PdfComparisonGroup v-for="group in section('otherMatched').groups" :key="group.key" :group="group" /><p v-if="!section('otherMatched').total" class="empty-cell">暂无记录</p></div>
      <div v-if="section('otherMatched').total > 20" class="pager"><span>第 {{ section('otherMatched').page }} / {{ Math.ceil(section('otherMatched').total / 20) }} 页</span><button class="ghost-button" :disabled="sectionPages.otherMatched <= 1 || compareLoading" @click="changeSectionPage('otherMatched', -1)">上一页</button><button class="ghost-button" :disabled="sectionPages.otherMatched * 20 >= section('otherMatched').total || compareLoading" @click="changeSectionPage('otherMatched', 1)">下一页</button></div>
    </details>
    <details class="compare-extra"><summary>待核对（{{ section('review').total }} 组）</summary>
      <p class="help-text">缺失或无法确认的文件编号保留原值，不归入单边结果。</p>
      <div class="compare-groups"><PdfComparisonGroup v-for="group in section('review').groups" :key="group.key" :group="group" /><p v-if="!section('review').total" class="empty-cell">暂无记录</p></div>
      <div v-if="section('review').total > 20" class="pager"><span>第 {{ section('review').page }} / {{ Math.ceil(section('review').total / 20) }} 页</span><button class="ghost-button" :disabled="sectionPages.review <= 1 || compareLoading" @click="changeSectionPage('review', -1)">上一页</button><button class="ghost-button" :disabled="sectionPages.review * 20 >= section('review').total || compareLoading" @click="changeSectionPage('review', 1)">下一页</button></div>
    </details>
  </article>
  <article class="panel page-panel compare-bucket">
    <div class="panel-heading plans-heading"><div><h2>仅我方有 <span class="compare-count">{{ section('mineOnly').total }} 组</span></h2></div></div>
    <div class="compare-groups"><PdfComparisonGroup v-for="group in section('mineOnly').groups" :key="group.key" :group="group" /><p v-if="!section('mineOnly').total" class="empty-cell">暂无记录</p></div>
    <div v-if="section('mineOnly').total > 20" class="pager"><span>第 {{ section('mineOnly').page }} / {{ Math.ceil(section('mineOnly').total / 20) }} 页</span><button class="ghost-button" :disabled="sectionPages.mineOnly <= 1 || compareLoading" @click="changeSectionPage('mineOnly', -1)">上一页</button><button class="ghost-button" :disabled="sectionPages.mineOnly * 20 >= section('mineOnly').total || compareLoading" @click="changeSectionPage('mineOnly', 1)">下一页</button></div>
  </article>
  <article class="panel page-panel compare-bucket">
    <div class="panel-heading plans-heading"><div><h2>仅业主有 <span class="compare-count">{{ section('ownerOnly').total }} 组</span></h2></div></div>
    <div class="compare-groups"><PdfComparisonGroup v-for="group in section('ownerOnly').groups" :key="group.key" :group="group" /><p v-if="!section('ownerOnly').total" class="empty-cell">暂无记录</p></div>
    <div v-if="section('ownerOnly').total > 20" class="pager"><span>第 {{ section('ownerOnly').page }} / {{ Math.ceil(section('ownerOnly').total / 20) }} 页</span><button class="ghost-button" :disabled="sectionPages.ownerOnly <= 1 || compareLoading" @click="changeSectionPage('ownerOnly', -1)">上一页</button><button class="ghost-button" :disabled="sectionPages.ownerOnly * 20 >= section('ownerOnly').total || compareLoading" @click="changeSectionPage('ownerOnly', 1)">下一页</button></div>
  </article>
</template>
