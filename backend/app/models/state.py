"""LangGraph 状态模型与候选领域模型定义"""

import operator
from typing import TypedDict, List, Dict, Any, Optional, Annotated
from pydantic import BaseModel, Field
from .schemas import (
    TripRequest,
    TripPlan,
    DayPlan,
    Attraction,
    Meal,
    Hotel,
    Budget,
    WeatherInfo,
    Location,
)


# ============ 真实候选实体模型 (无虚构默认值，真实数据与估算分离) ============

class AttractionCandidate(BaseModel):
    """真实景点候选数据 (从高德 MCP 获取并经过清洗)"""
    poi_id: str = Field(..., description="高德 POI 唯一标识")
    name: str = Field(..., description="景点官方名称")
    type: str = Field(default="景点", description="POI 分类类型")
    address: str = Field(default="", description="详细地址")
    location: Optional[Location] = Field(default=None, description="真实 GCJ-02 经纬度坐标 (可延迟按需补齐)")
    rating: Optional[float] = Field(default=None, description="官方评分 (无真实数据则为 None)")
    photos: List[str] = Field(default_factory=list, description="真实照片 URL 列表")
    ticket_price: Optional[int] = Field(default=None, description="官方门票价格 (元，无真实数据则为 None)")
    estimated_duration: Optional[int] = Field(default=None, description="建议游览时间 (分钟)")
    description: Optional[str] = Field(default=None, description="景点简介")
    tel: Optional[str] = Field(default=None, description="联系电话")


class HotelCandidate(BaseModel):
    """真实酒店候选数据"""
    poi_id: str = Field(..., description="高德 POI 唯一标识")
    name: str = Field(..., description="酒店官方名称")
    type: str = Field(default="酒店", description="酒店类型")
    address: str = Field(default="", description="酒店详细地址")
    location: Optional[Location] = Field(default=None, description="真实 GCJ-02 经纬度坐标 (可延迟按需补齐)")
    rating: Optional[str] = Field(default=None, description="用户评分 (无真实数据则为 None)")
    price_range: Optional[str] = Field(default=None, description="价格区间 (无真实数据则为 None)")
    estimated_cost: Optional[int] = Field(default=None, description="预估每晚费用 (元)")
    distance: Optional[str] = Field(default=None, description="距目标区域距离描述")


class RestaurantCandidate(BaseModel):
    """真实餐饮候选数据"""
    poi_id: str = Field(..., description="高德 POI 唯一标识")
    name: str = Field(..., description="餐厅官方名称")
    cuisine: str = Field(default="特色餐饮", description="菜系或美食类别")
    address: str = Field(default="", description="餐厅详细地址")
    location: Optional[Location] = Field(default=None, description="真实 GCJ-02 经纬度坐标 (可延迟按需补齐)")
    rating: Optional[float] = Field(default=None, description="官方评分 (无真实数据则为 None)")
    estimated_cost: Optional[int] = Field(default=None, description="人均消费预估 (元)")


# ============ LLM 推理输出协议 (仅决策与 ID 引用，严禁伪造实体数据) ============

class SearchStrategy(BaseModel):
    """LLM 规划的高德检索策略"""
    attraction_keywords: List[str] = Field(
        ...,
        description="针对用户偏好分解的景点搜索关键词列表 (2-4个)",
        min_length=1
    )
    hotel_keyword: str = Field(
        default="酒店",
        description="住宿搜索关键词 (如 '经济型酒店', '精品民宿')"
    )
    restaurant_keywords: List[str] = Field(
        default_factory=lambda: ["特色美食", "当地小吃"],
        description="餐饮搜索关键词列表 (1-2个)"
    )


class CuratedAttractions(BaseModel):
    """LLM 从候选池中精选的景点 ID 列表"""
    selected_poi_ids: List[str] = Field(
        ...,
        description="从候选池中选出的符合用户喜好和游玩天数的景点 POI ID 列表",
        min_length=1
    )
    reasoning: Optional[str] = Field(
        default=None,
        description="筛选理由与考量简述"
    )


class MealAssignment(BaseModel):
    """单餐规划决策"""
    type: str = Field(..., description="餐饮类型: breakfast, lunch, dinner, snack")
    name: str = Field(..., description="建议餐饮名称或风味特色")
    restaurant_poi_id: Optional[str] = Field(
        default=None,
        description="关联的真实餐馆 POI ID (若未匹配真实餐馆则为 None)"
    )
    description: Optional[str] = Field(default=None, description="就餐或菜品说明")
    estimated_cost: Optional[int] = Field(default=None, description="预估单人或整餐费用 (元)")


class DayAssignment(BaseModel):
    """单日行程决策骨架 (仅引用 POI ID，绝不包含自行编写的坐标与地址)"""
    day_index: int = Field(..., description="第几天 (0-based)")
    date: str = Field(..., description="对应日期 YYYY-MM-DD")
    theme_description: str = Field(..., description="当日主题与概览描述")
    transportation: Optional[str] = Field(default=None, description="当日建议交通方式")
    accommodation: Optional[str] = Field(default=None, description="当日住宿类型")
    attraction_poi_ids: List[str] = Field(
        ...,
        description="当日选中的景点 POI ID 列表 (仅 ID，后续由 Python 还原)",
        min_length=1
    )
    hotel_poi_id: Optional[str] = Field(
        default=None,
        description="当日入住酒店 POI ID (仅 ID)"
    )
    meals: List[MealAssignment] = Field(
        default_factory=list,
        description="当日早中晚餐安排"
    )


class ItineraryDraftSkeleton(BaseModel):
    """LLM 生成的行程骨架 (结构化决策产物)"""
    days: List[DayAssignment] = Field(..., description="每日行程分配列表")
    overall_suggestions: str = Field(..., description="整体出行建议、注意事项与装备建议")


# ============ LangGraph 全局状态定义 ============

class TripPlannerState(TypedDict, total=False):
    """LangGraph 旅行规划全局工作流状态"""

    # 1. 基础请求与归一化参数
    request: TripRequest
    city: str
    start_date: str
    end_date: str
    travel_days: int
    preferences: List[str]
    transportation: str
    accommodation: str
    free_text_input: Optional[str]

    # 2. 搜索策略
    strategy: Optional[SearchStrategy]

    # 3. 真实候选资源池 (由确定性 MCP 抓取，作为客观事实基准)
    raw_weather: List[WeatherInfo]
    candidate_attractions: Dict[str, AttractionCandidate]   # key: poi_id
    candidate_hotels: Dict[str, HotelCandidate]             # key: poi_id
    candidate_restaurants: Dict[str, RestaurantCandidate]   # key: poi_id

    # 4. LLM 语义决策中间体 (仅记录选中的 ID 与结构骨架)
    selected_attraction_ids: List[str]
    draft_skeleton: Optional[ItineraryDraftSkeleton]

    # 5. 还原后完整业务对象与物理计算 (纯 Python 处理)
    rehydrated_days: List[DayPlan]
    budget: Optional[Budget]
    final_plan: Optional[TripPlan]

    # 6. 工作流控制、度量与校验日志
    validation_passed: bool
    validation_errors: List[str]
    warnings: Annotated[List[str], operator.add]
    repair_count: int
    is_failed: bool
    error_message: Optional[str]
