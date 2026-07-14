<template>
  <div class="chat-view">
    <!-- 问题输入区 -->
    <div class="input-section">
      <el-card shadow="hover">
        <div class="input-container">
          <div class="mode-switch">
            <el-radio-group v-model="chatStore.agentMode" size="small">
              <el-radio-button :value="true">
                <el-icon><MagicStick /></el-icon> Agent模式
              </el-radio-button>
              <el-radio-button :value="false">
                <el-icon><Search /></el-icon> RAG模式
              </el-radio-button>
            </el-radio-group>
            <el-tooltip v-if="chatStore.agentMode" content="Agent模式：LLM自主决策调用工具，支持实时外部检索和自进化" placement="right">
              <el-icon class="mode-hint"><InfoFilled /></el-icon>
            </el-tooltip>
          </div>
          <el-input
            v-model="queryInput"
            type="textarea"
            :rows="3"
            placeholder="请输入临床问题，例如：糖尿病合并高血压患者首选哪类降压药？"
            resize="none"
            :disabled="chatStore.isLoading"
          />
          <div class="input-actions">
            <el-button type="primary" @click="handleQuery" :loading="chatStore.isLoading">
              <el-icon><Promotion /></el-icon>
              提交问题
            </el-button>
          </div>
        </div>
        
        <!-- 示例问题 -->
        <div class="example-queries">
          <span class="example-label">示例问题：</span>
          <el-tag 
            v-for="example in exampleQueries" 
            :key="example"
            class="example-tag"
            @click="queryInput = example"
          >
            {{ example }}
          </el-tag>
        </div>
      </el-card>
    </div>

    <!-- Agent工具调用面板 -->
    <el-card v-if="chatStore.toolCalls.length > 0" class="tool-calls-card" shadow="hover">
      <template #header>
        <div class="card-header">
          <el-icon><SetUp /></el-icon>
          <span>Agent工具调用 ({{ chatStore.toolCalls.length }}次)</span>
        </div>
      </template>
      <div class="tool-calls-list">
        <div v-for="(tc, i) in chatStore.toolCalls" :key="i" class="tool-call-item">
          <div class="tool-call-header">
            <el-tag :type="getToolTagType(tc.tool)" size="small">{{ getToolLabel(tc.tool) }}</el-tag>
            <span class="tool-call-args">{{ formatToolArgs(tc.tool, tc.input) }}</span>
            <el-icon v-if="tc.result" class="tool-done"><CircleCheckFilled /></el-icon>
            <el-icon v-else class="tool-loading"><Loading /></el-icon>
          </div>
          <div v-if="tc.result" class="tool-call-result">{{ tc.result }}</div>
        </div>
      </div>
    </el-card>

    <!-- 状态提示 -->
    <div v-if="chatStore.statusMessage && chatStore.isLoading" class="status-bar">
      <el-icon class="status-icon"><Loading /></el-icon>
      <span>{{ chatStore.statusMessage }}</span>
    </div>

    <!-- 答案展示区 -->
    <div class="answer-section" v-if="chatStore.currentAnswer || chatStore.retrievedChunks.length">
      <!-- 检索证据卡片 -->
      <el-card class="chunks-card" shadow="hover" v-if="chatStore.retrievedChunks.length">
        <template #header>
          <div class="card-header">
            <el-icon><FolderOpened /></el-icon>
            <span>检索到的临床证据 ({{ chatStore.retrievedChunks.length }}条)</span>
            <el-tag v-if="chatStore.agentMode" type="warning" size="small">含外部实时检索</el-tag>
          </div>
        </template>
        <div class="chunks-list">
          <el-collapse accordion>
            <el-collapse-item 
              v-for="(chunk, index) in chatStore.retrievedChunks" 
              :key="index"
              :name="index"
            >
              <template #title>
                <div class="chunk-title">
                  <el-tag size="small" :type="getOriginTagType(chunk.evidence_origin)">
                    {{ chunk.evidence_origin === 'external' ? '外部' : '本地' }}
                  </el-tag>
                  <span class="chunk-doc-id">[{{ chunk.doc_id }}]</span>
                  <span class="chunk-title-text">{{ chunk.title }}</span>
                  <el-tag v-if="chunk.evidence_level" size="small" type="info">{{ chunk.evidence_level }}</el-tag>
                </div>
              </template>
              <div class="chunk-content">
                <p>{{ chunk.text_preview || chunk.abstract_preview || chunk.text || '无预览' }}</p>
                <div class="chunk-meta">
                  <span v-if="chunk.score">相关性: {{ (chunk.score * 100).toFixed(1) }}%</span>
                  <span v-if="chunk.source">来源: {{ chunk.source }}</span>
                  <span v-if="chunk.journal">期刊: {{ chunk.journal }}</span>
                </div>
              </div>
            </el-collapse-item>
          </el-collapse>
        </div>
      </el-card>

      <!-- 答案卡片 -->
      <el-card class="answer-card" shadow="hover" v-if="chatStore.currentAnswer">
        <template #header>
          <div class="card-header">
            <el-icon><Document /></el-icon>
            <span>循证答案</span>
            <el-tag v-if="chatStore.isLoading" type="warning" effect="dark">
              生成中...
            </el-tag>
            <el-tag v-else-if="chatStore.agentMode" type="success" size="small">Agent生成</el-tag>
          </div>
        </template>
        <div class="answer-content">
          <div class="answer-text" v-html="formattedAnswer"></div>
        </div>
      </el-card>
    </div>

    <!-- 错误提示 -->
    <el-alert 
      v-if="chatStore.error"
      type="error"
      :title="chatStore.error"
      show-icon
      closable
      @close="chatStore.error = null"
    />

    <!-- 历史记录 -->
    <div class="history-section" v-if="chatStore.history.length">
      <el-card shadow="hover">
        <template #header>
          <div class="card-header">
            <el-icon><Clock /></el-icon>
            <span>历史问答</span>
            <el-button size="small" type="danger" @click="chatStore.clearHistory">
              清空历史
            </el-button>
          </div>
        </template>
        <el-timeline>
          <el-timeline-item 
            v-for="(item, index) in chatStore.history.slice(-5).reverse()"
            :key="index"
            :timestamp="item.timestamp"
            placement="top"
          >
            <el-card shadow="never">
              <div class="history-item">
                <div class="history-query">
                  <strong>问题：</strong>{{ item.query }}
                  <el-tag v-if="item.agentMode" type="success" size="small">Agent</el-tag>
                  <el-tag v-if="item.toolCalls" type="info" size="small">{{ item.toolCalls }}次工具调用</el-tag>
                </div>
                <div class="history-answer">
                  <strong>答案：</strong>{{ item.answer.slice(0, 200) }}...
                </div>
                <el-button size="small" text @click="loadHistory(item)">
                  查看详情
                </el-button>
              </div>
            </el-card>
          </el-timeline-item>
        </el-timeline>
      </el-card>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { ElMessage } from 'element-plus'
import { useChatStore } from '@/stores/chat'
import { marked } from 'marked'

// 配置marked选项
marked.setOptions({
  breaks: true,
  gfm: true,
  headerIds: false,
  mangle: false
})

const chatStore = useChatStore()
const queryInput = ref('')

const exampleQueries = [
  '糖尿病合并高血压患者首选哪类降压药？',
  '他汀类药物的主要不良反应有哪些？',
  '新型降糖药SGLT2抑制剂的心血管获益证据？',
  '高血脂患者LDL-C目标值是多少？'
]

// 格式化答案
const formattedAnswer = computed(() => {
  if (!chatStore.currentAnswer) return ''
  let answer = chatStore.currentAnswer
  answer = answer.replace(/\[doc_\w+\]/g, (match) => {
    return `<span class="citation">${match}</span>`
  })
  try {
    answer = marked.parse(answer)
  } catch (e) {
    console.error('Markdown解析失败:', e)
  }
  return answer
})

function getSourceType(sourceType) {
  const types = {
    'cn_guide': 'success',
    'pubmed': 'primary',
    'cn_eupmc': '',
    'pmc_fulltext': 'warning'
  }
  return types[sourceType] || 'info'
}

function getSourceLabel(sourceType) {
  const labels = {
    'cn_guide': '中文指南',
    'pubmed': '英文文献',
    'cn_eupmc': '中文文献',
    'pmc_fulltext': '英文全文'
  }
  return labels[sourceType] || sourceType
}

function getOriginTagType(origin) {
  return origin === 'external' ? 'warning' : 'success'
}

function getToolTagType(toolName) {
  const types = {
    'local_search': 'success',
    'external_search': 'warning',
    'evidence_evaluator': 'primary',
    'query_classifier': 'info'
  }
  return types[toolName] || 'info'
}

function getToolLabel(toolName) {
  const labels = {
    'local_search': '本地检索',
    'external_search': '外部检索',
    'evidence_evaluator': '证据评估',
    'query_classifier': '问题分类'
  }
  return labels[toolName] || toolName
}

function formatToolArgs(toolName, args) {
  if (!args) return ''
  if (args.query) return `"${args.query.substring(0, 50)}${args.query.length > 50 ? '...' : ''}"`
  if (args.evidence_summary) return `证据摘要(${args.evidence_summary.length}字)`
  return JSON.stringify(args).substring(0, 60)
}

async function handleQuery() {
  if (!queryInput.value.trim()) {
    ElMessage.warning('请输入问题')
    return
  }
  await chatStore.autoQuery(queryInput.value.trim())
}

function loadHistory(item) {
  queryInput.value = item.query
  chatStore.currentAnswer = item.answer
  chatStore.retrievedChunks = item.chunks
}
</script>

<style scoped>
.chat-view {
  max-width: 1200px;
  margin: 0 auto;
}

.input-section {
  margin-bottom: 20px;
}

.input-container {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.mode-switch {
  display: flex;
  align-items: center;
  gap: 8px;
}

.mode-hint {
  color: #909399;
  font-size: 16px;
}

.input-actions {
  display: flex;
  gap: 12px;
  justify-content: flex-end;
}

.example-queries {
  margin-top: 16px;
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.example-label {
  color: #666;
  font-size: 14px;
}

.example-tag {
  cursor: pointer;
}

.example-tag:hover {
  opacity: 0.8;
}

/* Agent工具调用面板 */
.tool-calls-card {
  margin-bottom: 16px;
}

.tool-calls-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.tool-call-item {
  background: #f5f7fa;
  border-radius: 6px;
  padding: 8px 12px;
  border-left: 3px solid #409eff;
}

.tool-call-header {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
}

.tool-call-args {
  flex: 1;
  color: #606266;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tool-done {
  color: #67c23a;
  font-size: 16px;
}

.tool-loading {
  color: #e6a23c;
  font-size: 16px;
  animation: spin 1s linear infinite;
}

.tool-call-result {
  margin-top: 4px;
  font-size: 12px;
  color: #909399;
  padding-left: 52px;
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

/* 状态提示 */
.status-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 16px;
  background: #ecf5ff;
  border-radius: 6px;
  margin-bottom: 16px;
  color: #409eff;
  font-size: 14px;
}

.status-icon {
  animation: spin 1s linear infinite;
}

.answer-section {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.chunks-card, .answer-card {
  margin-bottom: 20px;
}

.card-header {
  display: flex;
  align-items: center;
  gap: 8px;
}

.chunk-title {
  display: flex;
  align-items: center;
  gap: 8px;
}

.chunk-doc-id {
  color: #1890ff;
  font-weight: bold;
}

.chunk-title-text {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.chunk-content {
  padding: 12px;
  background: #f5f7fa;
  border-radius: 4px;
}

.chunk-content p {
  margin: 0;
  line-height: 1.6;
}

.chunk-meta {
  display: flex;
  gap: 16px;
  margin-top: 8px;
  font-size: 12px;
  color: #666;
}

.answer-content {
  line-height: 1.8;
  font-size: 15px;
}

/* Markdown渲染样式 */
.answer-text {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
}

.answer-text h1, .answer-text h2, .answer-text h3 {
  margin: 16px 0 12px 0;
  font-weight: 600;
  color: #303133;
}

.answer-text h1 {
  font-size: 20px;
  border-bottom: 2px solid #409eff;
  padding-bottom: 8px;
}

.answer-text h2 {
  font-size: 18px;
  color: #409eff;
}

.answer-text h3 {
  font-size: 16px;
}

.answer-text p {
  margin: 12px 0;
  line-height: 1.8;
}

.answer-text ul, .answer-text ol {
  margin: 12px 0;
  padding-left: 24px;
}

.answer-text li {
  margin: 6px 0;
  line-height: 1.6;
}

.answer-text ul li {
  list-style-type: disc;
}

.answer-text ol li {
  list-style-type: decimal;
}

.answer-text table {
  width: 100%;
  border-collapse: collapse;
  margin: 16px 0;
}

.answer-text th, .answer-text td {
  border: 1px solid #dcdfe6;
  padding: 8px 12px;
  text-align: left;
}

.answer-text th {
  background: #f5f7fa;
  font-weight: 600;
}

.answer-text tr:hover {
  background: #ecf5ff;
}

.answer-text strong {
  color: #409eff;
  font-weight: 600;
}

.answer-text code {
  background: #f5f7fa;
  padding: 2px 6px;
  border-radius: 4px;
  font-family: 'Courier New', monospace;
  color: #e6a23c;
}

.answer-text blockquote {
  border-left: 4px solid #409eff;
  padding: 8px 16px;
  margin: 12px 0;
  background: #f5f7fa;
  color: #606266;
}

.answer-text .citation {
  background: #e6f7ff;
  padding: 2px 8px;
  border-radius: 4px;
  color: #1890ff;
  cursor: pointer;
  font-weight: 500;
  display: inline-block;
  margin: 0 2px;
}

.answer-text .citation:hover {
  background: #bae7ff;
}

.history-section {
  margin-top: 40px;
}

.history-item {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.history-query, .history-answer {
  font-size: 14px;
}
</style>