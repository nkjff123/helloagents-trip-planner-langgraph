"""LangGraph 旅行规划工作流提示词模板库

设计原则:
1. 实体隔离：LLM 仅负责语义决策与骨架编排，仅输出 poi_id 引用，严禁输出经纬度或伪造实体信息。
2. 约束显式化：严格约束候选范围、天数、游玩负荷与餐食搭配。
3. 结构化导向：针对每个推理节点量身定制高契合度 Prompt，配合 JSON Schema 输出。
"""

from typing import List, Dict, Any, Optional
from ..models.state import (
    TripPlannerState,
    AttractionCandidate,
    HotelCandidate,
    RestaurantCandidate,
    ItineraryDraftSkeleton,
)


# ============================================================================
# 1. 搜索策略规划 Prompt (generate_search_strategy_node)
# ============================================================================

SEARCH_STRATEGY_SYSTEM_PROMPT = """你是一名资深专业旅行规划顾问与高德地图检索策略专家。
你的任务是根据用户的旅行基础信息、偏好标签、自由诉求以及交通/住宿要求，制定一组精准高效的高德地图 POI 检索关键词。

【策略规划原则】
1. attraction_keywords (景点检索关键词):
   - 生成 2~4 个多样化、有针对性的关键词。
   - 兼顾城市标志性地标、自然风光或历史文化，并紧扣用户特征（如“亲子”、“古镇”、“夜景”、“博物馆”等）。
   - 不要包含省市名称（如检索“成都”，关键词应为“著名景区”或“大熊猫基地”，而非“成都市宽窄巷子”）。
2. hotel_keyword (住宿检索关键词):
   - 根据用户住宿档次偏好，提供 1 个具体的酒店搜索词（如“经济型酒店”、“高档豪华酒店”、“精品民宿”、“商务快捷酒店”）。
3. restaurant_keywords (美食餐饮检索关键词):
   - 生成 1~2 个具有当地城市特色的美食分类或商圈餐饮搜索词（如“川菜馆”、“当地特色小吃”、“老字号酒楼”）。
"""


def format_search_strategy_messages(state: TripPlannerState) -> List[Dict[str, str]]:
    """组装搜索策略生成的提示词消息列表"""
    city = state.get("city", "")
    travel_days = state.get("travel_days", 1)
    start_date = state.get("start_date", "")
    end_date = state.get("end_date", "")
    preferences = state.get("preferences", [])
    transportation = state.get("transportation", "公共交通")
    accommodation = state.get("accommodation", "经济舒适")
    free_text = state.get("free_text_input", "") or "无特殊额外要求"

    pref_str = "、".join(preferences) if preferences else "常态大众观光"

    user_content = (
        f"请为以下旅行需求制定高德地图检索策略：\n"
        f"- 目的地城市: {city}\n"
        f"- 出行日期: {start_date} 至 {end_date} (共 {travel_days} 天)\n"
        f"- 偏好风格: {pref_str}\n"
        f"- 意向交通: {transportation}\n"
        f"- 住宿档次: {accommodation}\n"
        f"- 补充特殊诉求: {free_text}\n\n"
        f"请按照定义的输出结构生成高效的检索策略（包含 attraction_keywords, hotel_keyword, restaurant_keywords）。"
    )

    return [
        {"role": "system", "content": SEARCH_STRATEGY_SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]


# ============================================================================
# 2. 景点候选初筛与精选 Prompt (curate_attractions_node)
# ============================================================================

CURATE_ATTRACTIONS_SYSTEM_PROMPT = """你是一名经验丰富的旅行行程策展人。
你的任务是从高德地图真实检索召回的景点候选池中，挑选出最值得游览、最符合用户偏好且游玩天数匹配的景点。

【初筛铁律】
1. 绝对实体锚定：你只能从候选池提供的列表里选择，且【必须且只能返回候选列表中的 poi_id】！
2. 严禁捏造任何候选池中不存在的 poi_id，严禁修改 poi_id 的任何字符。
3. 数量合理性：根据出行总天数进行筛选，通常每天安排 2~4 个景点，因此总筛选景点数量建议控制在 `天数 * 2` 到 `天数 * 3` 之间（最低不少于 `天数` 个）。
4. 综合品质：优先考虑评分高、与用户偏好契合度高、口碑优良的代表性景点。
"""


def format_curate_attractions_messages(state: TripPlannerState) -> List[Dict[str, str]]:
    """组装景点候选初筛精选提示词"""
    city = state.get("city", "")
    travel_days = state.get("travel_days", 1)
    preferences = state.get("preferences", [])
    free_text = state.get("free_text_input", "") or "无"
    candidates: Dict[str, AttractionCandidate] = state.get("candidate_attractions", {})

    pref_str = "、".join(preferences) if preferences else "常态大众观光"

    # 格式化候选列表
    cand_lines = []
    for idx, cand in enumerate(candidates.values(), 1):
        rating_str = f"评分: {cand.rating}" if cand.rating is not None else "暂无评分"
        price_str = f"门票: {cand.ticket_price}元" if cand.ticket_price is not None else "门票待查"
        cand_lines.append(
            f"{idx}. [ID: {cand.poi_id}] {cand.name} | 分类: {cand.type} | {rating_str} | {price_str} | 地址: {cand.address or '无详细地址'}"
        )
    candidates_text = "\n".join(cand_lines) if cand_lines else "暂无可用的景点候选数据"

    target_count_min = max(1, travel_days * 2)
    target_count_max = max(target_count_min, travel_days * 3 + 1)

    user_content = (
        f"旅行基本诉求：\n"
        f"- 目的地: {city}，行程天数: {travel_days} 天\n"
        f"- 偏好风格: {pref_str}\n"
        f"- 特殊诉求: {free_text}\n"
        f"- 期望精选景点数: 建议选出 {target_count_min}~{target_count_max} 个核心景点\n\n"
        f"以下是高德地图检索到的真实候选景点池（共 {len(candidates)} 个）：\n"
        f"{candidates_text}\n\n"
        f"请从中遴选最契合的景点，返回 selected_poi_ids（纯 POI ID 列表）以及简要遴选理由 reasoning。"
    )

    return [
        {"role": "system", "content": CURATE_ATTRACTIONS_SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]


# ============================================================================
# 3. 多日行程骨架合成 Prompt (synthesize_itinerary_node)
# ============================================================================

SYNTHESIZE_ITINERARY_SYSTEM_PROMPT = """你是一名资深旅行路线规划总监。
你的任务是将已经精选好的真实景点、真实酒店候选以及真实餐馆候选，结合天气情况合理编制为一份节奏舒适、逻辑严密的每日行程骨架 (ItineraryDraftSkeleton)。

【核心规划铁律】
1. 仅输出 POI ID 引用：
   - 每日景点 attraction_poi_ids: 必须全部来自精选候选景点的 poi_id 列表！
   - 当日酒店 hotel_poi_id: 必须来自候选酒店池的真实 poi_id（若无可用酒店可为 null）！
   - 当日餐馆 restaurant_poi_id: 午餐或晚餐尽量引用候选餐馆池中的真实 poi_id，或为 null！
   - 绝对禁止捏造不存在的 ID，不要输出经纬度坐标与官方地址（后续由系统自动从数据池 100% 精确还原）。
2. 天数严格契约：
   - days 列表的长度必须严格等于出行总天数 travel_days。
   - day_index 从 0 开始连续递增，date 必须与出行日期每一天严格对应。
3. 游览节奏与负荷控制：
   - 每天安排 2~4 个景点，避免单日负荷过重；地理位置相近的景点归入同一天游览。
   - 遇雨雪恶劣天气时，优先安排室内展馆或文化场馆。
4. 餐食完备性：
   - 每天必须规划早、中、晚三餐 (meals: breakfast, lunch, dinner)。
   - 早餐可推荐酒店早餐或周边早茶，午餐和晚餐推荐具有地方风味的特色名菜。
5. 行程总览与出行贴士：
   - overall_suggestions 需包含总体出行建议、穿衣防晒防雨提示及特色体验指南。
"""


def format_synthesize_itinerary_messages(state: TripPlannerState) -> List[Dict[str, str]]:
    """组装多日行程骨架合成提示词"""
    city = state.get("city", "")
    travel_days = state.get("travel_days", 1)
    start_date = state.get("start_date", "")
    end_date = state.get("end_date", "")
    preferences = state.get("preferences", [])
    transportation = state.get("transportation", "公共交通")
    accommodation = state.get("accommodation", "经济舒适")
    free_text = state.get("free_text_input", "") or "无"

    # 1. 精选景点列表
    selected_ids = set(state.get("selected_attraction_ids", []))
    candidates_attr = state.get("candidate_attractions", {})
    curated_attrs = [
        candidates_attr[pid] for pid in selected_ids if pid in candidates_attr
    ]
    # 若精选集合为空，则降级使用所有候选
    if not curated_attrs:
        curated_attrs = list(candidates_attr.values())[: travel_days * 3]

    attr_lines = []
    for a in curated_attrs:
        rating_str = f"评分: {a.rating}" if a.rating is not None else ""
        price_str = f"门票: {a.ticket_price}元" if a.ticket_price is not None else "免费/待查"
        attr_lines.append(
            f"- [景点 ID: {a.poi_id}] {a.name} ({a.type}, {rating_str}, {price_str}, 地址: {a.address})"
        )
    attr_text = "\n".join(attr_lines) if attr_lines else "（暂无精选景点候选）"

    # 2. 酒店候选列表
    cand_hotels = state.get("candidate_hotels", {})
    hotel_lines = []
    for h in list(cand_hotels.values())[:10]:
        cost_str = f"约 {h.estimated_cost}元/晚" if h.estimated_cost else "价格适中"
        hotel_lines.append(
            f"- [酒店 ID: {h.poi_id}] {h.name} ({h.type}, {cost_str}, 地址: {h.address})"
        )
    hotel_text = "\n".join(hotel_lines) if hotel_lines else "（暂无酒店候选）"

    # 3. 餐厅候选列表
    cand_rests = state.get("candidate_restaurants", {})
    rest_lines = []
    for r in list(cand_rests.values())[:15]:
        cost_str = f"人均约 {r.estimated_cost}元" if r.estimated_cost else "人均适中"
        rest_lines.append(
            f"- [餐厅 ID: {r.poi_id}] {r.name} ({r.cuisine}, {cost_str}, 地址: {r.address})"
        )
    rest_text = "\n".join(rest_lines) if rest_lines else "（暂无餐厅候选）"

    # 4. 天气信息
    weather_list = state.get("raw_weather", [])
    weather_lines = []
    for w in weather_list:
        wind_info = getattr(w, "wind_power", "") or getattr(w, "wind_direction", "")
        wind_str = f" | 风力: {wind_info}" if wind_info else ""
        weather_lines.append(
            f"- 日期: {w.date} | 天气: {w.day_weather}/{w.night_weather} | 气温: {w.night_temp}~{w.day_temp}℃{wind_str}"
        )
    weather_text = "\n".join(weather_lines) if weather_lines else "（未获取到实时预报，请按舒适晴好天气做参考）"

    user_content = (
        f"【旅行基础信息】\n"
        f"- 目的地: {city}\n"
        f"- 日期范围: {start_date} 至 {end_date} (严格 {travel_days} 天)\n"
        f"- 用户偏好: {'、'.join(preferences) if preferences else '综合观光'}\n"
        f"- 意向交通: {transportation}\n"
        f"- 意向住宿: {accommodation}\n"
        f"- 附加要求: {free_text}\n\n"
        f"【天气参考】\n"
        f"{weather_text}\n\n"
        f"【可用候选资源池】(所有 ID 必须从此范围选择)\n"
        f"1. 候选景点 (重点安排):\n{attr_text}\n\n"
        f"2. 候选酒店:\n{hotel_text}\n\n"
        f"3. 候选餐厅:\n{rest_text}\n\n"
        f"请严格按照天数编制每日 DayAssignment，并提供整体出行建议 overall_suggestions。"
    )

    return [
        {"role": "system", "content": SYNTHESIZE_ITINERARY_SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]


# ============================================================================
# 4. 骨架定向自愈修补 Prompt (repair_skeleton_node)
# ============================================================================

REPAIR_SKELETON_SYSTEM_PROMPT = """你是一名旅行规划质量与合规性修复专家。
上一轮生成的行程草案在真实性或完整性规则校验中未能通过，发现了若干具体错误。
你的任务是根据给出的【校验未通过错误列表】，对现有行程骨架进行定向修补，确保完全满足所有契约。

【修复铁律】
1. 错误对症下药：针对校验报告中的每一条错误（如天数不匹配、引用的 POI ID 不在候选池、缺失餐饮、单日无景点等）逐一纠正。
2. 保持合法部分：对原本合规的日程与安排尽量予以保留，仅对异常部分进行替换或补充。
3. 严格 ID 范围：所有替换或新加入的 attraction_poi_ids、hotel_poi_id、restaurant_poi_id 必须取自提供的合法候选池。
4. 绝不伪造：切勿捏造任何新 ID。
"""


def format_repair_skeleton_messages(
    state: TripPlannerState,
) -> List[Dict[str, str]]:
    """组装行程骨架修补提示词"""
    travel_days = state.get("travel_days", 1)
    errors = state.get("validation_errors", [])
    draft_skeleton = state.get("draft_skeleton")
    candidate_attractions = state.get("candidate_attractions", {})
    candidate_hotels = state.get("candidate_hotels", {})
    candidate_restaurants = state.get("candidate_restaurants", {})

    # 格式化可用候选 ID 清单供模型自愈参考
    valid_attr_ids = [
        f"{cand.poi_id} ({cand.name})" for cand in candidate_attractions.values()
    ]
    valid_hotel_ids = [
        f"{cand.poi_id} ({cand.name})" for cand in candidate_hotels.values()
    ]
    valid_rest_ids = [
        f"{cand.poi_id} ({cand.name})" for cand in candidate_restaurants.values()
    ]

    error_text = "\n".join([f"- {err}" for err in errors])
    skeleton_json = (
        draft_skeleton.model_dump_json(indent=2)
        if draft_skeleton
        else "{}"
    )

    user_content = (
        f"【修复任务背景】\n"
        f"- 预期行程总天数: {travel_days} 天\n\n"
        f"【上一轮校验发现的致命错误】\n"
        f"{error_text}\n\n"
        f"【上一次生成的草案骨架】\n"
        f"{skeleton_json}\n\n"
        f"【合法候选资源池】（修补时必须从以下列表中选取 ID，绝不可自行编造）：\n"
        f"- 合法景点 ID 列表: {', '.join(valid_attr_ids[:30])}\n"
        f"- 合法酒店 ID 列表: {', '.join(valid_hotel_ids[:10])}\n"
        f"- 合法餐厅 ID 列表: {', '.join(valid_rest_ids[:15])}\n\n"
        f"请针对上述错误进行精准修复，重新输出一份完全合规的 ItineraryDraftSkeleton！"
    )

    return [
        {"role": "system", "content": REPAIR_SKELETON_SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]
