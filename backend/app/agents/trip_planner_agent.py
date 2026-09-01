"""多智能体旅行规划系统 (兼容适配层)

注意:
系统已全面迁移至基于 LangGraph 的显式状态图编排工作流 (backend/app/workflow/)。
本模块作为向后兼容适配层，内部委托给 LangGraph 工作流引擎执行，
已彻底废除伪多 Agent 字符串工具匹配与硬编码虚假数据兜底 (_create_fallback_plan)。
"""

from typing import Dict, Any, Optional
from loguru import logger
from ..models.schemas import TripRequest, TripPlan
from ..workflow import run_trip_planner_workflow, get_trip_planner_graph


class MultiAgentTripPlanner:
    """旅行规划器 (LangGraph 兼容封装)"""

    def __init__(self):
        """初始化旅行规划器并预热 LangGraph 状态图"""
        logger.info("初始化旅行规划适配器，预热 LangGraph 状态图...")
        self.graph = get_trip_planner_graph()

    def plan_trip(self, request: TripRequest) -> TripPlan:
        """委托给 LangGraph 状态图工作流执行旅行规划

        Args:
            request: 旅行请求数据

        Returns:
            经真实性校验与精确运算后的旅行计划

        Raises:
            RuntimeError: 工作流校验失败或修补超限
        """
        logger.info(
            f"MultiAgentTripPlanner 收到旅行规划请求 | 城市: {request.city} | 天数: {request.travel_days} 天"
        )
        final_state = run_trip_planner_workflow(request)

        if final_state.get("is_failed"):
            error_msg = (
                final_state.get("error_message")
                or "旅行规划执行失败: 未通过真实性校验"
            )
            logger.error(f"LangGraph 工作流未能成功交付: {error_msg}")
            raise RuntimeError(error_msg)

        final_plan = final_state.get("final_plan")
        if not final_plan:
            raise RuntimeError("旅行规划工作流异常：未能生成有效计划数据")

        return final_plan


# 全局单例
_multi_agent_planner: Optional[MultiAgentTripPlanner] = None


def get_trip_planner_agent() -> MultiAgentTripPlanner:
    """获取旅行规划适配器单例"""
    global _multi_agent_planner
    if _multi_agent_planner is None:
        _multi_agent_planner = MultiAgentTripPlanner()
    return _multi_agent_planner
