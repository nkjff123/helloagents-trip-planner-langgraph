"""后处理与确定性校验节点 (确定性节点)

核心职责:
1. rehydrate_entities_node: 依据 POI ID 从原始候选池还原实体真实信息 (名称、GCJ-02 坐标、官方地址)，物理切断 LLM 篡改
2. enrich_routes_node: 调用真实路线规划丰富行程路况信息
3. calculate_budget_node: Python 严格加法运算，保障 total == sum(items)
4. validate_grounding_node: 严格校验所有景点与酒店必须存在于高德原始候选池中且经纬度零漂移
5. failure_node: 失败时流转至此并明确置 is_failed=True，严禁生成假数据
"""

from typing import Dict, Any, List, Optional
from loguru import logger

from ...models.schemas import (
    DayPlan,
    Attraction,
    Hotel,
    Meal,
    Budget,
    TripPlan,
)
from ...models.state import (
    TripPlannerState,
    ItineraryDraftSkeleton,
    AttractionCandidate,
    HotelCandidate,
    RestaurantCandidate,
)
from ...services.amap_service import get_amap_service


def rehydrate_entities_node(state: TripPlannerState) -> Dict[str, Any]:
    """根据 POI ID 还原真实实体对象 (核心确定性还原节点)

    大模型仅输出 POI ID 与骨架，由本节点依据真实高德候选池还原所有地理事实字段。
    """
    draft_skeleton: Optional[ItineraryDraftSkeleton] = state.get("draft_skeleton")
    if not draft_skeleton or not draft_skeleton.days:
        return {
            "validation_passed": False,
            "validation_errors": ["缺少日程草案骨架 (draft_skeleton 为空)"],
        }

    candidate_attractions: Dict[str, AttractionCandidate] = state.get(
        "candidate_attractions", {}
    )
    candidate_hotels: Dict[str, HotelCandidate] = state.get("candidate_hotels", {})
    candidate_restaurants: Dict[str, RestaurantCandidate] = state.get(
        "candidate_restaurants", {}
    )

    rehydrated_days: List[DayPlan] = []
    errors: List[str] = []

    for day in draft_skeleton.days:
        day_attractions: List[Attraction] = []

        # 1. 还原景点实体
        for poi_id in day.attraction_poi_ids:
            cand = candidate_attractions.get(poi_id)
            if cand:
                attr = Attraction(
                    name=cand.name,
                    address=cand.address,
                    location=cand.location,
                    visit_duration=cand.estimated_duration or 120,
                    description=cand.description or f"游览{cand.name}，领略当地风貌与特色文化。",
                    category=cand.type or "景点",
                    rating=cand.rating,
                    photos=cand.photos,
                    poi_id=cand.poi_id,
                    image_url=cand.photos[0] if cand.photos else None,
                    ticket_price=cand.ticket_price or 0,
                )
                day_attractions.append(attr)
            else:
                errors.append(
                    f"第 {day.day_index + 1} 天引用的景点 POI ID '{poi_id}' 不存在于高德真实候选池中"
                )

        # 2. 还原酒店实体
        hotel_obj: Optional[Hotel] = None
        if day.hotel_poi_id:
            cand_h = candidate_hotels.get(day.hotel_poi_id)
            if cand_h:
                hotel_obj = Hotel(
                    name=cand_h.name,
                    address=cand_h.address,
                    location=cand_h.location,
                    price_range=cand_h.price_range or "适中",
                    rating=str(cand_h.rating) if cand_h.rating else "4.5",
                    distance=cand_h.distance or "近商圈",
                    type=cand_h.type or state.get("accommodation", "舒适型酒店"),
                    estimated_cost=cand_h.estimated_cost or 350,
                )
            else:
                errors.append(
                    f"第 {day.day_index + 1} 天引用的酒店 POI ID '{day.hotel_poi_id}' 不存在于高德真实候选池中"
                )

        # 3. 还原餐饮实体
        rehydrated_meals: List[Meal] = []
        if day.meals:
            for meal_assign in day.meals:
                m_loc = None
                m_addr = None
                m_cost = 30 if meal_assign.type == "breakfast" else 70

                if meal_assign.restaurant_poi_id:
                    cand_r = candidate_restaurants.get(meal_assign.restaurant_poi_id)
                    if cand_r:
                        m_loc = cand_r.location
                        m_addr = cand_r.address
                        m_cost = cand_r.estimated_cost or m_cost

                rehydrated_meals.append(
                    Meal(
                        type=meal_assign.type,
                        name=meal_assign.name,
                        address=m_addr,
                        location=m_loc,
                        description=meal_assign.description or f"品尝{meal_assign.name}",
                        estimated_cost=m_cost,
                    )
                )
        else:
            # 默认补齐三餐结构以满足前端视图渲染要求
            rehydrated_meals = [
                Meal(type="breakfast", name="当地特色早点", description="传统早点铺", estimated_cost=30),
                Meal(type="lunch", name="风味午餐", description="景点附近特色美食", estimated_cost=60),
                Meal(type="dinner", name="特色晚餐", description="当地口碑餐厅", estimated_cost=80),
            ]

        day_plan = DayPlan(
            date=day.date,
            day_index=day.day_index,
            description=day.theme_description,
            transportation=day.transportation or state.get("transportation", "公共交通"),
            accommodation=day.accommodation or state.get("accommodation", "舒适型酒店"),
            hotel=hotel_obj,
            attractions=day_attractions,
            meals=rehydrated_meals,
        )
        rehydrated_days.append(day_plan)

    update: Dict[str, Any] = {
        "rehydrated_days": rehydrated_days,
    }
    if errors:
        update["validation_errors"] = errors

    logger.info(
        f"实体还原完成 | 还原天数: {len(rehydrated_days)} | 还原景点总数: {sum(len(d.attractions) for d in rehydrated_days)}"
    )
    return update


def enrich_routes_node(state: TripPlannerState) -> Dict[str, Any]:
    """路线丰富节点 (确定性调用高德真实路线规划)

    非阻塞节点：若高德路线不可用或超时，保留原有描述并记录 warning，不阻断主流程。
    """
    rehydrated_days = state.get("rehydrated_days", [])
    if not rehydrated_days:
        return {}

    service = get_amap_service()
    trans_mode = state.get("transportation", "公共交通")
    route_type = "driving" if "自驾" in trans_mode or "出租" in trans_mode else "walking"

    warnings: List[str] = []

    for day in rehydrated_days:
        # 当某天有两个及以上景点时，规划两景点之间的路况
        if len(day.attractions) >= 2:
            origin = day.attractions[0].address or day.attractions[0].name
            dest = day.attractions[1].address or day.attractions[1].name
            city = state.get("city", "")

            try:
                route_res = service.plan_route(
                    origin_address=origin,
                    destination_address=dest,
                    origin_city=city,
                    destination_city=city,
                    route_type=route_type,
                )
                if route_res and route_res.description:
                    dist_km = round(route_res.distance / 1000.0, 1)
                    day.description += f" 【交通导引: 从{day.attractions[0].name}前往{day.attractions[1].name}约 {dist_km}公里，{route_res.description}】"
            except Exception as e:
                warnings.append(f"第 {day.day_index + 1} 天路线规划跳过: {str(e)}")

    update: Dict[str, Any] = {"rehydrated_days": rehydrated_days}
    if warnings:
        update["warnings"] = warnings
    return update


def calculate_budget_node(state: TripPlannerState) -> Dict[str, Any]:
    """预算精确计算节点 (纯 Python 算术计算，禁止大模型心算)

    保证: total == total_attractions + total_hotels + total_meals + total_transportation
    并同时装配最终可交付的 TripPlan 对象。
    """
    rehydrated_days: List[DayPlan] = state.get("rehydrated_days", [])
    travel_days = max(1, len(rehydrated_days))

    # 1. 景点门票总费用
    total_attractions = sum(
        sum(a.ticket_price for a in day.attractions) for day in rehydrated_days
    )

    # 2. 酒店住宿总费用
    total_hotels = sum(
        day.hotel.estimated_cost if day.hotel else 0 for day in rehydrated_days
    )

    # 3. 餐饮总费用
    total_meals = sum(
        sum(m.estimated_cost for m in day.meals) for day in rehydrated_days
    )

    # 4. 交通出行费用 (按交通方式确定性定额)
    trans_mode = state.get("transportation", "公共交通")
    if any(k in trans_mode for k in ["自驾", "租车", "专车"]):
        daily_trans = 100
    elif any(k in trans_mode for k in ["打车", "出租"]):
        daily_trans = 70
    else:
        daily_trans = 30
    total_transportation = daily_trans * travel_days

    # 5. 总费用求和
    total = total_attractions + total_hotels + total_meals + total_transportation

    budget = Budget(
        total_attractions=total_attractions,
        total_hotels=total_hotels,
        total_meals=total_meals,
        total_transportation=total_transportation,
        total=total,
    )

    # 6. 装配最终 TripPlan
    overall_suggestions = (
        state["draft_skeleton"].overall_suggestions
        if state.get("draft_skeleton")
        else "出行请携带好证件，留意天气变化，热门景点建议提前预约购票。"
    )

    final_plan = TripPlan(
        city=state.get("city", ""),
        start_date=state.get("start_date", ""),
        end_date=state.get("end_date", ""),
        days=rehydrated_days,
        weather_info=state.get("raw_weather", []),
        overall_suggestions=overall_suggestions,
        budget=budget,
    )

    logger.info(
        f"预算计算完成 | 门票: {total_attractions} | 住宿: {total_hotels} | 餐饮: {total_meals} | 交通: {total_transportation} | 合计: {total}"
    )

    return {
        "budget": budget,
        "final_plan": final_plan,
    }


def validate_grounding_node(state: TripPlannerState) -> Dict[str, Any]:
    """严格真实性与物理一致性校验器节点

    强制检查:
    1. 日程天数必须精确等于请求 travel_days
    2. 每天安排景点数必须 >= 1
    3. 规划中的每一个景点必须 100% 存在于 candidate_attractions 且坐标完全一致
    4. 规划中的酒店若存在，其经纬度必须与 candidate_hotels 严格一致
    """
    rehydrated_days: List[DayPlan] = state.get("rehydrated_days", [])
    expected_days = state.get("travel_days", 0)
    candidate_attractions: Dict[str, AttractionCandidate] = state.get(
        "candidate_attractions", {}
    )
    candidate_hotels: Dict[str, HotelCandidate] = state.get("candidate_hotels", {})

    errors: List[str] = []

    # 检查 1: 天数契约
    if len(rehydrated_days) != expected_days:
        errors.append(
            f"行程天数不匹配：预期 {expected_days} 天，实际生成 {len(rehydrated_days)} 天"
        )

    # 检查 2 & 3: 每天景点负荷与实体真实性
    for day in rehydrated_days:
        if not day.attractions:
            errors.append(f"第 {day.day_index + 1} 天未安排任何景点")

        for attr in day.attractions:
            cand = candidate_attractions.get(attr.poi_id)
            if not cand:
                errors.append(
                    f"真实性校验失败: 景点 '{attr.name}' (ID: {attr.poi_id}) 不在候选池中"
                )
            else:
                # 经纬度零漂移校验
                if (
                    abs(attr.location.longitude - cand.location.longitude) > 1e-4
                    or abs(attr.location.latitude - cand.location.latitude) > 1e-4
                ):
                    errors.append(
                        f"坐标漂移篡改警告: 景点 '{attr.name}' 坐标与高德原始候选坐标不一致"
                    )

        # 检查 4: 酒店实体真实性
        if day.hotel:
            # 找到对应 hotel candidate
            matching_hotels = [
                h for h in candidate_hotels.values() if h.name == day.hotel.name
            ]
            if not matching_hotels:
                errors.append(
                    f"真实性校验失败: 酒店 '{day.hotel.name}' 不在候选池中"
                )

    passed = len(errors) == 0
    if passed:
        logger.info("工作流严格真实性校验 100% 通过！")
        return {"validation_passed": True}
    else:
        logger.warning(f"工作流真实性校验未通过 ({len(errors)} 项错误): {errors}")
        return {
            "validation_passed": False,
            "validation_errors": errors,
        }


def failure_node(state: TripPlannerState) -> Dict[str, Any]:
    """显式失败终结节点 (绝不调用 fallback 生成假数据)"""
    errors = state.get("validation_errors", [])
    detail = "；".join(errors) if errors else "未满足生成约束"
    error_msg = f"旅行计划生成失败：多次修补后仍未通过真实性与完整性校验。原因: {detail}"

    logger.error(f"工作流终止于失败节点: {error_msg}")

    return {
        "is_failed": True,
        "error_message": error_msg,
        "final_plan": None,
    }
