"""输入参数归一化与校验节点 (确定性节点)

职责:
1. 提取并清洗请求参数 (去除城市名称后缀如'市'以增强高德检索命中率)
2. 校验日期格式与先后顺序，强制旅行天数与实际跨度对齐 (1-30天)
3. 初始化候选集合与工作流控制标记
"""

from datetime import datetime
from typing import Dict, Any, List
from loguru import logger

from ...models.schemas import TripRequest
from ...models.state import TripPlannerState


def normalize_city_name(city: str) -> str:
    """归一化城市名称，剥离后缀以提升高德 API 检索召回率"""
    cleaned = city.strip()
    # 当长度大于2且以'市'结尾时去除'市' (如 '成都市' -> '成都'，但保留 '吉林')
    if len(cleaned) > 2 and cleaned.endswith("市"):
        cleaned = cleaned[:-1]
    return cleaned


def normalize_and_validate_input(state: TripPlannerState) -> Dict[str, Any]:
    """输入归一化与前置校验节点

    Args:
        state: 当前工作流状态

    Returns:
        待合并入 State 的更新字典
    """
    errors: List[str] = []
    warnings: List[str] = []

    # 1. 提取基础参数 (支持从嵌套 request 或顶层直接提取)
    req: TripRequest = state.get("request")
    if req:
        city = req.city
        start_date = req.start_date
        end_date = req.end_date
        travel_days = req.travel_days
        transportation = req.transportation
        accommodation = req.accommodation
        preferences = req.preferences or []
        free_text_input = req.free_text_input or ""
    else:
        city = state.get("city", "")
        start_date = state.get("start_date", "")
        end_date = state.get("end_date", "")
        travel_days = state.get("travel_days", 0)
        transportation = state.get("transportation", "公共交通")
        accommodation = state.get("accommodation", "经济型酒店")
        preferences = state.get("preferences", [])
        free_text_input = state.get("free_text_input", "")

    # 2. 城市名称归一化
    normalized_city = normalize_city_name(city)
    if not normalized_city:
        errors.append("目的地城市不能为空")

    # 3. 日期格式与顺序校验
    start_dt = None
    end_dt = None
    try:
        start_dt = datetime.strptime(start_date, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        errors.append(f"开始日期格式无效: '{start_date}'，必须为 YYYY-MM-DD 格式")

    try:
        end_dt = datetime.strptime(end_date, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        errors.append(f"结束日期格式无效: '{end_date}'，必须为 YYYY-MM-DD 格式")

    calculated_days = travel_days
    if start_dt and end_dt:
        if start_dt > end_dt:
            errors.append(f"开始日期 ({start_date}) 不能晚于结束日期 ({end_date})")
        else:
            actual_span = (end_dt - start_dt).days + 1
            if actual_span > 30 or actual_span < 1:
                errors.append(f"旅行跨度必须在 1-30 天之间，当前计算为 {actual_span} 天")
            elif travel_days != actual_span:
                warnings.append(
                    f"填写的旅行天数 ({travel_days} 天) 与日期跨度 ({actual_span} 天) 不一致，已自动同步为 {actual_span} 天"
                )
                calculated_days = actual_span

    logger.info(
        f"输入校验完成 | 城市: {normalized_city} | 跨度: {calculated_days} 天 ({start_date} ~ {end_date})"
    )

    update: Dict[str, Any] = {
        "city": normalized_city,
        "start_date": start_date,
        "end_date": end_date,
        "travel_days": calculated_days,
        "transportation": transportation,
        "accommodation": accommodation,
        "preferences": preferences,
        "free_text_input": free_text_input,
        "raw_weather": state.get("raw_weather", []),
        "candidate_attractions": state.get("candidate_attractions", {}),
        "candidate_hotels": state.get("candidate_hotels", {}),
        "candidate_restaurants": state.get("candidate_restaurants", {}),
        "selected_attraction_ids": state.get("selected_attraction_ids", []),
        "rehydrated_days": state.get("rehydrated_days", []),
        "validation_passed": len(errors) == 0,
        "repair_count": state.get("repair_count", 0),
        "is_failed": len(errors) > 0,
        "error_message": "；".join(errors) if errors else None,
    }

    if errors:
        update["validation_errors"] = errors
    if warnings:
        update["warnings"] = warnings

    return update
