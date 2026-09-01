"""LLM 推理节点模块 (LLM Reasoning Nodes)

核心设计:
1. generate_search_strategy_node: 依据用户偏好与自由诉求生成高德检索策略 (SearchStrategy)
2. curate_attractions_node: 从候选池精选最匹配的景点，严格返回 poi_id 列表，并执行严格候选池存在性校验
3. synthesize_itinerary_node: 综合天气、地理就近、候选酒店及餐饮生成行程骨架 (ItineraryDraftSkeleton)
4. repair_skeleton_node: 针对校验失败项定向修补骨架，修补计数器累加
"""

from typing import Dict, Any, List
from loguru import logger

from ...models.state import (
    TripPlannerState,
    SearchStrategy,
    CuratedAttractions,
    ItineraryDraftSkeleton,
    AttractionCandidate,
)
from ...services.llm_service import generate_structured
from ..prompts import (
    format_search_strategy_messages,
    format_curate_attractions_messages,
    format_synthesize_itinerary_messages,
    format_repair_skeleton_messages,
)


def generate_search_strategy_node(state: TripPlannerState) -> Dict[str, Any]:
    """规划高德地图搜索策略 (LLM 推理节点)"""
    city = state.get("city", "")
    logger.info(f"开始为城市 '{city}' 生成高德地图搜索策略...")

    messages = format_search_strategy_messages(state)
    try:
        strategy: SearchStrategy = generate_structured(
            schema=SearchStrategy,
            messages=messages,
            temperature=0.3,
            max_retries=2,
        )
        logger.info(
            f"搜索策略规划成功: 景点关键词={strategy.attraction_keywords}, 酒店={strategy.hotel_keyword}, 美食={strategy.restaurant_keywords}"
        )
        return {"strategy": strategy}
    except Exception as e:
        logger.error(f"生成搜索策略失败，使用兜底策略: {str(e)}")
        # 降级兜底策略
        fallback_strategy = SearchStrategy(
            attraction_keywords=["热门景点", "著名景区", "文化古迹"],
            hotel_keyword=state.get("accommodation", "舒适型酒店") or "酒店",
            restaurant_keywords=["特色美食", "当地小吃"],
        )
        return {
            "strategy": fallback_strategy,
            "warnings": [f"搜索策略大模型生成受阻，已启用系统兜底检索策略: {str(e)}"],
        }


def curate_attractions_node(state: TripPlannerState) -> Dict[str, Any]:
    """从高德候选池中精选景点 (LLM 初筛与排序节点)

    严格执行实体锚定：LLM 仅输出选中的 poi_id 列表，并强制过滤剔除任何不存在的伪造 ID。
    """
    city = state.get("city", "")
    candidates: Dict[str, AttractionCandidate] = state.get("candidate_attractions", {})
    travel_days = state.get("travel_days", 1)

    if not candidates:
        logger.warning(f"城市 '{city}' 候选景点池为空，无法执行精选")
        return {
            "selected_attraction_ids": [],
            "warnings": [f"未检索到城市 '{city}' 的任何候选景点"],
        }

    logger.info(f"开始从 {len(candidates)} 个候选景点中初筛精选...")
    messages = format_curate_attractions_messages(state)

    try:
        curated: CuratedAttractions = generate_structured(
            schema=CuratedAttractions,
            messages=messages,
            temperature=0.2,
            max_retries=2,
        )
        raw_ids = curated.selected_poi_ids
    except Exception as e:
        logger.error(f"景点精选模型调用失败，降级按评分及顺序选取: {str(e)}")
        raw_ids = list(candidates.keys())

    # 严格候选池存在性校验与过滤（物理杜绝虚构 ID）
    valid_selected_ids: List[str] = [pid for pid in raw_ids if pid in candidates]

    # 保障最低需求量：若筛选后有效景点数量偏少，从候选池中自动补足
    min_required = max(1, travel_days * 2)
    if len(valid_selected_ids) < min_required:
        for pid in candidates.keys():
            if pid not in valid_selected_ids:
                valid_selected_ids.append(pid)
            if len(valid_selected_ids) >= min_required:
                break

    logger.info(
        f"景点初筛精选完成，最终锁定 {len(valid_selected_ids)} 个真实候选景点 ID"
    )
    return {"selected_attraction_ids": valid_selected_ids}


def synthesize_itinerary_node(state: TripPlannerState) -> Dict[str, Any]:
    """合成多日行程决策骨架 (LLM 行程编排节点)

    生成包含每日 POI ID 分配、酒店 ID、餐馆安排与出行建议的 ItineraryDraftSkeleton。
    """
    city = state.get("city", "")
    travel_days = state.get("travel_days", 1)
    logger.info(f"开始合成 {city} {travel_days} 日行程骨架...")

    messages = format_synthesize_itinerary_messages(state)
    try:
        skeleton: ItineraryDraftSkeleton = generate_structured(
            schema=ItineraryDraftSkeleton,
            messages=messages,
            temperature=0.3,
            max_retries=2,
        )
        logger.info(f"行程骨架合成成功，共规划 {len(skeleton.days)} 天日程")
        return {"draft_skeleton": skeleton}
    except Exception as e:
        logger.error(f"合成行程骨架失败: {str(e)}")
        raise e


def repair_skeleton_node(state: TripPlannerState) -> Dict[str, Any]:
    """定向修复行程骨架 (LLM 自愈修补节点)

    针对前置节点汇报的 validation_errors 进行定向纠正，并将 repair_count 递增。
    """
    repair_count = state.get("repair_count", 0) + 1
    errors = state.get("validation_errors", [])
    logger.warning(
        f"进入骨架修复节点 (第 {repair_count} 次修复)，待解决错误: {errors}"
    )

    messages = format_repair_skeleton_messages(state)
    try:
        repaired_skeleton: ItineraryDraftSkeleton = generate_structured(
            schema=ItineraryDraftSkeleton,
            messages=messages,
            temperature=0.1,  # 修复时使用极低温度确保严格修正
            max_retries=2,
        )
        logger.info(f"第 {repair_count} 次骨架修复成功完成")
        return {
            "draft_skeleton": repaired_skeleton,
            "repair_count": repair_count,
        }
    except Exception as e:
        logger.error(f"第 {repair_count} 次骨架修复执行失败: {str(e)}")
        return {
            "repair_count": repair_count,
            "warnings": [f"骨架修补模型调用异常: {str(e)}"],
        }
