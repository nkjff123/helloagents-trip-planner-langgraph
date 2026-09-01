"""LangGraph 旅行规划工作流图构建与编译模块 (StateGraph)

核心拓扑架构:
1. 输入校验与前置拦截 (normalize_and_validate_input -> 失败直接终止)
2. 解耦并发分支:
   - 分支 A: 天气查询 (fetch_weather_node)
   - 分支 B: 搜索策略规划 (generate_search_strategy_node)
     -> 并行三路检索 (search_attractions, search_hotels, search_restaurants)
     -> 景点初筛精选 (curate_attractions_node)
3. 聚合决策:
   - 多日行程骨架合成 (synthesize_itinerary_node, 汇总天气与精选实体)
4. 确定性后处理链路:
   - 真实实体还原 (rehydrate_entities_node)
   -> 交通路线丰富 (enrich_routes_node)
   -> 确定性精准预算运算 (calculate_budget_node)
   -> 严格真实性与防篡改校验 (validate_grounding_node)
5. 条件分支转移:
   - 校验通过 -> END (交付最终旅行计划)
   - 校验未通过且修补次数 < 2 -> repair_skeleton_node -> rehydrate_entities_node (自愈循环)
   - 校验未通过且修补次数 >= 2 -> failure_node -> END (显式失败，拒绝伪造假数据)
"""

from typing import Dict, Any, List, Union
from loguru import logger
from langgraph.graph import StateGraph, START, END
from langgraph.graph.state import CompiledStateGraph

from ..models.schemas import TripRequest
from ..models.state import TripPlannerState
from .nodes.input_nodes import normalize_and_validate_input
from .nodes.search_nodes import (
    fetch_weather_node,
    search_attractions,
    search_hotels,
    search_restaurants,
)
from .nodes.reasoning_nodes import (
    generate_search_strategy_node,
    curate_attractions_node,
    synthesize_itinerary_node,
    repair_skeleton_node,
)
from .nodes.postprocess_nodes import (
    rehydrate_entities_node,
    enrich_routes_node,
    calculate_budget_node,
    validate_grounding_node,
    failure_node,
)


def route_after_input_validation(
    state: TripPlannerState,
) -> Union[str, List[str]]:
    """输入校验后的路由分支决策

    若前置输入参数校验失败，直接路由至 failure_node；
    否则同时扇出至天气查询节点与检索策略规划节点。
    """
    if state.get("is_failed", False):
        logger.warning(
            f"前置输入校验未通过: {state.get('error_message')}，直接流转至失败节点"
        )
        return "failure_node"
    return ["fetch_weather_node", "generate_search_strategy_node"]


def route_after_grounding_validation(state: TripPlannerState) -> str:
    """真实性校验后的条件路由决策

    - 校验通过 -> END
    - 校验未通过且 repair_count < 2 -> repair_skeleton_node
    - 校验未通过且 repair_count >= 2 -> failure_node
    """
    if state.get("validation_passed", False):
        logger.info("真实性校验完全通过，工作流正常交付！")
        return "end"

    repair_count = state.get("repair_count", 0)
    max_repairs = 2

    if repair_count < max_repairs:
        logger.warning(
            f"真实性校验未通过 (第 {repair_count} 次)，流转至 repair_skeleton_node 进行定向自愈修补"
        )
        return "repair_skeleton_node"
    else:
        logger.error(
            f"修补次数已达上限 ({repair_count}/{max_repairs}) 仍未通过校验，流转至 failure_node 显式终止"
        )
        return "failure_node"


def build_trip_planner_graph() -> StateGraph:
    """构建未编译的 StateGraph 图定义"""
    workflow = StateGraph(TripPlannerState)

    # 1. 注册所有节点
    workflow.add_node("normalize_and_validate_input", normalize_and_validate_input)
    workflow.add_node("fetch_weather_node", fetch_weather_node)
    workflow.add_node("generate_search_strategy_node", generate_search_strategy_node)
    workflow.add_node("search_attractions", search_attractions)
    workflow.add_node("search_hotels", search_hotels)
    workflow.add_node("search_restaurants", search_restaurants)
    workflow.add_node("curate_attractions_node", curate_attractions_node)
    workflow.add_node("synthesize_itinerary_node", synthesize_itinerary_node)
    workflow.add_node("rehydrate_entities_node", rehydrate_entities_node)
    workflow.add_node("enrich_routes_node", enrich_routes_node)
    workflow.add_node("calculate_budget_node", calculate_budget_node)
    workflow.add_node("validate_grounding_node", validate_grounding_node)
    workflow.add_node("repair_skeleton_node", repair_skeleton_node)
    workflow.add_node("failure_node", failure_node)

    # 2. 编排边与路由拓扑
    workflow.add_edge(START, "normalize_and_validate_input")

    # 输入校验后分支: 失败进 failure_node，成功扇出至 fetch_weather 与 generate_search_strategy
    workflow.add_conditional_edges(
        "normalize_and_validate_input",
        route_after_input_validation,
        [
            "failure_node",
            "fetch_weather_node",
            "generate_search_strategy_node",
        ],
    )

    # 搜索策略完成后扇出至三路独立检索
    workflow.add_edge("generate_search_strategy_node", "search_attractions")
    workflow.add_edge("generate_search_strategy_node", "search_hotels")
    workflow.add_edge("generate_search_strategy_node", "search_restaurants")

    # 三路检索汇聚至景点精选 (等待三路检索全部完成)
    workflow.add_edge(
        ["search_attractions", "search_hotels", "search_restaurants"],
        "curate_attractions_node",
    )

    # 景点精选与天气查询汇聚至多日行程合成 (等待精选与天气均就绪)
    workflow.add_edge(
        ["curate_attractions_node", "fetch_weather_node"],
        "synthesize_itinerary_node",
    )

    # 行程合成后进入确定性后处理流水线
    workflow.add_edge("synthesize_itinerary_node", "rehydrate_entities_node")
    workflow.add_edge("rehydrate_entities_node", "enrich_routes_node")
    workflow.add_edge("enrich_routes_node", "calculate_budget_node")
    workflow.add_edge("calculate_budget_node", "validate_grounding_node")

    # 校验结果条件路由
    workflow.add_conditional_edges(
        "validate_grounding_node",
        route_after_grounding_validation,
        {
            "end": END,
            "repair_skeleton_node": "repair_skeleton_node",
            "failure_node": "failure_node",
        },
    )

    # 自愈修补后重新进入实体还原后处理链路
    workflow.add_edge("repair_skeleton_node", "rehydrate_entities_node")

    # 失败节点连接至 END
    workflow.add_edge("failure_node", END)

    return workflow


# 全局单例编译图缓存
_compiled_graph: CompiledStateGraph = None


def get_trip_planner_graph() -> CompiledStateGraph:
    """获取或初始化编译后的旅行规划图单例"""
    global _compiled_graph
    if _compiled_graph is None:
        logger.info("初始化并编译 LangGraph 旅行规划工作流图...")
        builder = build_trip_planner_graph()
        _compiled_graph = builder.compile()
        logger.info("LangGraph 旅行规划工作流图编译就绪！")
    return _compiled_graph


def run_trip_planner_workflow(
    request: TripRequest, config: Dict[str, Any] = None
) -> TripPlannerState:
    """执行 LangGraph 旅行规划完整工作流

    Args:
        request: 前端传入的旅行需求模型
        config: 可选的执行配置 (如 thread_id)

    Returns:
        包含 final_plan 或 is_failed 诊断信息的全局状态
    """
    graph = get_trip_planner_graph()

    initial_state: TripPlannerState = {
        "request": request,
        "city": request.city,
        "start_date": request.start_date,
        "end_date": request.end_date,
        "travel_days": request.travel_days,
        "preferences": request.preferences or [],
        "transportation": request.transportation or "公共交通",
        "accommodation": request.accommodation or "经济型酒店",
        "free_text_input": request.free_text_input,
        "raw_weather": [],
        "candidate_attractions": {},
        "candidate_hotels": {},
        "candidate_restaurants": {},
        "selected_attraction_ids": [],
        "rehydrated_days": [],
        "validation_passed": False,
        "validation_errors": [],
        "warnings": [],
        "repair_count": 0,
        "is_failed": False,
        "error_message": None,
    }

    logger.info(
        f"启动 LangGraph 旅行规划工作流 | 城市: {request.city} | 天数: {request.travel_days} 天"
    )
    final_state = graph.invoke(initial_state, config=config)
    return final_state
