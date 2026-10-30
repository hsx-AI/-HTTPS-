<script setup>
import {nextTick, onMounted, ref} from 'vue'
import {api} from './api'
const props = defineProps({code:String,source:String})
const emit = defineEmits(['close'])
const dialog = ref(null), item = ref(null), error = ref('')
onMounted(async () => {
  await nextTick(); dialog.value.showModal()
  try { item.value = await api.detail({code:props.code,source:props.source}) }
  catch (err) { error.value = err.message }
})
function exportOriginal() {
  const cell = value => '"' + String(value ?? '').replace(/^[=+@\-\t\r]/,"'$&").replaceAll('"','""') + '"'
  const rows = [['数据平台',item.value.sourceLabel],['计划编码',item.value.displayCode],...item.value.fields.map(f=>[f.label,f.value])]
  const url = URL.createObjectURL(new Blob(['\ufeff'+rows.map(r=>r.map(cell).join(',')).join('\r\n')],{type:'text/csv;charset=utf-8'}))
  const link = document.createElement('a'); link.href=url; link.download='计划完整信息.csv'; link.click(); setTimeout(()=>URL.revokeObjectURL(url),1000)
}
</script>
<template>
  <dialog ref="dialog" class="panel detail-dialog" aria-labelledby="detail-title" @cancel.prevent="emit('close')">
    <div class="panel-heading"><div><h2 id="detail-title">计划完整信息</h2><p>{{ item?.sourceLabel }} · {{ item?.displayCode }}</p></div><button class="ghost-button" @click="emit('close')">关闭</button></div>
    <p v-if="error" class="error-banner">{{ error }}</p><p v-else-if="!item">正在读取…</p>
    <template v-else><h3>{{ item.name }}</h3><p class="help-text">以下内容按原平台表格保留。不同平台提供的信息不同，未提供的内容不会自动补填。</p><button class="ghost-button" @click="exportOriginal">导出完整信息</button>
    <dl class="original-fields"><div v-for="(field,i) in item.fields" :key="i"><dt>{{ field.label }}</dt><dd>{{ field.value || '未提供' }}</dd></div></dl></template>
  </dialog>
</template>
