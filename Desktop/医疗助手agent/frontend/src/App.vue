<template>
  <el-container class="app-container">
    <!-- 顶部导航栏 -->
    <el-header class="app-header">
      <div class="header-left">
        <el-icon class="logo-icon"><Document /></el-icon>
        <span class="app-title">OpenEvidence 临床证据助手</span>
      </div>
      <div class="header-right">
        <el-menu mode="horizontal" :default-active="activeMenu" router :ellipsis="false">
          <el-menu-item index="/chat">
            <el-icon><ChatDotRound /></el-icon>
            <span>循证问答</span>
          </el-menu-item>
          <el-menu-item index="/admin/knowledge">
            <el-icon><Folder /></el-icon>
            <span>知识库管理</span>
          </el-menu-item>
          <el-menu-item index="/admin/eval">
            <el-icon><DataAnalysis /></el-icon>
            <span>效果评测</span>
          </el-menu-item>
          <el-menu-item index="/admin/evolution">
            <el-icon><MagicStick /></el-icon>
            <span>自进化监控</span>
          </el-menu-item>
        </el-menu>
      </div>
    </el-header>

    <!-- 主内容区域 -->
    <el-main class="app-main">
      <router-view />
    </el-main>

    <!-- 底部信息 -->
    <el-footer class="app-footer">
      <span>面向临床医生的循证证据问答工具 | 支持高血压、高血脂、2型糖尿病、心脑血管合并症</span>
    </el-footer>
  </el-container>
</template>

<script setup>
import { computed } from 'vue'
import { useRoute } from 'vue-router'

const route = useRoute()
const activeMenu = computed(() => route.path)
</script>

<style>
.app-container {
  height: 100vh;
  display: flex;
  flex-direction: column;
}

.app-header {
  background: linear-gradient(135deg, #1890ff 0%, #096dd9 100%);
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 20px;
  height: 60px;
}

.header-left {
  display: flex;
  align-items: center;
  color: white;
}

.logo-icon {
  font-size: 28px;
  margin-right: 12px;
}

.app-title {
  font-size: 18px;
  font-weight: bold;
}

.header-right .el-menu {
  background: transparent;
  border-bottom: none;
}

.header-right .el-menu-item {
  color: white;
  border-bottom: none;
}

.header-right .el-menu-item:hover,
.header-right .el-menu-item.is-active {
  background: rgba(255, 255, 255, 0.2);
  border-bottom: none;
}

.app-main {
  background: #f5f7fa;
  padding: 20px;
  overflow: auto;
}

.app-footer {
  background: #fafafa;
  border-top: 1px solid #e8e8e8;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  color: #666;
  height: 40px;
}
</style>