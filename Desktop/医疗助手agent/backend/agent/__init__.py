"""
自进化医疗循证Agent模块

Phase 1: Agent工具调用框架
- Agent Loop with LangChain tool calling
- External search (PubMed + EuropePMC)
- Local knowledge base search

Phase 2: 自进化能力
- Experience memory bank
- Knowledge gap logging
- Strategy self-evolution
"""

# 延迟导入，避免启动时加载所有依赖
def get_agent():
    """获取Agent实例（延迟初始化）"""
    from backend.agent.agent_loop import medical_agent
    return medical_agent


def get_memory_bank():
    """获取经验记忆库实例"""
    from backend.agent.memory_bank import memory_bank
    return memory_bank


def get_gap_logger():
    """获取知识缺口记录器实例"""
    from backend.agent.gap_logger import gap_logger
    return gap_logger
