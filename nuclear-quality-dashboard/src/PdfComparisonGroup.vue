<script setup>
defineProps({ group: { type: Object, required: true } })
</script>

<template>
  <article class="compare-group">
    <div class="compare-group-head">
      <div><strong>{{ group.matchCode || '文件编号缺失' }}</strong><span v-if="group.category === '待核对'" class="status-badge badge-orange">待核对</span><span v-else-if="group.ownerCount && group.mineCount" class="muted-cell">{{ group.relation }}</span></div>
      <b>我方 {{ group.mineCount }} 条 ↔ 业主 {{ group.ownerCount }} 条</b>
    </div>
    <div class="compare-sides">
      <div class="compare-side">
        <h3>我方 PDF 清单</h3>
        <p v-if="!group.mine.length" class="empty-cell">我方清单无对应记录</p>
        <div v-for="item in group.mine" :key="item.rowIndex" class="compare-record">
          <strong>{{ item.name || '未命名计划' }}</strong>
          <p>原始文件编号：{{ item.originalCode || '文件编号缺失' }}</p>
          <p>厂内编号：{{ item.internalCode || '未提供' }} · 版本号：{{ item.version || '未提供' }}</p>
          <p>审批/实施状态：{{ item.status || '未提供' }} · PDF 第 {{ item.page }} 页</p>
        </div>
      </div>
      <div class="compare-side">
        <h3>业主平台记录</h3>
        <p v-if="!group.owners.length" class="empty-cell">业主平台无对应记录</p>
        <div v-for="(item, i) in group.owners" :key="`${item.source}-${item.recordKey}-${i}`" class="compare-record">
          <span class="source-badge">{{ item.sourceLabel }}</span>
          <strong>{{ item.name || '未命名计划' }}</strong>
          <p>原始文件编号：{{ item.originalCode || '文件编号缺失' }}</p>
          <p>版本：{{ item.version || '未提供' }} · 状态：{{ item.status || '未提供' }}</p>
        </div>
      </div>
    </div>
  </article>
</template>
