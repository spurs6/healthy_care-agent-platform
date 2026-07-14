import { defineStore } from 'pinia'
import { ref } from 'vue'
import { chatApi, agentApi } from '@/utils/api'

export const useChatStore = defineStore('chat', () => {
  // 当前问题
  const currentQuery = ref('')
  
  // 当前答案
  const currentAnswer = ref('')
  
  // 检索到的证据
  const retrievedChunks = ref([])
  
  // 是否正在加载
  const isLoading = ref(false)
  
  // 错误信息
  const error = ref(null)
  
  // 历史记录
  const history = ref([])
  
  // Agent模式开关
  const agentMode = ref(true)
  
  // Agent工具调用记录
  const toolCalls = ref([])
  
  // 当前状态消息
  const statusMessage = ref('')
  
  // 流式问答（传统RAG模式）
  async function streamQuery(query) {
    currentQuery.value = query
    currentAnswer.value = ''
    retrievedChunks.value = []
    isLoading.value = true
    error.value = null
    toolCalls.value = []
    statusMessage.value = ''
    
    await chatApi.streamChatPost(
      query,
      (data) => {
        _handleSSEMessage(data, query)
      },
      (err) => {
        isLoading.value = false
        error.value = err.message || '请求失败'
      },
      () => {
        isLoading.value = false
      }
    )
  }
  
  // Agent流式问答
  async function streamAgentQuery(query) {
    currentQuery.value = query
    currentAnswer.value = ''
    retrievedChunks.value = []
    isLoading.value = true
    error.value = null
    toolCalls.value = []
    statusMessage.value = ''
    
    await agentApi.streamAgentChat(
      query,
      (data) => {
        _handleAgentSSEMessage(data, query)
      },
      (err) => {
        isLoading.value = false
        error.value = err.message || 'Agent请求失败'
      },
      () => {
        isLoading.value = false
      }
    )
  }
  
  // 统一SSE消息处理（传统模式）
  function _handleSSEMessage(data, query) {
    if (data.type === 'status') {
      statusMessage.value = data.message
    } else if (data.type === 'chunks') {
      retrievedChunks.value = data.data || []
    } else if (data.type === 'text') {
      currentAnswer.value += data.content
    } else if (data.type === 'references') {
      currentAnswer.value += data.content
    } else if (data.type === 'done') {
      isLoading.value = false
      statusMessage.value = ''
      _addToHistory(query)
    }
  }
  
  // Agent SSE消息处理
  function _handleAgentSSEMessage(data, query) {
    if (data.type === 'status') {
      statusMessage.value = data.message
    } else if (data.type === 'tool_call') {
      toolCalls.value.push({
        tool: data.tool,
        input: data.input,
        result: null,
        timestamp: new Date().toISOString()
      })
      // 根据工具类型设置状态消息
      const toolMessages = {
        'local_search': '正在检索本地知识库...',
        'external_search': '正在实时搜索PubMed和EuropePMC...',
        'evidence_evaluator': '正在评估证据充分性...',
        'query_classifier': '正在分析问题类型...'
      }
      statusMessage.value = toolMessages[data.tool] || `调用工具: ${data.tool}`
    } else if (data.type === 'tool_result') {
      // 更新对应工具调用的结果
      const lastCall = toolCalls.value.find(
        tc => tc.tool === data.tool && tc.result === null
      )
      if (lastCall) {
        lastCall.result = data.summary
      }
    } else if (data.type === 'chunks') {
      // 追加证据（Agent可能多次检索）
      const newChunks = data.data || []
      retrievedChunks.value = [...retrievedChunks.value, ...newChunks]
    } else if (data.type === 'text') {
      currentAnswer.value += data.content
    } else if (data.type === 'references') {
      currentAnswer.value += data.content
    } else if (data.type === 'done') {
      isLoading.value = false
      statusMessage.value = ''
      _addToHistory(query)
    }
  }
  
  function _addToHistory(query) {
    history.value.push({
      query,
      answer: currentAnswer.value,
      chunks: retrievedChunks.value,
      timestamp: new Date().toISOString(),
      agentMode: agentMode.value,
      toolCalls: toolCalls.value.length
    })
  }
  
  // 自动选择模式
  async function autoQuery(query) {
    if (agentMode.value) {
      await streamAgentQuery(query)
    } else {
      await streamQuery(query)
    }
  }
  
  // 非流式问答
  async function query(query) {
    currentQuery.value = query
    isLoading.value = true
    error.value = null
    
    try {
      const response = await chatApi.query(query)
      currentAnswer.value = response.answer
      retrievedChunks.value = response.chunks
      
      _addToHistory(query)
    } catch (err) {
      error.value = err.message
    } finally {
      isLoading.value = false
    }
  }
  
  // 切换模式
  function toggleAgentMode() {
    agentMode.value = !agentMode.value
  }
  
  // 清空当前状态
  function clearCurrent() {
    currentQuery.value = ''
    currentAnswer.value = ''
    retrievedChunks.value = []
    error.value = null
    toolCalls.value = []
    statusMessage.value = ''
  }
  
  // 清空历史
  function clearHistory() {
    history.value = []
  }
  
  return {
    currentQuery,
    currentAnswer,
    retrievedChunks,
    isLoading,
    error,
    history,
    agentMode,
    toolCalls,
    statusMessage,
    streamQuery,
    streamAgentQuery,
    autoQuery,
    query,
    toggleAgentMode,
    clearCurrent,
    clearHistory
  }
})
