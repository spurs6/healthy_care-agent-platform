import axios from 'axios'
import { ElMessage } from 'element-plus'

const BASE_URL = '/api'

// 创建axios实例
const apiClient = axios.create({
  baseURL: BASE_URL,
  timeout: 120000,
  headers: {
    'Content-Type': 'application/json'
  }
})

// 请求拦截器
apiClient.interceptors.request.use(
  config => {
    return config
  },
  error => {
    return Promise.reject(error)
  }
)

// 响应拦截器
apiClient.interceptors.response.use(
  response => {
    return response.data
  },
  error => {
    const message = error.response?.data?.message || error.message || '请求失败'
    ElMessage.error(message)
    return Promise.reject(error)
  }
)

// ==================== 问答接口 ====================
export const chatApi = {
  // 流式问答
  streamChat(query, onMessage, onError, onComplete) {
    const eventSource = new EventSource(
      `${BASE_URL}/chat/stream?query=${encodeURIComponent(query)}`
    )
    
    eventSource.onmessage = (event) => {
      const data = JSON.parse(event.data)
      onMessage(data)
    }
    
    eventSource.onerror = (error) => {
      eventSource.close()
      if (onError) onError(error)
    }
    
    return eventSource
  },
  
  // POST流式问答
  async streamChatPost(query, onMessage, onError, onComplete) {
    try {
      const response = await fetch(`${BASE_URL}/chat/stream`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query })
      })

      if (!response.ok || !response.body) {
        const message = await response.text()
        throw new Error(message || `请求失败: ${response.status}`)
      }
      
      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        
        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''
        
        for (const line of lines) {
          const trimmed = line.trim()
          if (!trimmed) continue

          const dataStr = trimmed.startsWith('data:')
            ? trimmed.slice(5).trim()
            : trimmed

          if (dataStr === '[DONE]') {
            if (onComplete) onComplete()
            continue
          }

          try {
            const data = JSON.parse(dataStr)
            onMessage(data)
          } catch (e) {
            // 忽略非 JSON 行
          }
        }
      }

      if (buffer.trim()) {
        const lastLine = buffer.trim()
        const dataStr = lastLine.startsWith('data:') ? lastLine.slice(5).trim() : lastLine
        if (dataStr && dataStr !== '[DONE]') {
          try {
            onMessage(JSON.parse(dataStr))
          } catch (e) {
            // 忽略尾部残留
          }
        }
      }

      if (onComplete) onComplete()
    } catch (error) {
      if (onError) onError(error)
    }
  },
  
  // 非流式问答
  query(query) {
    return apiClient.post('/chat/query', { query })
  },

  // 领域检查
  domainCheck(query) {
    return apiClient.get(`/chat/domain_check?query=${encodeURIComponent(query)}`)
  }
}

// ==================== Agent问答接口 ====================
export const agentApi = {
  // Agent流式问答
  async streamAgentChat(query, onMessage, onError, onComplete) {
    try {
      const response = await fetch(`${BASE_URL}/chat/agent_stream`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query })
      })

      if (!response.ok || !response.body) {
        const message = await response.text()
        throw new Error(message || `请求失败: ${response.status}`)
      }

      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''

        for (const line of lines) {
          const trimmed = line.trim()
          if (!trimmed) continue

          const dataStr = trimmed.startsWith('data:')
            ? trimmed.slice(5).trim()
            : trimmed

          try {
            const data = JSON.parse(dataStr)
            onMessage(data)
          } catch (e) {
            // 忽略非JSON行
          }
        }
      }

      if (onComplete) onComplete()
    } catch (error) {
      if (onError) onError(error)
    }
  },

  // 获取自进化状态
  getEvolutionStatus() {
    return apiClient.get('/chat/evolution/status')
  },

  // 获取经验记录
  getExperiences(limit = 50) {
    return apiClient.get('/chat/evolution/experiences', { params: { limit } })
  },

  // 获取知识缺口统计
  getGapStats() {
    return apiClient.get('/chat/evolution/gaps')
  },

  // 触发自博弈评估
  triggerSelfPlay(sampleCount = 5) {
    return apiClient.post('/chat/evolution/self_play', null, { params: { sample_count: sampleCount } })
  },

  // 触发推理原则蒸馏
  triggerDistillation(queryType = null) {
    const params = {}
    if (queryType) params.query_type = queryType
    return apiClient.post('/chat/evolution/distill', null, { params })
  },

  // 获取推理原则列表
  getPrinciples(limit = 50) {
    return apiClient.get('/chat/evolution/principles', { params: { limit } })
  },

  // 获取安全审计统计
  getSafetyStats() {
    return apiClient.get('/chat/evolution/safety')
  },

  // 获取审计日志
  getAuditLogs(limit = 50, riskLevel = null, unreviewedOnly = false) {
    return apiClient.get('/chat/evolution/safety/audit', { params: { limit, risk_level: riskLevel, unreviewed_only: unreviewedOnly } })
  },

  // 审核审计日志
  reviewAudit(auditId, approved, note = '') {
    return apiClient.post('/chat/evolution/safety/review', null, { params: { audit_id: auditId, approved, note } })
  },

  // 获取完整自进化报告
  getFullReport() {
    return apiClient.get('/chat/evolution/full_report')
  }
}

// ==================== 知识库管理接口 ====================
export const adminApi = {
  // 获取文档列表
  getDocuments(params) {
    return apiClient.get('/admin/documents', { params })
  },
  
  // 获取单个文档
  getDocument(docId) {
    return apiClient.get(`/admin/documents/${docId}`)
  },
  
  // 删除文档
  deleteDocument(docId) {
    return apiClient.delete(`/admin/documents/${docId}`)
  },
  
  // 上传中文指南
  uploadCnGuide(file) {
    const formData = new FormData()
    formData.append('file', file)
    return apiClient.post('/admin/upload/cn_guide', formData, {
      headers: { 'Content-Type': 'multipart/form-data' }
    })
  },
  
  // 上传英文文献
  uploadEnPubmed(file) {
    const formData = new FormData()
    formData.append('file', file)
    return apiClient.post('/admin/upload/en_pubmed', formData, {
      headers: { 'Content-Type': 'multipart/form-data' }
    })
  },
  
  // 处理文档
  processDocument(docId) {
    return apiClient.post(`/admin/process/${docId}`)
  },
  
  // 批量处理
  batchProcess(docIds) {
    return apiClient.post('/admin/batch_process', docIds)
  },
  
  // 增量更新
  startIncrementalUpdate(source, days = 30) {
    return apiClient.post(`/admin/incremental/start?source=${source}&days=${days}`)
  },
  
  // 获取增量任务状态
  getIncrementalStatus(taskType) {
    return apiClient.get(`/admin/incremental/status?task_type=${taskType}`)
  },
  
  // 获取统计信息
  getStats() {
    return apiClient.get('/admin/stats')
  },
  
  // 获取向量库统计
  getCollectionStats() {
    return apiClient.get('/admin/stats/collections')
  },
  
  // 搜索临床试验
  searchClinicalTrials(params) {
    return apiClient.get('/admin/clinical_trials', { params })
  }
}

// ==================== 评测接口 ====================
export const evalApi = {
  // 获取测试集列表
  getTestSets() {
    return apiClient.get('/eval/test_sets')
  },
  
  // 上传测试集
  uploadTestSet(file) {
    const formData = new FormData()
    formData.append('file', file)
    return apiClient.post('/eval/test_sets/upload', formData, {
      headers: { 'Content-Type': 'multipart/form-data' }
    })
  },
  
  // 获取测试集内容
  getTestSet(filename) {
    return apiClient.get(`/eval/test_sets/${filename}`)
  },
  
  // 删除测试集
  deleteTestSet(filename) {
    return apiClient.delete(`/eval/test_sets/${filename}`)
  },
  
  // 基于知识库生成测试集
  generateTestSet(numQuestions = 10) {
    return apiClient.post(`/eval/test_sets/generate?num_questions=${numQuestions}`)
  },
  
  // 运行评测
  runEvaluation(filename, limit = 10) {
    return apiClient.post(`/eval/run?filename=${filename}&limit=${limit}`)
  },
  
  // 获取评测历史
  getHistory(limit = 20) {
    return apiClient.get(`/eval/history?limit=${limit}`)
  },
  
  // 获取评测详情
  getEvalDetail(evalId) {
    return apiClient.get(`/eval/history/${evalId}`)
  },
  
  // 删除评测记录
  deleteEvalHistory(evalId) {
    return apiClient.delete(`/eval/history/${evalId}`)
  },
  
  // 导出评测报告
  exportReport(report) {
    return apiClient.post('/eval/export', report)
  }
}

export default apiClient
