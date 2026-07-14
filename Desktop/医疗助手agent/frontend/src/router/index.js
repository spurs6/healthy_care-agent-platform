import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  {
    path: '/',
    redirect: '/chat'
  },
  {
    path: '/chat',
    name: 'Chat',
    component: () => import('@/views/ChatView.vue'),
    meta: { title: '循证问答' }
  },
  {
    path: '/admin/knowledge',
    name: 'Knowledge',
    component: () => import('@/views/KnowledgeView.vue'),
    meta: { title: '知识库管理' }
  },
  {
    path: '/admin/eval',
    name: 'Evaluation',
    component: () => import('@/views/EvaluationView.vue'),
    meta: { title: '效果评测' }
  },
  {
    path: '/admin/evolution',
    name: 'Evolution',
    component: () => import('@/views/EvolutionView.vue'),
    meta: { title: '自进化监控' }
  }
]

const router = createRouter({
  history: createWebHistory(),
  routes
})

router.beforeEach((to, from, next) => {
  document.title = to.meta.title ? `${to.meta.title} - OpenEvidence` : 'OpenEvidence'
  next()
})

export default router