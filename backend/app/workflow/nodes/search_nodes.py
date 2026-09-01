"""检索与天气确定性数据获取节点 (Deterministic Search & Weather Nodes)

核心设计:
1. fetch_weather_node: 独立并行天气节点，遵循天气透明策略 (Transparent Weather Policy)，服务不可用时返回空并记录 warning，绝不生成假天气。
2. search_attractions / search_hotels / search_restaurants: 三路解耦并行检索节点，从高德 MCP 检索真实 POI 候选并结构化为 Dict[poi_id, Candidate]。
"""

from typing import Dict, Any, List
from loguru import logger

from ...models.schemas import WeatherInfo
from ...models.state import (
    TripPlannerState,
    AttractionCandidate,
    HotelCandidate,
    RestaurantCandidate,
    SearchStrategy,
)
from ...services.amap_service import get_amap_service


def fetch_weather_node(state: TripPlannerState) -> Dict[str, Any]:
    """查询真实城市天气预报 (独立并行节点)

    遵循天气透明原则：若服务不可用则返回空列表并追加 warning，严禁生成虚假晴雨数据。
    """
    city = state.get("city", "")
    amap_service = get_amap_service()

    logger.info(f"天气节点开始查询城市天气: {city}")
    try:
        weather_list = amap_service.get_weather(city)
        if weather_list:
            logger.info(f"成功获取城市 '{city}' {len(weather_list)} 天天气预报")
            return {"raw_weather": weather_list}
        else:
            msg = f"高德天气服务未返回城市 '{city}' 的预报数据，前端将透明隐藏天气组件"
            logger.warning(msg)
            return {
                "raw_weather": [],
                "warnings": [msg],
            }
    except Exception as e:
        msg = f"天气查询出现异常: {str(e)}"
        logger.error(msg)
        return {
            "raw_weather": [],
            "warnings": [msg],
        }


def search_attractions(state: TripPlannerState) -> Dict[str, Any]:
    """根据搜索策略并发检索景点候选池 (确定性节点)"""
    city = state.get("city", "")
    strategy: SearchStrategy = state.get("strategy")
    amap_service = get_amap_service()

    keywords: List[str] = []
    if strategy and strategy.attraction_keywords:
        keywords = strategy.attraction_keywords
    else:
        keywords = ["著名景区", "文化古迹"]

    logger.info(f"开始检索景点候选池 (城市: {city}, 关键词: {keywords})")
    candidates_map: Dict[str, AttractionCandidate] = {}

    for kw in keywords:
        try:
            items = amap_service.search_attraction_candidates(keywords=kw, city=city)
            for item in items:
                if item.poi_id not in candidates_map:
                    candidates_map[item.poi_id] = item
        except Exception as e:
            logger.error(f"关键词 '{kw}' 检索景点失败: {str(e)}")

    logger.info(f"景点检索完成，共汇总去重得到 {len(candidates_map)} 个真实候选景点")
    return {"candidate_attractions": candidates_map}


def search_hotels(state: TripPlannerState) -> Dict[str, Any]:
    """根据搜索策略并发检索酒店候选池 (确定性节点)"""
    city = state.get("city", "")
    strategy: SearchStrategy = state.get("strategy")
    amap_service = get_amap_service()

    hotel_kw = strategy.hotel_keyword if strategy and strategy.hotel_keyword else "酒店"

    logger.info(f"开始检索酒店候选池 (城市: {city}, 关键词: {hotel_kw})")
    candidates_map: Dict[str, HotelCandidate] = {}

    try:
        items = amap_service.search_hotel_candidates(keywords=hotel_kw, city=city)
        for item in items:
            if item.poi_id not in candidates_map:
                candidates_map[item.poi_id] = item
    except Exception as e:
        logger.error(f"检索酒店候选失败: {str(e)}")

    logger.info(f"酒店检索完成，共汇总去重得到 {len(candidates_map)} 个真实候选酒店")
    return {"candidate_hotels": candidates_map}


def search_restaurants(state: TripPlannerState) -> Dict[str, Any]:
    """根据搜索策略并发检索餐饮候选池 (真实餐饮检索接入，拒绝凭空捏造)"""
    city = state.get("city", "")
    strategy: SearchStrategy = state.get("strategy")
    amap_service = get_amap_service()

    keywords: List[str] = []
    if strategy and strategy.restaurant_keywords:
        keywords = strategy.restaurant_keywords
    else:
        keywords = ["特色美食", "当地小吃"]

    logger.info(f"开始检索特色餐饮候选池 (城市: {city}, 关键词: {keywords})")
    candidates_map: Dict[str, RestaurantCandidate] = {}

    for kw in keywords:
        try:
            items = amap_service.search_restaurant_candidates(keywords=kw, city=city)
            for item in items:
                if item.poi_id not in candidates_map:
                    candidates_map[item.poi_id] = item
        except Exception as e:
            logger.error(f"关键词 '{kw}' 检索餐饮失败: {str(e)}")

    logger.info(f"餐饮检索完成，共汇总去重得到 {len(candidates_map)} 个真实候选餐厅")
    return {"candidate_restaurants": candidates_map}
