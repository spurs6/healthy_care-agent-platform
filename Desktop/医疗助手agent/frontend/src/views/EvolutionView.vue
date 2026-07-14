<template>
  <div class="evolution-view">
    <!-- 顶部总览 -->
    <el-row :gutter="16" class="overview-row">
      <el-col :span="6">
        <el-card shadow="hover" class="overview-card">
          <div class="overview-content">
            <el-icon class="overview-icon" style="color: #409eff;"><DataLine /></el-icon>
            <div class="overview-info">
              <div class="overview-value">{{ report.memory_bank?.total_experiences || 0 }}</div>
              <div class="overview-label">经验记录</div>
            </div>
          </div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="hover" class="overview-card">
          <div class="overview-content">
            <el-icon class="overview-icon" style="color: #67c23a;"><TrendCharts /></el-icon>
            <div class="overview-info">
              <div class="overview-value">{{ report.reasoning_principles?.total_principles || 0 }}</div>
              <div class="overview-label">推理原则</div>
            </div>
          </div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="hover" class="overview-card">
          <div class="overview-content">
            <el-icon class="overview-icon" style="color: #e6a23c;"><Warning /></el-icon>
            <div class="overview-info">
              <div class="overview-value">{{ report.knowledge_gaps?.total_gaps || 0 }}</div>
              <div class="overview-label">知识缺口</div>
            </div>
          </div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="hover" class="overview-card">
          <div class="overview-content">
            <el-icon class="overview-icon" style="color: #f56c6c;"><Lock /></el-icon>
            <div class="overview-info">
              <div class="overview-value">{{ report.safety?.total_actions || 0 }}</div>
              <div class="overview-label">安全审计</div>
            </div>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <!-- 能力状态 -->
    <el-card shadow="hover" class="section-card">
      <template #header>
        <div class="card-header">
          <el-icon><Cpu /></el-icon>
          <span>自进化能力状态</span>
          <el-button size="small" type="primary" @click="loadReport" :loading="loading">刷新</el-button>
        </div>
      </template>
      <div class="capabilities-grid">
        <div v-for="(enabled, name) in report.capabilities" :key="name" class="capability-item">
          <el-tag :type="enabled ? 'success' : 'info'" effect="dark" size="large">
            <el-icon><Check v-if="enabled" /><Close v-else /></el-icon>
            {{ capabilityLabels[name] || name }}
          </el-tag>
        </div>
      </div>
    </el-card>

    <!-- Tab区域 -->
    <el-tabs v-model="activeTab" class="main-tabs" @tab-change="onTabChange">
      
      <!-- Tab1: 经验记忆库 -->
      <el-tab-pane label="经验记忆库" name="experiences">
        <el-card shadow="hover">
          <template #header>
            <div class="card-header">
              <span>问答经验记录 ({{ report.memory_bank?.total_experiences || 0 }}条)</span>
              <div>
                <el-tag type="info" size="small">平均评分: {{ (report.memory_bank?.avg_eval_score || 0).toFixed(4) }}</el-tag>
                <el-tag type="success" size="small" style="margin-left: 8px;">已优化策略: {{ report.memory_bank?.optimized_strategy_count || 0 }}种</el-tag>
              </div>
            </div>
          </template>

          <!-- 经验类型分布 -->
          <div v-if="report.memory_bank?.type_distribution" class="type-distribution">
            <span class="dist-label">查询类型分布：</span>
            <el-tag v-for="(count, type) in report.memory_bank.type_distribution" :key="type"
              :type="getTypeColor(type)" size="small" style="margin: 4px;">
              {{ typeLabels[type] || type }}: {{ count }}
            </el-tag>
          </div>

          <!-- 经验列表 -->
          <el-table :data="experiences" v-loading="expLoading" stripe style="margin-top: 16px;" max-height="400">
            <el-table-column prop="query" label="查询问题" min-width="200" show-overflow-tooltip />
            <el-table-column prop="query_type" label="类型" width="120">
              <template #default="{ row }">
                <el-tag size="small" :type="getTypeColor(row.query_type)">{{ typeLabels[row.query_type] || row.query_type }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="疾病标签" width="150">
              <template #default="{ row }">
                <el-tag v-for="tag in (row.disease_tags || [])" :key="tag" size="small" style="margin: 2px;">{{ tag }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="自动评分" width="100">
              <template #default="{ row }">
                <el-progress :percentage="Math.round((row.auto_eval_score || 0) * 100)" :color="getScoreColor(row.auto_eval_score)" :stroke-width="8" />
              </template>
            </el-table-column>
            <el-table-column label="工具调用" width="100">
              <template #default="{ row }">
                {{ (row.tool_calls || []).length }}次
              </template>
            </el-table-column>
            <el-table-column prop="timestamp" label="时间" width="160">
              <template #default="{ row }">
                {{ formatTime(row.timestamp) }}
              </template>
            </el-table-column>
            <el-table-column label="详情" width="80">
              <template #default="{ row }">
                <el-button size="small" text @click="showExpDetail(row)">查看</el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-tab-pane>

      <!-- Tab2: 策略自博弈 -->
      <el-tab-pane label="策略自博弈" name="selfplay">
        <el-card shadow="hover">
          <template #header>
            <div class="card-header">
              <span>自博弈评估引擎</span>
              <el-button size="small" type="warning" @click="runSelfPlay" :loading="selfPlayLoading">
                <el-icon><VideoPlay /></el-icon>
                触发自博弈评估
              </el-button>
            </div>
          </template>

          <el-alert type="info" :closable="false" style="margin-bottom: 16px;">
            <template #title>
              自博弈评估：系统自动从知识库生成测试题，用不同检索策略（默认/优化/激进）分别回答，比较效果后自动更新最优策略参数。
            </template>
          </el-alert>

          <!-- 已优化策略列表 -->
          <div v-if="optimizedStrategies.length > 0">
            <h4>已优化的检索策略</h4>
            <el-table :data="optimizedStrategies" stripe>
              <el-table-column prop="query_type" label="查询类型" width="150">
                <template #default="{ row }">{{ typeLabels[row.query_type] || row.query_type }}</template>
              </el-table-column>
              <el-table-column prop="avg_score" label="平均评分" width="120">
                <template #default="{ row }">
                  <el-progress :percentage="Math.round(row.avg_score * 100)" :stroke-width="8" />
                </template>
              </el-table-column>
              <el-table-column prop="sample_count" label="样本数" width="100" />
              <el-table-column prop="updated_at" label="更新时间" width="180">
                <template #default="{ row }">{{ formatTime(row.updated_at) }}</template>
              </el-table-column>
            </el-table>
          </div>
          <el-empty v-else description="暂无优化策略，点击上方按钮触发自博弈评估" />

          <!-- 自博弈结果 -->
          <div v-if="selfPlayResult" class="selfplay-result">
            <el-divider />
            <h4>最近一次评估结果</h4>
            <el-descriptions :column="2" border>
              <el-descriptions-item label="状态">{{ selfPlayResult.status }}</el-descriptions-item>
              <el-descriptions-item label="测试用例数">{{ selfPlayResult.total_test_cases }}</el-descriptions-item>
              <el-descriptions-item label="类型分布">{{ JSON.stringify(selfPlayResult.type_distribution) }}</el-descriptions-item>
              <el-descriptions-item label="更新策略数">{{ selfPlayResult.updated_strategies?.length || 0 }}</el-descriptions-item>
            </el-descriptions>
          </div>
        </el-card>
      </el-tab-pane>

      <!-- Tab3: 推理原则 -->
      <el-tab-pane label="推理原则" name="principles">
        <el-card shadow="hover">
          <template #header>
            <div class="card-header">
              <span>推理原则库 ({{ principleData.stats?.total_principles || 0 }}条)</span>
              <el-button size="small" type="success" @click="runDistillation" :loading="distillLoading">
                <el-icon><MagicStick /></el-icon>
                蒸馏推理原则
              </el-button>
            </div>
          </template>

          <el-alert type="info" :closable="false" style="margin-bottom: 16px;">
            <template #title>
              推理原则蒸馏：系统从高分问答经验中，用LLM分析共同模式，提取"当...时，应该..."格式的可复用推理策略，指导后续问答。
            </template>
          </el-alert>

          <!-- 原则统计 -->
          <div v-if="principleData.stats" class="principle-stats">
            <el-row :gutter="16">
              <el-col :span="6">
                <el-statistic title="原则总数" :value="principleData.stats.total_principles" />
              </el-col>
              <el-col :span="6">
                <el-statistic title="总使用次数" :value="principleData.stats.total_usage" />
              </el-col>
              <el-col :span="6">
                <el-statistic title="总成功次数" :value="principleData.stats.total_success" />
              </el-col>
              <el-col :span="6">
                <el-statistic title="整体成功率" :value="Math.round((principleData.stats.overall_success_rate || 0) * 100)" suffix="%" />
              </el-col>
            </el-row>
          </div>

          <!-- 原则列表 -->
          <div v-if="principleData.principles && principleData.principles.length > 0" style="margin-top: 16px;">
            <el-card v-for="p in principleData.principles" :key="p.principle_id" shadow="never" class="principle-card">
              <div class="principle-header">
                <el-tag :type="getTypeColor(p.query_type)" size="small">{{ typeLabels[p.query_type] || p.query_type }}</el-tag>
                <span class="principle-text">{{ p.principle }}</span>
              </div>
              <div class="principle-meta">
                <el-progress :percentage="Math.round(p.confidence * 100)" :stroke-width="12" :format="p => `置信度 ${p}%`"
                  :color="p.confidence > 0.7 ? '#67c23a' : p.confidence > 0.5 ? '#e6a23c' : '#909399'"
                  style="width: 200px;" />
                <span class="principle-usage">使用{{ p.usage_count }}次 / 成功{{ p.success_count }}次</span>
                <span class="principle-time">更新于 {{ formatTime(p.updated_at) }}</span>
              </div>
            </el-card>
          </div>
          <el-empty v-else description="暂无推理原则。系统需要积累足够的高分经验（评分>=0.7）后，点击上方按钮蒸馏原则。" />
        </el-card>
      </el-tab-pane>

      <!-- Tab4: 知识缺口 -->
      <el-tab-pane label="知识缺口" name="gaps">
        <el-card shadow="hover">
          <template #header>
            <div class="card-header">
              <span>知识缺口监控</span>
            </div>
          </template>

          <el-alert type="warning" :closable="false" style="margin-bottom: 16px;">
            <template #title>
              当本地知识库检索相似度低于0.7时，系统自动记录知识缺口并触发外部检索（PubMed+EuropePMC）补充。高频缺口领域将生成批量获取建议。
            </template>
          </el-alert>

          <div v-if="gapData.stats">
            <el-row :gutter="16" style="margin-bottom: 16px;">
              <el-col :span="6"><el-statistic title="缺口总数" :value="gapData.stats.total_gaps" /></el-col>
              <el-col :span="6"><el-statistic title="已解决" :value="gapData.stats.resolved_count" /></el-col>
              <el-col :span="6"><el-statistic title="解决率" :value="Math.round((gapData.stats.resolution_rate || 0) * 100)" suffix="%" /></el-col>
              <el-col :span="6"><el-statistic title="平均相似度" :value="gapData.stats.avg_max_similarity?.toFixed(4) || 0" /></el-col>
            </el-row>

            <div v-if="gapData.stats.domain_distribution && Object.keys(gapData.stats.domain_distribution).length > 0">
              <h4>缺口领域分布</h4>
              <el-tag v-for="(count, domain) in gapData.stats.domain_distribution" :key="domain"
                type="warning" size="large" style="margin: 4px;">
                {{ domain }}: {{ count }}
              </el-tag>
            </div>
          </div>

          <el-divider />

          <h4 v-if="gapData.suggested_fetches && gapData.suggested_fetches.length > 0">建议批量获取任务</h4>
          <el-table v-if="gapData.suggested_fetches" :data="gapData.suggested_fetches" stripe>
            <el-table-column prop="domain" label="领域" width="120" />
            <el-table-column prop="gap_frequency" label="缺口频率" width="100" />
            <el-table-column prop="avg_similarity" label="平均相似度" width="120" />
            <el-table-column label="搜索词" min-width="200">
              <template #default="{ row }">
                <el-tag v-for="term in row.suggested_search_terms" :key="term" size="small" style="margin: 2px;">{{ term }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="priority" label="优先级" width="80">
              <template #default="{ row }">
                <el-tag :type="row.priority === 'high' ? 'danger' : 'warning'" size="small">{{ row.priority }}</el-tag>
              </template>
            </el-table-column>
          </el-table>

          <el-empty v-if="!gapData.stats || gapData.stats.total_gaps === 0" description="暂无知识缺口。当Agent检测到本地证据不足时会自动记录。" />
        </el-card>
      </el-tab-pane>

      <!-- Tab5: 安全审计 -->
      <el-tab-pane label="安全审计" name="safety">
        <el-card shadow="hover">
          <template #header>
            <div class="card-header">
              <span>安全防护与审计日志</span>
              <div style="display: flex; align-items: center; gap: 12px;">
                <el-tag v-if="safetyData.stats?.pending_review > 0" type="danger" effect="dark">
                  {{ safetyData.stats.pending_review }}条待审核
                </el-tag>
                <el-switch v-model="unreviewedOnly" active-text="只看待审核" @change="loadSafety" />
                <el-button size="small" @click="loadSafety" :loading="safetyLoading">刷新</el-button>
              </div>
            </div>
          </template>

          <el-alert type="error" :closable="false" style="margin-bottom: 16px;">
            <template #title>
              安全防护：所有自进化操作（经验记录、策略更新、原则蒸馏）均记录审计日志。高风险操作需人工审核后才生效。防止"错误进化"。
            </template>
          </el-alert>

          <!-- 安全阈值 -->
          <div v-if="safetyData.stats?.safety_thresholds" class="thresholds">
            <h4>安全阈值配置</h4>
            <el-descriptions :column="2" border size="small">
              <el-descriptions-item label="策略更新最少样本">{{ safetyData.stats.safety_thresholds.min_samples_for_strategy }}</el-descriptions-item>
              <el-descriptions-item label="原则蒸馏最少样本">{{ safetyData.stats.safety_thresholds.min_samples_for_principle }}</el-descriptions-item>
              <el-descriptions-item label="自动应用最低置信度">{{ (safetyData.stats.safety_thresholds.min_confidence_for_auto_apply * 100).toFixed(0) }}%</el-descriptions-item>
              <el-descriptions-item label="单次最大变化幅度">{{ (safetyData.stats.safety_thresholds.max_strategy_change_per_update * 100).toFixed(0) }}%</el-descriptions-item>
            </el-descriptions>
          </div>

          <!-- 风险分布 -->
          <div v-if="safetyData.stats?.risk_distribution" style="margin-top: 16px;">
            <h4>风险等级分布</h4>
            <el-tag v-for="(count, level) in safetyData.stats.risk_distribution" :key="level"
              :type="riskColors[level]" size="large" style="margin: 4px;">
              {{ riskLabels[level] }}: {{ count }}
            </el-tag>
          </div>

          <!-- 审计日志 -->
          <el-divider />
          <h4>审计日志</h4>
          <el-table :data="safetyData.recent_audits || []" stripe max-height="500" v-loading="safetyLoading">
            <el-table-column prop="action_type" label="操作类型" width="160">
              <template #default="{ row }">
                <el-tag size="small" :type="actionTypeColors[row.action_type] || 'info'">
                  {{ actionTypeLabels[row.action_type] || row.action_type }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="target_table" label="目标表" width="180" show-overflow-tooltip>
              <template #default="{ row }">
                {{ tableLabels[row.target_table] || row.target_table }}
              </template>
            </el-table-column>
            <el-table-column prop="change_summary" label="变更摘要" min-width="200" show-overflow-tooltip />
            <el-table-column prop="risk_level" label="风险" width="80">
              <template #default="{ row }">
                <el-tag :type="riskColors[row.risk_level]" size="small">{{ riskLabels[row.risk_level] }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="审核状态" width="100">
              <template #default="{ row }">
                <el-tag v-if="row.requires_review && !row.reviewed" type="warning" size="small">待审核</el-tag>
                <el-tag v-else-if="row.reviewed" type="success" size="small">已审核</el-tag>
                <el-tag v-else type="info" size="small">自动通过</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="timestamp" label="时间" width="160">
              <template #default="{ row }">{{ formatTime(row.timestamp) }}</template>
            </el-table-column>
            <el-table-column label="操作" width="150" fixed="right">
              <template #default="{ row }">
                <template v-if="row.requires_review && !row.reviewed">
                  <el-button size="small" type="success" @click="openReview(row)">审核</el-button>
                </template>
                <el-button v-else size="small" text @click="showAuditDetail(row)">查看</el-button>
              </template>
            </el-table-column>
          </el-table>

          <!-- 审计详情弹窗 -->
          <el-dialog v-model="auditDetailVisible" title="审计详情" width="650px" class="audit-dialog">
            <el-descriptions :column="1" border v-if="currentAudit">
              <el-descriptions-item label="操作类型">{{ actionTypeLabels[currentAudit.action_type] || currentAudit.action_type }}</el-descriptions-item>
              <el-descriptions-item label="目标表">{{ tableLabels[currentAudit.target_table] || currentAudit.target_table }}</el-descriptions-item>
              <el-descriptions-item label="目标ID">{{ currentAudit.target_id }}</el-descriptions-item>
              <el-descriptions-item label="变更摘要">{{ currentAudit.change_summary }}</el-descriptions-item>
              <el-descriptions-item label="风险等级">
                <el-tag :type="riskColors[currentAudit.risk_level]" size="small">{{ riskLabels[currentAudit.risk_level] }}</el-tag>
              </el-descriptions-item>
              <el-descriptions-item label="审核状态">
                <el-tag v-if="currentAudit.reviewed" type="success" size="small">已审核</el-tag>
                <el-tag v-else type="info" size="small">自动通过</el-tag>
              </el-descriptions-item>
              <el-descriptions-item label="变更前" v-if="currentAudit.old_value">
                <div class="json-viewer">{{ JSON.stringify(currentAudit.old_value, null, 2) }}</div>
              </el-descriptions-item>
              <el-descriptions-item label="变更后" v-if="currentAudit.new_value">
                <div class="json-viewer">{{ JSON.stringify(currentAudit.new_value, null, 2) }}</div>
              </el-descriptions-item>
              <el-descriptions-item label="审核备注" v-if="currentAudit.review_note">{{ currentAudit.review_note }}</el-descriptions-item>
            </el-descriptions>
          </el-dialog>

          <!-- 审核操作弹窗 -->
          <el-dialog v-model="reviewDialogVisible" title="审核操作" width="550px" class="audit-dialog">
            <div v-if="currentAudit" style="margin-bottom: 16px;">
              <el-descriptions :column="1" border size="small">
                <el-descriptions-item label="操作类型">{{ actionTypeLabels[currentAudit.action_type] || currentAudit.action_type }}</el-descriptions-item>
                <el-descriptions-item label="变更摘要">{{ currentAudit.change_summary }}</el-descriptions-item>
                <el-descriptions-item label="风险等级">
                  <el-tag :type="riskColors[currentAudit.risk_level]" size="small">{{ riskLabels[currentAudit.risk_level] }}</el-tag>
                </el-descriptions-item>
                <el-descriptions-item label="变更后值" v-if="currentAudit.new_value">
                  <div class="json-viewer">{{ JSON.stringify(currentAudit.new_value, null, 2) }}</div>
                </el-descriptions-item>
              </el-descriptions>
            </div>
            <el-input
              v-model="reviewNote"
              type="textarea"
              :rows="3"
              placeholder="请输入审核备注（可选）"
              style="margin-bottom: 16px;"
            />
            <div style="display: flex; justify-content: flex-end; gap: 12px;">
              <el-button @click="reviewDialogVisible = false">取消</el-button>
              <el-button type="danger" @click="confirmReview(false)" :loading="reviewLoading">拒绝</el-button>
              <el-button type="success" @click="confirmReview(true)" :loading="reviewLoading">通过</el-button>
            </div>
          </el-dialog>
        </el-card>
      </el-tab-pane>

    </el-tabs>

    <!-- 经验详情弹窗 -->
    <el-dialog v-model="expDetailVisible" title="经验详情" width="700px">
      <el-descriptions :column="2" border v-if="currentExp">
        <el-descriptions-item label="查询问题" :span="2">{{ currentExp.query }}</el-descriptions-item>
        <el-descriptions-item label="查询类型">{{ typeLabels[currentExp.query_type] || currentExp.query_type }}</el-descriptions-item>
        <el-descriptions-item label="自动评分">{{ (currentExp.auto_eval_score || 0).toFixed(4) }}</el-descriptions-item>
        <el-descriptions-item label="疾病标签" :span="2">
          <el-tag v-for="tag in (currentExp.disease_tags || [])" :key="tag" size="small" style="margin: 2px;">{{ tag }}</el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="使用策略" :span="2">
          <pre>{{ JSON.stringify(currentExp.strategy, null, 2) }}</pre>
        </el-descriptions-item>
        <el-descriptions-item label="检索结果" :span="2">
          <pre>{{ JSON.stringify(currentExp.outcome, null, 2) }}</pre>
        </el-descriptions-item>
        <el-descriptions-item label="工具调用记录" :span="2">
          <div v-for="(tc, i) in (currentExp.tool_calls || [])" :key="i" class="tool-call-detail">
            <el-tag size="small" :type="getTypeColor(tc.tool)">{{ tc.tool }}</el-tag>
            <span>{{ tc.result_summary || '执行中...' }}</span>
          </div>
        </el-descriptions-item>
      </el-descriptions>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { agentApi } from '@/utils/api'

const loading = ref(false)
const activeTab = ref('experiences')
const report = ref({})

// 经验
const experiences = ref([])
const expLoading = ref(false)
const expDetailVisible = ref(false)
const currentExp = ref(null)

// 自博弈
const selfPlayLoading = ref(false)
const selfPlayResult = ref(null)
const optimizedStrategies = ref([])

// 推理原则
const distillLoading = ref(false)
const principleData = ref({ stats: {}, principles: [] })

// 知识缺口
const gapData = ref({ stats: {}, suggested_fetches: [] })

// 安全
const safetyData = ref({ stats: {}, recent_audits: [] })
const safetyLoading = ref(false)
const unreviewedOnly = ref(false)
const reviewDialogVisible = ref(false)
const auditDetailVisible = ref(false)
const currentAudit = ref(null)
const reviewNote = ref('')
const reviewLoading = ref(false)

// 标签映射
const typeLabels = {
  treatment: '治疗推荐',
  diagnosis: '诊断标准',
  drug_interaction: '药物相互作用',
  prognosis: '预后评估',
  guideline_interpretation: '指南解读',
  mechanism: '机制原理'
}

const capabilityLabels = {
  knowledge_self_evolution: '知识自进化',
  strategy_self_evolution: '策略自进化',
  reasoning_self_evolution: '推理自进化',
  self_play_evaluation: '自博弈评估',
  cross_query_transfer: '跨查询迁移',
  safety_guard: '安全防护',
  human_in_the_loop: '人工审核'
}

const riskLabels = {
  low: '低风险',
  medium: '中风险',
  high: '高风险',
  critical: '极高风险'
}

const riskColors = {
  low: 'success',
  medium: 'warning',
  high: 'danger',
  critical: 'danger'
}

const actionTypeLabels = {
  strategy_update: '策略更新',
  principle_distillation: '原则蒸馏',
  experience_record: '经验记录',
  gap_detected: '缺口检测',
  knowledge_fetch: '知识获取'
}

const actionTypeColors = {
  strategy_update: 'warning',
  principle_distillation: 'danger',
  experience_record: 'success',
  gap_detected: 'info',
  knowledge_fetch: 'primary'
}

const tableLabels = {
  table_agent_experience: '经验记忆库',
  table_knowledge_gap: '知识缺口表',
  table_strategy_optimization: '策略优化表',
  table_reasoning_principle: '推理原则表',
  table_evolution_audit: '审计日志表'
}

onMounted(async () => {
  await loadReport()
  await loadExperiences()
})

async function loadReport() {
  loading.value = true
  try {
    const res = await agentApi.getFullReport()
    report.value = res
    // 提取已优化策略
    if (res.memory_bank?.optimized_types) {
      optimizedStrategies.value = res.memory_bank.optimized_types
    }
  } catch (e) {
    ElMessage.error('加载报告失败: ' + (e.message || '后端未启动'))
  } finally {
    loading.value = false
  }
}

async function loadExperiences() {
  expLoading.value = true
  try {
    const res = await agentApi.getExperiences(50)
    experiences.value = res.experiences || []
  } catch (e) {
    console.error('加载经验失败:', e)
  } finally {
    expLoading.value = false
  }
}

async function onTabChange(tab) {
  if (tab === 'principles' && !principleData.value.principles.length) {
    await loadPrinciples()
  } else if (tab === 'gaps' && !gapData.value.stats.total_gaps) {
    await loadGaps()
  } else if (tab === 'safety' && !safetyData.value.recent_audits?.length) {
    await loadSafety()
  }
}

async function loadPrinciples() {
  try {
    const res = await agentApi.getPrinciples(50)
    principleData.value = res
  } catch (e) {
    console.error('加载原则失败:', e)
  }
}

async function loadGaps() {
  try {
    const res = await agentApi.getGapStats()
    gapData.value = res
  } catch (e) {
    console.error('加载缺口失败:', e)
  }
}

async function loadSafety() {
  safetyLoading.value = true
  try {
    const [statsRes, logsRes] = await Promise.all([
      agentApi.getSafetyStats(),
      agentApi.getAuditLogs(50, null, unreviewedOnly.value)
    ])
    safetyData.value = {
      stats: statsRes.stats,
      recent_audits: logsRes.logs || []
    }
  } catch (e) {
    console.error('加载安全统计失败:', e)
  } finally {
    safetyLoading.value = false
  }
}

function openReview(audit) {
  currentAudit.value = audit
  reviewNote.value = ''
  reviewDialogVisible.value = true
}

function showAuditDetail(audit) {
  currentAudit.value = audit
  auditDetailVisible.value = true
}

async function confirmReview(approved) {
  if (!currentAudit.value) return
  reviewLoading.value = true
  try {
    await agentApi.reviewAudit(currentAudit.value.audit_id, approved, reviewNote.value)
    ElMessage.success(approved ? '审核已通过' : '审核已拒绝')
    reviewDialogVisible.value = false
    await loadSafety()
    await loadReport()
  } catch (e) {
    ElMessage.error('审核操作失败: ' + (e.message || ''))
  } finally {
    reviewLoading.value = false
  }
}

async function runSelfPlay() {
  selfPlayLoading.value = true
  try {
    ElMessage.info('自博弈评估已启动，请耐心等待...')
    const res = await agentApi.triggerSelfPlay(5)
    selfPlayResult.value = res
    if (res.updated_strategies?.length > 0) {
      ElMessage.success(`评估完成！更新了${res.updated_strategies.length}种策略`)
    } else {
      ElMessage.warning('评估完成，但无策略更新（可能经验不足）')
    }
    await loadReport()
  } catch (e) {
    ElMessage.error('自博弈评估失败: ' + (e.message || '超时'))
  } finally {
    selfPlayLoading.value = false
  }
}

async function runDistillation() {
  distillLoading.value = true
  try {
    ElMessage.info('推理原则蒸馏已启动...')
    const res = await agentApi.triggerDistillation(null)
    if (res.distilled_count > 0) {
      ElMessage.success(`蒸馏完成！提取了${res.distilled_count}条推理原则`)
    } else {
      ElMessage.warning('蒸馏完成，但未提取到原则（需要更多高分经验）')
    }
    await loadPrinciples()
    await loadReport()
  } catch (e) {
    ElMessage.error('蒸馏失败: ' + (e.message || '超时'))
  } finally {
    distillLoading.value = false
  }
}

function showExpDetail(exp) {
  currentExp.value = exp
  expDetailVisible.value = true
}

function getTypeColor(type) {
  const colors = {
    treatment: 'success',
    diagnosis: 'primary',
    drug_interaction: 'warning',
    prognosis: 'danger',
    guideline_interpretation: '',
    mechanism: 'info'
  }
  return colors[type] || 'info'
}

function getScoreColor(score) {
  if (score >= 0.8) return '#67c23a'
  if (score >= 0.6) return '#e6a23c'
  return '#909399'
}

function formatTime(ts) {
  if (!ts) return '-'
  try {
    return new Date(ts).toLocaleString('zh-CN', { hour12: false })
  } catch {
    return ts
  }
}
</script>

<style scoped>
.evolution-view {
  max-width: 1400px;
  margin: 0 auto;
}

.overview-row {
  margin-bottom: 16px;
}

.overview-card {
  height: 100px;
}

.overview-content {
  display: flex;
  align-items: center;
  gap: 16px;
}

.overview-icon {
  font-size: 36px;
}

.overview-info {
  display: flex;
  flex-direction: column;
}

.overview-value {
  font-size: 28px;
  font-weight: bold;
  color: #303133;
}

.overview-label {
  font-size: 14px;
  color: #909399;
}

.section-card {
  margin-bottom: 16px;
}

.card-header {
  display: flex;
  align-items: center;
  gap: 8px;
  justify-content: space-between;
}

.card-header span:first-child {
  flex: 1;
}

.capabilities-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
}

.capability-item {
  display: inline-block;
}

.main-tabs {
  margin-top: 16px;
}

.type-distribution {
  padding: 8px 0;
}

.principle-card {
  margin-bottom: 12px;
  border-left: 4px solid #409eff;
}

.principle-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}

.principle-text {
  font-size: 15px;
  font-weight: 500;
  color: #303133;
}

.principle-meta {
  display: flex;
  align-items: center;
  gap: 16px;
}

.principle-usage {
  font-size: 13px;
  color: #909399;
}

.principle-time {
  font-size: 12px;
  color: #c0c4cc;
}

.tool-call-detail {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 4px 0;
  font-size: 13px;
}

.thresholds {
  margin-bottom: 16px;
}

.json-viewer {
  max-height: 250px;
  overflow-y: auto;
  overflow-x: hidden;
  white-space: pre-wrap;
  word-break: break-all;
  font-family: 'Consolas', 'Monaco', monospace;
  font-size: 12px;
  line-height: 1.5;
  padding: 8px;
  background: #f6f8fa;
  border-radius: 4px;
  border: 1px solid #e1e4e8;
}

.audit-dialog :deep(.el-dialog__body) {
  max-height: 60vh;
  overflow-y: auto;
}
</style>
