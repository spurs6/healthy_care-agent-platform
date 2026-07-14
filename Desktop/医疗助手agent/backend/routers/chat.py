"""
OpenEvidence 临床证据助手 - 问答路由
支持传统RAG问答和自进化Agent问答
"""
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional, List, AsyncIterator
import asyncio
import json
from datetime import datetime

from backend.rag_core import rag_retriever
from backend.llm_service import llm_service, domain_filter
from backend.db_store import RetrievedChunk


router = APIRouter()


def _sse_data(payload: dict) -> str:
    """把普通 JSON 包装成 SSE data 帧。"""
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


class ChatRequest(BaseModel):
    """问答请求"""
    query: str
    session_id: Optional[str] = None


class ChatResponse(BaseModel):
    """问答响应"""
    answer: str
    chunks: List[dict]
    has_evidence: bool
    query: str
    timestamp: str


# ==================== 传统RAG问答（保留兼容）====================
@router.post("/query", response_model=ChatResponse)
async def chat_query(request: ChatRequest):
    """问答接口 - 非流式"""
    query = request.query.strip()
    if not query:
        raise HTTPException(status_code=400, detail="问题不能为空")
    chunks, has_evidence = rag_retriever.retrieve(query)
    response = await llm_service.answer(query, chunks, has_evidence)
    return ChatResponse(**response)


@router.post("/stream")
async def chat_stream(request: ChatRequest):
    """问答接口 - SSE流式返回（传统RAG模式）"""
    query = request.query.strip()
    if not query:
        raise HTTPException(status_code=400, detail="问题不能为空")

    async def generate() -> AsyncIterator[str]:
        yield _sse_data({"type": "status", "message": "正在检索临床证据..."})
        chunks, has_evidence = rag_retriever.retrieve(query)
        if chunks:
            yield _sse_data({
                "type": "chunks",
                "data": [
                    {"chunk_id": c["chunk_id"], "doc_id": c["doc_id"],
                     "title": c["title"], "score": c["score"]}
                    for c in chunks[:5]
                ]
            })
        yield _sse_data({"type": "status", "message": "正在生成循证答案..."})
        full_answer = []
        async for chunk in llm_service.stream_answer(query, chunks, has_evidence):
            full_answer.append(chunk)
            yield _sse_data({"type": "text", "content": chunk})
        if chunks:
            refs = llm_service.format_references(chunks)
            yield _sse_data({"type": "references", "content": refs})
        yield _sse_data({"type": "done", "message": "回答完成"})

    return StreamingResponse(
        generate(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"}
    )


# ==================== 自进化Agent问答 ====================
@router.post("/agent_stream")
async def agent_stream(request: ChatRequest):
    """
    Agent问答接口 - SSE流式返回（自进化Agent模式）
    
    SSE消息类型:
    - status: 状态更新
    - tool_call: Agent调用工具
    - tool_result: 工具执行结果
    - chunks: 检索到的证据
    - text: 答案文本片段
    - references: 参考文献附录
    - done: 回答完成
    """
    query = request.query.strip()
    if not query:
        raise HTTPException(status_code=400, detail="问题不能为空")

    async def generate() -> AsyncIterator[str]:
        try:
            from backend.agent.agent_loop import get_medical_agent
            agent = get_medical_agent()

            async for event in agent.stream_answer(query):
                yield _sse_data(event)

        except Exception as e:
            yield _sse_data({"type": "text", "content": f"[Agent异常: {str(e)}]"})
            yield _sse_data({"type": "done", "message": "回答完成"})

    return StreamingResponse(
        generate(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"}
    )


# ==================== 自进化状态接口 ====================
@router.get("/evolution/status")
async def get_evolution_status():
    """获取Agent自进化状态报告"""
    try:
        from backend.agent.memory_bank import memory_bank
        from backend.agent.gap_logger import gap_logger
        from backend.agent.strategy_evolution import strategy_evolution

        return strategy_evolution.get_evolution_report()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取进化状态失败: {str(e)}")


@router.get("/evolution/experiences")
async def get_experiences(limit: int = 50):
    """获取最近的Agent经验记录"""
    try:
        from backend.agent.memory_bank import memory_bank
        experiences = memory_bank.get_recent_experiences(limit)
        return {"total": len(experiences), "experiences": experiences}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取经验记录失败: {str(e)}")


@router.get("/evolution/gaps")
async def get_gap_stats():
    """获取知识缺口统计"""
    try:
        from backend.agent.gap_logger import gap_logger
        stats = gap_logger.get_gap_stats()
        recent = gap_logger.get_recent_gaps(10)
        suggestions = gap_logger.get_suggested_fetch_tasks()
        return {"stats": stats, "recent_gaps": recent, "suggested_fetches": suggestions}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取缺口统计失败: {str(e)}")


@router.post("/evolution/self_play")
async def trigger_self_play(sample_count: int = 5):
    """手动触发自博弈评估"""
    try:
        from backend.agent.strategy_evolution import strategy_evolution
        from backend.agent.safety_guard import safety_guard, RiskLevel
        result = await strategy_evolution.self_play_evaluate(sample_count)

        # 安全审计：记录策略更新
        if result.get("updated_strategies"):
            for s in result["updated_strategies"]:
                safety_guard.log_evolution_action(
                    action_type="strategy_update",
                    target_table="table_strategy_optimization",
                    target_id=s["query_type"],
                    change_summary=f"更新{ s['query_type']}策略, 均分={s['avg_score']:.3f}",
                    new_value=s["best_strategy"],
                    risk_level=RiskLevel.MEDIUM,
                    requires_review=True
                )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"自博弈评估失败: {str(e)}")


# ==================== 推理原则接口（Phase 3）====================
@router.post("/evolution/distill")
async def trigger_distillation(query_type: str = None):
    """手动触发推理原则蒸馏"""
    try:
        from backend.agent.reasoning_evolution import reasoning_evolution
        from backend.agent.safety_guard import safety_guard, RiskLevel
        result = await reasoning_evolution.distill_principles(query_type)

        # 安全审计
        if result.get("distilled_count", 0) > 0:
            safety_guard.log_evolution_action(
                action_type="principle_distillation",
                target_table="table_reasoning_principle",
                target_id=query_type or "all",
                change_summary=f"蒸馏出{result['distilled_count']}条推理原则",
                new_value={"principles": result.get("principles", [])},
                risk_level=RiskLevel.HIGH,
                requires_review=True
            )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"原则蒸馏失败: {str(e)}")


@router.get("/evolution/principles")
async def get_principles(limit: int = 50):
    """获取推理原则列表"""
    try:
        from backend.agent.reasoning_evolution import reasoning_evolution
        stats = reasoning_evolution.get_principle_stats()
        all_principles = reasoning_evolution.get_all_principles(limit)
        return {"stats": stats, "principles": all_principles}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取原则失败: {str(e)}")


# ==================== 安全审计接口 ====================
@router.get("/evolution/safety")
async def get_safety_stats():
    """获取安全防护统计"""
    try:
        from backend.agent.safety_guard import safety_guard
        stats = safety_guard.get_safety_stats()
        logs = safety_guard.get_audit_logs(limit=20)
        return {"stats": stats, "recent_audits": logs}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取安全统计失败: {str(e)}")


@router.get("/evolution/safety/audit")
async def get_audit_logs(limit: int = 50, risk_level: str = None, unreviewed_only: bool = False):
    """获取审计日志"""
    try:
        from backend.agent.safety_guard import safety_guard
        logs = safety_guard.get_audit_logs(limit, risk_level, unreviewed_only)
        return {"total": len(logs), "logs": logs}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取审计日志失败: {str(e)}")


@router.post("/evolution/safety/review")
async def review_audit(audit_id: str, approved: bool, note: str = "", reviewer: str = "admin"):
    """审核审计日志"""
    try:
        from backend.agent.safety_guard import safety_guard
        safety_guard.review_audit_log(audit_id, reviewer, approved, note)
        return {"message": "审核完成", "audit_id": audit_id, "approved": approved}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"审核失败: {str(e)}")


@router.get("/evolution/full_report")
async def get_full_evolution_report():
    """获取完整的自进化状态报告（含推理原则和安全）"""
    try:
        from backend.agent.memory_bank import memory_bank
        from backend.agent.gap_logger import gap_logger
        from backend.agent.reasoning_evolution import reasoning_evolution
        from backend.agent.safety_guard import safety_guard

        return {
            "memory_bank": memory_bank.get_stats(),
            "knowledge_gaps": gap_logger.get_gap_stats(),
            "reasoning_principles": reasoning_evolution.get_principle_stats(),
            "safety": safety_guard.get_safety_stats(),
            "capabilities": {
                "knowledge_self_evolution": True,
                "strategy_self_evolution": memory_bank.get_stats()["total_experiences"] >= 10,
                "reasoning_self_evolution": reasoning_evolution.get_principle_stats()["total_principles"] > 0,
                "self_play_evaluation": True,
                "cross_query_transfer": True,
                "safety_guard": True,
                "human_in_the_loop": True
            },
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取报告失败: {str(e)}")


# ==================== 基础接口（保留兼容）====================
@router.get("/domain_check")
async def check_domain(query: str):
    """检查问题是否在允许领域内"""
    is_allowed = domain_filter.is_allowed_domain(query)
    return {
        "is_allowed": is_allowed,
        "message": domain_filter.get_reject_message() if not is_allowed else "问题在服务范围内"
    }
