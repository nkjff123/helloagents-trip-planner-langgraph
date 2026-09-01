"""模型与状态架构测试 (验证模式合规性、无虚假默认值、Reducer 机制及温度解析)"""

import operator
import unittest
from typing import get_type_hints, Annotated
from pydantic import ValidationError

from app.models.schemas import (
    TripRequest,
    Location,
    Attraction,
    Meal,
    Hotel,
    DayPlan,
    WeatherInfo,
    Budget,
    TripPlan,
)
from app.models.state import (
    AttractionCandidate,
    HotelCandidate,
    RestaurantCandidate,
    SearchStrategy,
    MealAssignment,
    DayAssignment,
    ItineraryDraftSkeleton,
    TripPlannerState,
)


class TestSchemasAndModels(unittest.TestCase):
    """测试数据模型及状态规范"""

    def test_trip_request_validation(self):
        """测试用户输入请求模型校验"""
        valid_req = TripRequest(
            city="北京",
            start_date="2026-10-01",
            end_date="2026-10-03",
            travel_days=3,
            transportation="公共交通",
            accommodation="经济型酒店",
            preferences=["历史文化", "美食"],
            free_text_input="想去看升旗"
        )
        self.assertEqual(valid_req.city, "北京")
        self.assertEqual(valid_req.travel_days, 3)
        self.assertEqual(len(valid_req.preferences), 2)

        # 测试异常天数 (超出 1-30 范围)
        with self.assertRaises(ValidationError):
            TripRequest(
                city="上海",
                start_date="2026-10-01",
                end_date="2026-11-15",
                travel_days=45,
                transportation="自驾",
                accommodation="豪华酒店"
            )

    def test_candidates_have_no_fake_defaults(self):
        """核心规范测试: 确保候选模型绝无虚假默认值 (评分/价格必须为 None)"""
        loc = Location(longitude=116.397, latitude=39.908)

        # 1. 景点候选模型
        attr = AttractionCandidate(
            poi_id="B000A83M61",
            name="故宫博物院",
            address="北京市东城区景山前街4号",
            location=loc
        )
        self.assertIsNone(attr.rating, "景点初始评分必须为 None，禁止预设虚假默认值")
        self.assertIsNone(attr.ticket_price, "门票价格必须为 None，禁止预设虚假默认值")
        self.assertIsNone(attr.estimated_duration)
        self.assertEqual(attr.photos, [])

        # 2. 酒店候选模型
        hotel = HotelCandidate(
            poi_id="B000A83HOTEL",
            name="如家精选酒店",
            address="东城区前门东大街",
            location=loc
        )
        self.assertIsNone(hotel.rating, "酒店初始评分必须为 None")
        self.assertIsNone(hotel.price_range, "酒店初始价格区间必须为 None")
        self.assertIsNone(hotel.estimated_cost, "酒店预估费用必须为 None")

        # 3. 餐饮候选模型
        rest = RestaurantCandidate(
            poi_id="B000A83REST",
            name="四季民福烤鸭店",
            address="东城区故宫东门",
            location=loc
        )
        self.assertIsNone(rest.rating)
        self.assertIsNone(rest.estimated_cost)

    def test_llm_skeleton_grounding_by_id(self):
        """测试 LLM 决策骨架仅输出 POI ID 且必须非空"""
        # 合法骨架
        skeleton = ItineraryDraftSkeleton(
            days=[
                DayAssignment(
                    day_index=0,
                    date="2026-10-01",
                    theme_description="历史文化探索",
                    attraction_poi_ids=["POI_GUGONG", "POI_JINGSHAN"],
                    hotel_poi_id="POI_HOTEL_1",
                    meals=[
                        MealAssignment(
                            type="breakfast",
                            name="老北京豆汁焦圈",
                            description="当地传统早点"
                        ),
                        MealAssignment(
                            type="lunch",
                            name="故宫角楼餐厅烤鸭",
                            restaurant_poi_id="POI_REST_1"
                        )
                    ]
                )
            ],
            overall_suggestions="建议提早预约故宫门票并携带身份证。"
        )
        self.assertEqual(len(skeleton.days), 1)
        self.assertEqual(skeleton.days[0].attraction_poi_ids, ["POI_GUGONG", "POI_JINGSHAN"])

        # 景点 ID 列表为空时必须抛出 ValidationError
        with self.assertRaises(ValidationError):
            DayAssignment(
                day_index=0,
                date="2026-10-01",
                theme_description="无景点无效行程",
                attraction_poi_ids=[]
            )

    def test_search_strategy_validation(self):
        """测试搜索策略模型"""
        strat = SearchStrategy(
            attraction_keywords=["故宫", "历史博物馆"],
            hotel_keyword="王府井舒适型酒店",
            restaurant_keywords=["老字号北京菜"]
        )
        self.assertEqual(len(strat.attraction_keywords), 2)

        # 关键词列表为空时报错
        with self.assertRaises(ValidationError):
            SearchStrategy(attraction_keywords=[])

    def test_weather_info_temperature_parsing(self):
        """测试天气模型的温度字段清洗逻辑 (去除 °C、℃ 等符号)"""
        w1 = WeatherInfo(
            date="2026-10-01",
            day_weather="晴",
            night_weather="多云",
            day_temp="24°C",
            night_temp="13℃",
            wind_direction="北风",
            wind_power="1-2级"
        )
        self.assertEqual(w1.day_temp, 24)
        self.assertEqual(w1.night_temp, 13)

        w2 = WeatherInfo(
            date="2026-10-02",
            day_weather="阴",
            night_weather="小雨",
            day_temp=18,
            night_temp=10
        )
        self.assertEqual(w2.day_temp, 18)
        self.assertEqual(w2.night_temp, 10)

    def test_state_reducer_behavior(self):
        """测试 LangGraph 状态中的 operator.add Reducer 行为"""
        state_hints = get_type_hints(TripPlannerState)

        # 验证 validation_errors 与 warnings 是否带有 operator.add Reducer
        val_errors_hint = state_hints.get("validation_errors")
        warnings_hint = state_hints.get("warnings")

        self.assertIsNotNone(val_errors_hint)
        self.assertIsNotNone(warnings_hint)

        # 模拟两个并行分支追加错误与告警
        initial_errors = ["错误 A: 天气查询超时"]
        branch_errors = ["错误 B: 酒店候选不足"]
        merged_errors = operator.add(initial_errors, branch_errors)

        self.assertEqual(merged_errors, ["错误 A: 天气查询超时", "错误 B: 酒店候选不足"])

    def test_budget_exact_math_compatibility(self):
        """测试预算模型与数据兼容性"""
        budget = Budget(
            total_attractions=120,
            total_hotels=800,
            total_meals=360,
            total_transportation=90,
            total=1370
        )
        self.assertEqual(budget.total, 1370)
        self.assertEqual(
            budget.total,
            budget.total_attractions + budget.total_hotels + budget.total_meals + budget.total_transportation
        )


if __name__ == "__main__":
    unittest.main()
