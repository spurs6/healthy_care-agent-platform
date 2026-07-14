<template>
  <div class="knowledge-view">
    <!-- 统计概览 -->
    <el-row :gutter="12" class="stats-row">
      <el-col :span="12">
        <el-card shadow="hover" class="stat-card stat-card-primary">
          <div class="stat-content">
            <el-icon class="stat-icon"><Folder /></el-icon>
            <div class="stat-info">
              <div class="stat-value">{{ stats.total_articles || 0 }}</div>
              <div class="stat-label">总文献数</div>
            </div>
          </div>
        </el-card>
      </el-col>
      <el-col :span="12" v-if="totalVectorCount > 0">
        <el-card shadow="hover" class="stat-card stat-card-primary">
          <div class="stat-content">
            <el-icon class="stat-icon" style="color: #722ed1;"><DataAnalysis /></el-icon>
            <div class="stat-info">
              <div class="stat-value">{{ totalVectorCount }}</div>
              <div class="stat-label">向量索引数</div>
            </div>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <!-- 文档分类统计 -->
    <div class="category-stats">
      <el-card shadow="hover" class="stat-card stat-card-category">
        <div class="stat-content">
          <el-icon class="stat-icon" style="color: #52c41a;"><Document /></el-icon>
          <div class="stat-info">
            <div class="stat-value">{{ stats.cn_guide || 0 }}</div>
            <div class="stat-label">中文指南</div>
          </div>
        </div>
      </el-card>
      <el-card shadow="hover" class="stat-card stat-card-category">
        <div class="stat-content">
          <el-icon class="stat-icon" style="color: #1890ff;"><Reading /></el-icon>
          <div class="stat-info">
            <div class="stat-value">{{ stats.pubmed || 0 }}</div>
            <div class="stat-label">PubMed</div>
          </div>
        </div>
      </el-card>
      <el-card shadow="hover" class="stat-card stat-card-category">
        <div class="stat-content">
          <el-icon class="stat-icon" style="color: #faad14;"><Reading /></el-icon>
          <div class="stat-info">
            <div class="stat-value">{{ stats.cn_eupmc || 0 }}</div>
            <div class="stat-label">欧洲PMC中文</div>
          </div>
        </div>
      </el-card>
      <el-card shadow="hover" class="stat-card stat-card-category">
        <div class="stat-content">
          <el-icon class="stat-icon" style="color: #f5222d;"><Reading /></el-icon>
          <div class="stat-info">
            <div class="stat-value">{{ stats.europepmc || 0 }}</div>
            <div class="stat-label">EuropePMC</div>
          </div>
        </div>
      </el-card>
      <el-card shadow="hover" class="stat-card stat-card-category">
        <div class="stat-content">
          <el-icon class="stat-icon" style="color: #722ed1;"><Reading /></el-icon>
          <div class="stat-info">
            <div class="stat-value">{{ stats.pmc_fulltext || 0 }}</div>
            <div class="stat-label">PMC全文</div>
          </div>
        </div>
      </el-card>
    </div>

    <!-- 操作区 -->
    <el-card shadow="hover" class="action-card">
      <template #header>
        <div class="card-header">
          <span>知识库操作</span>
        </div>
      </template>
      <el-row :gutter="20">
        <el-col :span="8">
          <el-upload
            ref="cnUpload"
            :action="uploadActionCn"
            :on-success="handleUploadSuccess"
            :on-error="handleUploadError"
            accept=".pdf"
            :show-file-list="false"
          >
            <el-button type="success">
              <el-icon><Upload /></el-icon>
              上传中文指南PDF
            </el-button>
          </el-upload>
        </el-col>
        <el-col :span="8">
          <el-upload
            ref="enUpload"
            :action="uploadActionEn"
            :on-success="handleUploadSuccess"
            :on-error="handleUploadError"
            accept=".pdf"
            :show-file-list="false"
          >
            <el-button type="primary">
              <el-icon><Upload /></el-icon>
              上传英文文献PDF
            </el-button>
          </el-upload>
        </el-col>
        <el-col :span="8">
          <el-button @click="startIncrementalUpdate" :loading="incrementalLoading">
            <el-icon><Refresh /></el-icon>
            执行增量更新
          </el-button>
        </el-col>
      </el-row>
      
      <!-- 增量任务状态 -->
      <div class="task-status" v-if="taskStatus">
        <el-alert 
          :type="taskStatus.status === 'completed' ? 'success' : 
                 taskStatus.status === 'running' ? 'warning' : 'info'"
          :title="`增量任务状态: ${taskStatus.status}`"
          show-icon
        >
          <template #default>
            <div>处理数量: {{ taskStatus.processed_count }}</div>
            <div>错误数量: {{ taskStatus.error_count }}</div>
            <div>开始时间: {{ taskStatus.start_time }}</div>
          </template>
        </el-alert>
      </div>
    </el-card>

    <!-- 文档列表 -->
    <el-card shadow="hover" class="documents-card">
      <template #header>
        <div class="card-header">
          <span>文档列表</span>
          <div class="header-actions">
            <el-input 
              v-model="searchParams.disease" 
              placeholder="疾病关键词"
              clearable
              style="width: 150px;"
            />
            <el-select v-model="searchParams.source_type" clearable placeholder="来源类型" style="width: 130px;">
              <el-option label="中文指南" value="cn_guide" />
              <el-option label="PubMed" value="pubmed" />
              <el-option label="欧洲PMC中文" value="cn_eupmc" />
              <el-option label="EuropePMC" value="europepmc" />
              <el-option label="PMC全文" value="pmc_fulltext" />
            </el-select>
            <el-button @click="searchDocuments">
              <el-icon><Search /></el-icon>
              搜索
            </el-button>
            <el-button @click="resetSearch">
              <el-icon><RefreshLeft /></el-icon>
              重置
            </el-button>
          </div>
        </div>
      </template>
      
      <el-table :data="documents" v-loading="tableLoading" stripe>
        <el-table-column prop="doc_id" label="文档ID" width="150" />
        <el-table-column prop="title" label="标题" min-width="200" show-overflow-tooltip />
        <el-table-column prop="source_type" label="来源" width="100">
          <template #default="{ row }">
            <el-tag :type="getSourceType(row.source_type)">
              {{ getSourceLabel(row.source_type) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="publish_year" label="年份" width="80" />
        <el-table-column prop="evidence_level" label="证据等级" width="100" />
        <el-table-column prop="language" label="语言" width="60">
          <template #default="{ row }">
            {{ row.language === 'zh' ? '中文' : '英文' }}
          </template>
        </el-table-column>
        <el-table-column label="操作" width="200" fixed="right">
          <template #default="{ row }">
            <el-button v-if="row.file_path" size="small" type="primary" @click="processDocument(row.doc_id)">
              处理
            </el-button>
            <el-tag v-else size="small" type="success">已索引</el-tag>
            <el-button size="small" @click="viewDocument(row.doc_id)">
              查看
            </el-button>
            <el-button size="small" type="danger" @click="deleteDocument(row.doc_id)">
              删除
            </el-button>
          </template>
        </el-table-column>
      </el-table>
      
      <div class="pagination">
        <el-pagination
          v-model:current-page="currentPage"
          v-model:page-size="searchParams.limit"
          :total="totalDocuments"
          :page-sizes="[20, 50, 100, 200]"
          layout="total, sizes, prev, pager, next, jumper"
          @current-change="onPageChange"
          @size-change="onSizeChange"
        />
      </div>
    </el-card>

    <!-- 文档详情弹窗 -->
    <el-dialog v-model="detailVisible" title="文档详情" width="600px">
      <el-descriptions :column="2" border v-if="currentDocument">
        <el-descriptions-item label="文档ID">{{ currentDocument.doc_id }}</el-descriptions-item>
        <el-descriptions-item label="标题">{{ currentDocument.title }}</el-descriptions-item>
        <el-descriptions-item label="来源">{{ getSourceLabel(currentDocument.source_type) }}</el-descriptions-item>
        <el-descriptions-item label="年份">{{ currentDocument.publish_year }}</el-descriptions-item>
        <el-descriptions-item label="证据等级">{{ currentDocument.evidence_level }}</el-descriptions-item>
        <el-descriptions-item label="语言">{{ currentDocument.language === 'zh' ? '中文' : '英文' }}</el-descriptions-item>
        <el-descriptions-item label="疾病标签">
          <el-tag v-for="tag in currentDocument.disease_tags" :key="tag" size="small">
            {{ tag }}
          </el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="PMID">{{ currentDocument.pmid || '-' }}</el-descriptions-item>
        <el-descriptions-item label="摘要" :span="2">
          {{ currentDocument.abstract || '-' }}
        </el-descriptions-item>
      </el-descriptions>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted, computed } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { adminApi } from '@/utils/api'

const stats = ref({})
const vectorStats = ref({})
const documents = ref([])
const totalDocuments = ref(0)
const tableLoading = ref(false)
const incrementalLoading = ref(false)
const taskStatus = ref(null)
const detailVisible = ref(false)
const currentDocument = ref(null)
const currentPage = ref(1)

const searchParams = ref({
  source_type: null,
  disease: null,
  year_from: null,
  year_to: null,
  limit: 50,
  offset: 0
})

// 计算向量库总数
const totalVectorCount = computed(() => {
  if (!vectorStats.value) return 0
  return Object.values(vectorStats.value).reduce((sum, count) => sum + count, 0)
})

const uploadActionCn = '/api/admin/upload/cn_guide'
const uploadActionEn = '/api/admin/upload/en_pubmed'

onMounted(async () => {
  await loadStats()
  await loadDocuments()
})

async function loadStats() {
  try {
    const res = await adminApi.getStats()
    stats.value = res.database
    
    const vecRes = await adminApi.getCollectionStats()
    vectorStats.value = vecRes
  } catch (error) {
    console.error('加载统计失败:', error)
  }
}

async function loadDocuments() {
  tableLoading.value = true
  try {
    const params = {
      ...searchParams.value,
      offset: (currentPage.value - 1) * searchParams.value.limit
    }
    const res = await adminApi.getDocuments(params)
    documents.value = res.documents
    totalDocuments.value = res.total
  } catch (error) {
    console.error('加载文档失败:', error)
  } finally {
    tableLoading.value = false
  }
}

function onPageChange(newPage) {
  currentPage.value = newPage
  loadDocuments()
}

function onSizeChange(newSize) {
  searchParams.value.limit = newSize
  currentPage.value = 1
  loadDocuments()
}

function searchDocuments() {
  currentPage.value = 1
  loadDocuments()
}

function resetSearch() {
  searchParams.value = {
    source_type: null,
    disease: null,
    year_from: null,
    year_to: null,
    limit: 50,
    offset: 0
  }
  currentPage.value = 1
  loadDocuments()
}

function handleUploadSuccess(response) {
  ElMessage.success(`文件上传成功: ${response.doc_id}`)
  loadDocuments()
  loadStats()
}

function handleUploadError(error) {
  ElMessage.error('文件上传失败')
}

async function startIncrementalUpdate() {
  incrementalLoading.value = true
  try {
    const res = await adminApi.startIncrementalUpdate('pubmed', 30)
    ElMessage.success(`增量更新任务已启动: ${res.task_id}`)
    
    // 获取任务状态
    const statusRes = await adminApi.getIncrementalStatus('manual_import')
    taskStatus.value = statusRes
  } catch (error) {
    ElMessage.error('启动增量更新失败')
  } finally {
    incrementalLoading.value = false
  }
}

async function processDocument(docId) {
  try {
    const res = await adminApi.processDocument(docId)
    ElMessage.success(`处理完成，生成 ${res.chunks_count} 个chunks`)
    loadStats()
  } catch (error) {
    ElMessage.error('处理文档失败')
  }
}

async function viewDocument(docId) {
  try {
    const res = await adminApi.getDocument(docId)
    currentDocument.value = res
    detailVisible.value = true
  } catch (error) {
    ElMessage.error('获取文档详情失败')
  }
}

async function deleteDocument(docId) {
  try {
    await ElMessageBox.confirm('确认删除该文档？')
    await adminApi.deleteDocument(docId)
    ElMessage.success('文档已删除')
    loadDocuments()
    loadStats()
  } catch (error) {
    if (error !== 'cancel') {
      ElMessage.error('删除文档失败')
    }
  }
}

function getSourceType(sourceType) {
  const types = {
    'cn_guide': 'success',
    'pubmed': 'primary',
    'cn_eupmc': 'warning',
    'europepmc': 'info',
    'pmc_fulltext': 'danger'
  }
  return types[sourceType] || 'info'
}

function getSourceLabel(sourceType) {
  const labels = {
    'cn_guide': '中文指南',
    'pubmed': 'PubMed',
    'cn_eupmc': '欧洲PMC中文',
    'europepmc': 'EuropePMC',
    'pmc_fulltext': 'PMC全文'
  }
  return labels[sourceType] || sourceType
}
</script>

<style scoped>
.knowledge-view {
  max-width: 1400px;
  margin: 0 auto;
}

.stats-row {
  margin-bottom: 12px;
}

.stat-card {
  height: 100px;
}

.stat-card-primary {
  height: 110px;
}

.stat-card-primary .stat-icon {
  font-size: 42px;
}

.stat-card-primary .stat-value {
  font-size: 28px;
}

.category-stats {
  display: flex;
  gap: 12px;
  margin-bottom: 20px;
}

.category-stats .stat-card-category {
  flex: 1;
  min-width: 0;
}

.stat-content {
  display: flex;
  align-items: center;
  gap: 16px;
}

.stat-icon {
  font-size: 36px;
  color: #1890ff;
}

.stat-info {
  display: flex;
  flex-direction: column;
}

.stat-value {
  font-size: 24px;
  font-weight: bold;
  color: #1890ff;
}

.stat-label {
  font-size: 14px;
  color: #666;
}

.action-card {
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

.task-status {
  margin-top: 16px;
}

.documents-card {
  margin-bottom: 20px;
}

.pagination {
  margin-top: 16px;
  display: flex;
  justify-content: center;
}
</style>