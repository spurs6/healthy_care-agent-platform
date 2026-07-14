<template>
  <div class="evaluation-view">
    <!-- 测试集管理 -->
    <el-card shadow="hover" class="testset-card">
      <template #header>
        <div class="card-header">
          <span>测试集管理</span>
          <div class="header-actions">
            <el-upload
              :action="uploadAction"
              :on-success="handleUploadSuccess"
              accept=".json"
              :show-file-list="false"
            >
              <el-button size="small">
                <el-icon><Upload /></el-icon>
                上传测试集
              </el-button>
            </el-upload>
            <el-button size="small" type="success" @click="showGenerateDialog = true" :loading="generateLoading">
              <el-icon><MagicStick /></el-icon>
              生成测试集样例
            </el-button>
          </div>
        </div>
      </template>
      
      <el-table :data="testSets" v-loading="testSetLoading" stripe size="small">
        <el-table-column prop="filename" label="文件名" min-width="250" />
        <el-table-column prop="count" label="题目数" width="80" align="center" />
        <el-table-column label="更新时间" width="180">
          <template #default="{ row }">
            {{ formatTime(row.modified) }}
          </template>
        </el-table-column>
        <el-table-column label="操作" width="240">
          <template #default="{ row }">
            <div class="row-actions">
              <el-button size="small" @click="viewTestSet(row.filename)">查看</el-button>
              <el-button size="small" type="primary" @click="runEval(row.filename)">运行评测</el-button>
              <el-button size="small" type="danger" plain @click="deleteTestSet(row.filename)">删除</el-button>
            </div>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 评测配置 -->
    <el-card shadow="hover" class="eval-control-card">
      <template #header><span>评测配置</span></template>
      <el-form :inline="true">
        <el-form-item label="测试集">
          <el-select v-model="selectedTestSet" placeholder="选择测试集" style="width: 280px">
            <el-option v-for="ts in testSets" :key="ts.filename" :label="ts.filename" :value="ts.filename" />
          </el-select>
        </el-form-item>
        <el-form-item label="测试条目数">
          <el-input-number v-model="testLimit" :min="1" :max="100" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="runEvaluation" :loading="evalLoading">
            <el-icon><VideoPlay /></el-icon>
            开始评测
          </el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <!-- 评测历史记录 -->
    <el-card shadow="hover" class="history-card">
      <template #header>
        <div class="card-header">
          <span>评测历史记录</span>
          <el-button size="small" @click="loadHistory" :loading="historyLoading">
            <el-icon><Refresh /></el-icon>
            刷新
          </el-button>
        </div>
      </template>
      
      <el-table :data="evalHistory" v-loading="historyLoading" stripe size="small" @row-click="viewHistoryDetail">
        <el-table-column label="时间" width="170">
          <template #default="{ row }">
            {{ formatTime(row.timestamp) }}
          </template>
        </el-table-column>
        <el-table-column prop="test_set" label="测试集" min-width="200" show-overflow-tooltip />
        <el-table-column prop="total_count" label="题数" width="60" align="center" />
        <el-table-column label="忠实度" width="90" align="center">
          <template #default="{ row }">
            <el-tag :type="row.avg_faithfulness >= 0.8 ? 'success' : 'warning'" size="small">
              {{ (row.avg_faithfulness * 100).toFixed(1) }}%
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="引用准确率" width="100" align="center">
          <template #default="{ row }">
            {{ (row.avg_citation_accuracy * 100).toFixed(1) }}%
          </template>
        </el-table-column>
        <el-table-column label="检索精准率" width="100" align="center">
          <template #default="{ row }">
            {{ (row.avg_context_precision * 100).toFixed(1) }}%
          </template>
        </el-table-column>
        <el-table-column label="答案相关性" width="100" align="center">
          <template #default="{ row }">
            {{ (row.avg_answer_relevance * 100).toFixed(1) }}%
          </template>
        </el-table-column>
        <el-table-column label="达标率" width="90" align="center">
          <template #default="{ row }">
            <el-tag :type="row.pass_rate >= 0.8 ? 'success' : 'danger'" size="small">
              {{ (row.pass_rate * 100).toFixed(0) }}%
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="120" align="center">
          <template #default="{ row }">
            <el-button size="small" text @click.stop="viewHistoryDetail(row)">详情</el-button>
            <el-button size="small" text type="danger" @click.stop="deleteHistory(row.eval_id)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 当前评测结果 -->
    <el-card shadow="hover" class="result-card" v-if="evalReport">
      <template #header>
        <div class="card-header">
          <span>评测报告 - {{ currentEvalTime }}</span>
          <el-button size="small" type="success" @click="exportReport">
            <el-icon><Download /></el-icon>
            导出报告
          </el-button>
        </div>
      </template>
      
      <!-- 指标概览 -->
      <el-row :gutter="20" class="metrics-row">
        <el-col :span="4">
          <el-statistic title="测试总数" :value="evalReport.total_count" />
        </el-col>
        <el-col :span="4">
          <el-statistic title="证据忠实度" :value="evalReport.avg_faithfulness * 100" suffix="%" :precision="1" />
        </el-col>
        <el-col :span="4">
          <el-statistic title="引用准确率" :value="evalReport.avg_citation_accuracy * 100" suffix="%" :precision="1" />
        </el-col>
        <el-col :span="4">
          <el-statistic title="检索精准率" :value="evalReport.avg_context_precision * 100" suffix="%" :precision="1" />
        </el-col>
        <el-col :span="4">
          <el-statistic title="答案相关性" :value="evalReport.avg_answer_relevance * 100" suffix="%" :precision="1" />
        </el-col>
        <el-col :span="4">
          <el-statistic title="达标率" :value="evalReport.pass_rate * 100" suffix="%" :precision="1" />
        </el-col>
      </el-row>

      <!-- 指标图表 -->
      <div class="chart-container" ref="chartContainer"></div>

      <!-- 详细结果列表 -->
      <el-collapse class="detail-collapse">
        <el-collapse-item title="详细评测结果" name="details">
          <el-table :data="evalReport.details" max-height="400" size="small">
            <el-table-column type="expand">
              <template #default="{ row }">
                <div class="expand-detail">
                  <p><strong>问题：</strong>{{ row.query }}</p>
                  <p><strong>标准答案：</strong>{{ row.ground_truth }}</p>
                  <p><strong>系统回答：</strong>{{ row.answer }}</p>
                  <p><strong>检索文档：</strong>{{ row.retrieved_chunks?.join(', ') || '无' }}</p>
                </div>
              </template>
            </el-table-column>
            <el-table-column prop="query" label="问题" min-width="200" show-overflow-tooltip />
            <el-table-column label="忠实度" width="80" align="center">
              <template #default="{ row }">
                <el-tag :type="row.faithfulness >= 0.8 ? 'success' : 'danger'" size="small">
                  {{ (row.faithfulness * 100).toFixed(0) }}%
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="引用准确率" width="100" align="center">
              <template #default="{ row }">
                {{ (row.citation_accuracy * 100).toFixed(0) }}%
              </template>
            </el-table-column>
            <el-table-column label="检索精准率" width="100" align="center">
              <template #default="{ row }">
                {{ (row.context_precision * 100).toFixed(0) }}%
              </template>
            </el-table-column>
            <el-table-column label="答案相关性" width="100" align="center">
              <template #default="{ row }">
                {{ (row.answer_relevance * 100).toFixed(0) }}%
              </template>
            </el-table-column>
          </el-table>
        </el-collapse-item>
      </el-collapse>
    </el-card>

    <!-- 测试集详情弹窗 -->
    <el-dialog v-model="testSetVisible" title="测试集详情" width="800px">
      <el-table :data="testSetItems" max-height="500" size="small">
        <el-table-column type="index" width="50" />
        <el-table-column prop="query" label="测试问题" min-width="250" show-overflow-tooltip />
        <el-table-column prop="ground_truth" label="标准答案" min-width="300" show-overflow-tooltip />
        <el-table-column prop="source" label="来源" width="150" show-overflow-tooltip />
      </el-table>
    </el-dialog>

    <!-- 生成测试集弹窗 -->
    <el-dialog v-model="showGenerateDialog" title="基于知识库生成测试集" width="450px">
      <el-alert type="info" :closable="false" style="margin-bottom: 16px;">
        系统将从知识库中随机抽取文献，使用LLM基于文献内容自动生成问答题对。生成的测试集保存到 test_set 目录。
      </el-alert>
      <el-form>
        <el-form-item label="生成题数">
          <el-input-number v-model="generateNum" :min="3" :max="30" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showGenerateDialog = false">取消</el-button>
        <el-button type="primary" @click="generateTestSet" :loading="generateLoading">开始生成</el-button>
      </template>
    </el-dialog>

    <!-- 评测历史详情弹窗 -->
    <el-dialog v-model="historyDetailVisible" title="评测详情" width="900px" class="history-detail-dialog">
      <div v-if="historyDetail" v-loading="historyDetailLoading">
        <!-- 概览指标 -->
        <el-descriptions :column="3" border size="small" style="margin-bottom: 16px;">
          <el-descriptions-item label="测试集">{{ historyDetail.test_set }}</el-descriptions-item>
          <el-descriptions-item label="评测时间">{{ formatTime(historyDetail.timestamp) }}</el-descriptions-item>
          <el-descriptions-item label="题目数">{{ historyDetail.total_count }}</el-descriptions-item>
          <el-descriptions-item label="证据忠实度">{{ (historyDetail.avg_faithfulness * 100).toFixed(1) }}%</el-descriptions-item>
          <el-descriptions-item label="引用准确率">{{ (historyDetail.avg_citation_accuracy * 100).toFixed(1) }}%</el-descriptions-item>
          <el-descriptions-item label="检索精准率">{{ (historyDetail.avg_context_precision * 100).toFixed(1) }}%</el-descriptions-item>
          <el-descriptions-item label="答案相关性">{{ (historyDetail.avg_answer_relevance * 100).toFixed(1) }}%</el-descriptions-item>
          <el-descriptions-item label="达标率">
            <el-tag :type="historyDetail.pass_rate >= 0.8 ? 'success' : 'danger'" size="small">
              {{ (historyDetail.pass_rate * 100).toFixed(0) }}%
            </el-tag>
          </el-descriptions-item>
        </el-descriptions>

        <!-- 详细结果 -->
        <el-table :data="historyDetail.details?.details || []" max-height="400" size="small">
          <el-table-column type="expand">
            <template #default="{ row }">
              <div class="expand-detail">
                <p><strong>问题：</strong>{{ row.query }}</p>
                <p><strong>标准答案：</strong>{{ row.ground_truth }}</p>
                <p><strong>系统回答：</strong>{{ row.answer }}</p>
              </div>
            </template>
          </el-table-column>
          <el-table-column prop="query" label="问题" min-width="200" show-overflow-tooltip />
          <el-table-column label="忠实度" width="80" align="center">
            <template #default="{ row }">
              <el-tag :type="row.faithfulness >= 0.8 ? 'success' : 'danger'" size="small">
                {{ (row.faithfulness * 100).toFixed(0) }}%
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="引用准确率" width="100" align="center">
            <template #default="{ row }">{{ (row.citation_accuracy * 100).toFixed(0) }}%</template>
          </el-table-column>
          <el-table-column label="检索精准率" width="100" align="center">
            <template #default="{ row }">{{ (row.context_precision * 100).toFixed(0) }}%</template>
          </el-table-column>
          <el-table-column label="答案相关性" width="100" align="center">
            <template #default="{ row }">{{ (row.answer_relevance * 100).toFixed(0) }}%</template>
          </el-table-column>
        </el-table>
      </div>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted, nextTick, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { evalApi } from '@/utils/api'
import * as echarts from 'echarts'

const testSets = ref([])
const testSetLoading = ref(false)
const testSetVisible = ref(false)
const testSetItems = ref([])
const selectedTestSet = ref('')
const testLimit = ref(10)
const evalLoading = ref(false)
const evalReport = ref(null)
const currentEvalTime = ref('')
const chartContainer = ref(null)
let chartInstance = null

const uploadAction = '/api/eval/test_sets/upload'

// 生成测试集
const showGenerateDialog = ref(false)
const generateNum = ref(10)
const generateLoading = ref(false)

// 评测历史
const evalHistory = ref([])
const historyLoading = ref(false)
const historyDetailVisible = ref(false)
const historyDetail = ref(null)
const historyDetailLoading = ref(false)

onMounted(async () => {
  await loadTestSets()
  await loadHistory()
})

watch(evalReport, async (newVal) => {
  if (newVal) {
    await nextTick()
    renderChart()
  }
})

async function loadTestSets() {
  testSetLoading.value = true
  try {
    const res = await evalApi.getTestSets()
    testSets.value = res.test_sets
    if (testSets.value.length > 0 && !selectedTestSet.value) {
      selectedTestSet.value = testSets.value[0].filename
    }
  } catch (error) {
    console.error('加载测试集失败:', error)
  } finally {
    testSetLoading.value = false
  }
}

async function loadHistory() {
  historyLoading.value = true
  try {
    const res = await evalApi.getHistory(30)
    evalHistory.value = res.history
  } catch (error) {
    console.error('加载评测历史失败:', error)
  } finally {
    historyLoading.value = false
  }
}

function handleUploadSuccess(response) {
  ElMessage.success(`测试集上传成功: ${response.filename}`)
  loadTestSets()
}

async function generateTestSet() {
  generateLoading.value = true
  try {
    const res = await evalApi.generateTestSet(generateNum.value)
    ElMessage.success(`测试集生成成功: ${res.filename} (${res.count}题)`)
    showGenerateDialog.value = false
    await loadTestSets()
    selectedTestSet.value = res.filename
  } catch (error) {
    ElMessage.error('生成测试集失败: ' + (error.response?.data?.detail || error.message))
  } finally {
    generateLoading.value = false
  }
}

async function viewTestSet(filename) {
  try {
    const res = await evalApi.getTestSet(filename)
    testSetItems.value = res.items
    testSetVisible.value = true
  } catch (error) {
    ElMessage.error('获取测试集详情失败')
  }
}

async function deleteTestSet(filename) {
  try {
    await ElMessageBox.confirm('确定删除该测试集？', '提示', { type: 'warning' })
    await evalApi.deleteTestSet(filename)
    ElMessage.success('测试集已删除')
    loadTestSets()
  } catch (error) {
    if (error !== 'cancel') ElMessage.error('删除失败')
  }
}

async function runEval(filename) {
  selectedTestSet.value = filename
  await runEvaluation()
}

async function runEvaluation() {
  if (!selectedTestSet.value) {
    ElMessage.warning('请选择测试集')
    return
  }
  
  evalLoading.value = true
  try {
    const res = await evalApi.runEvaluation(selectedTestSet.value, testLimit.value)
    evalReport.value = res
    currentEvalTime.value = formatTime(res.timestamp)
    ElMessage.success('评测完成，结果已保存')
    await loadHistory()
  } catch (error) {
    ElMessage.error('评测执行失败: ' + (error.response?.data?.detail || error.message))
  } finally {
    evalLoading.value = false
  }
}

async function viewHistoryDetail(row) {
  historyDetailVisible.value = true
  historyDetailLoading.value = true
  historyDetail.value = null
  try {
    const res = await evalApi.getEvalDetail(row.eval_id)
    historyDetail.value = res
  } catch (error) {
    ElMessage.error('获取评测详情失败')
  } finally {
    historyDetailLoading.value = false
  }
}

async function deleteHistory(evalId) {
  try {
    await ElMessageBox.confirm('确定删除该评测记录？', '提示', { type: 'warning' })
    await evalApi.deleteEvalHistory(evalId)
    ElMessage.success('记录已删除')
    loadHistory()
  } catch (error) {
    if (error !== 'cancel') ElMessage.error('删除失败')
  }
}

function formatTime(isoStr) {
  if (!isoStr) return ''
  const d = new Date(isoStr)
  return d.toLocaleString('zh-CN', { 
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit'
  })
}

function renderChart() {
  if (!chartContainer.value || !evalReport.value) return
  
  if (chartInstance) {
    chartInstance.dispose()
  }
  
  chartInstance = echarts.init(chartContainer.value)
  
  const metrics = ['faithfulness', 'citation_accuracy', 'context_precision', 'answer_relevance']
  const values = metrics.map(m => (evalReport.value[`avg_${m}`] || 0) * 100)
  const thresholds = [80, 85, 75, 80]
  
  chartInstance.setOption({
    title: { text: '评测指标对比', left: 'center' },
    tooltip: { trigger: 'axis' },
    legend: { data: ['实际值', '达标阈值'], top: 30 },
    xAxis: { type: 'category', data: ['证据忠实度', '引用准确率', '检索精准率', '答案相关性'] },
    yAxis: { type: 'value', max: 100, axisLabel: { formatter: '{value}%' } },
    series: [
      {
        name: '实际值', type: 'bar', data: values,
        itemStyle: { color: values.map((v, i) => v >= thresholds[i] ? '#52c41a' : '#f5222d') },
        label: { show: true, position: 'top', formatter: '{c}%' }
      },
      {
        name: '达标阈值', type: 'line', data: thresholds,
        lineStyle: { color: '#faad14', type: 'dashed' }, symbol: 'none'
      }
    ]
  })
}

async function exportReport() {
  try {
    await evalApi.exportReport(evalReport.value)
    ElMessage.success('报告导出成功')
  } catch (error) {
    ElMessage.error('导出报告失败')
  }
}
</script>

<style scoped>
.evaluation-view {
  max-width: 1400px;
  margin: 0 auto;
}

.testset-card, .eval-control-card, .result-card, .history-card {
  margin-bottom: 20px;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.header-actions {
  display: flex;
  gap: 12px;
}

.row-actions {
  display: flex;
  gap: 8px;
  align-items: center;
}

.metrics-row {
  margin-bottom: 20px;
  text-align: center;
}

.chart-container {
  height: 300px;
  margin: 20px 0;
}

.detail-collapse {
  margin-top: 20px;
}

.expand-detail {
  padding: 12px 20px;
  background: #f9f9f9;
  border-radius: 4px;
}

.expand-detail p {
  margin: 6px 0;
  line-height: 1.6;
}

.history-detail-dialog :deep(.el-dialog__body) {
  max-height: 65vh;
  overflow-y: auto;
}
</style>
