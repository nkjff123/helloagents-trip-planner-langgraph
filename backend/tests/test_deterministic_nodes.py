"""确定性节点单元测试 (输入清洗、实体按 ID 还原、严格候选池校验、精确预算算术与显式失败)"""

import unittest
from unittest.mock import patch, MagicMock
from app.models.schemas import Location, TripRequest, DayPlan, Attraction, Hotel, Meal
from app.models.state import (
    AttractionCandidate,
    HotelCandidate,
    RestaurantCandidate,
    DayAssignment,
    MealAssignment,
    ItineraryDraftSkeleton,
    TripPlannerState,
)
from app.workflow.nodes.input_nodes import (
    normalize_city_name,
    normalize_and_validate_input,
)
from app.workflow.nodes.postprocess_nodes import (
    rehydrate_entities_node,
    calculate_budget_node,
    validate_grounding_node,
    failure_node,
)


class TestDeterministicNodes(unittest.TestCase):
    """测试 LangGraph 确定性节点与后处理算子"""

    def setUp(self):
        """设置基准测试数据"""
        self.loc_gugong = Location(longitude=116.397026, latitude=39.918058)
        self.loc_jingshan = Location(longitude=116.399582, latitude=39.927233)
        self.loc_hotel = Location(longitude=116.417026, latitude=39.918058)

        self.candidate_attractions = {
            "POI_GUGONG": AttractionCandidate(
                poi_id="POI_GUGONG",
                name="故宫博物院",
                type="风景名胜",
                address="景山前街4号",
                location=self.loc_gugong,
                rating=4.9,
                photos=["https://example.com/gugong.jpg"],
                ticket_price=60,
            ),
            "POI_JINGSHAN": AttractionCandidate(
                poi_id="POI_JINGSHAN",
                name="景山公园",
                type="公园广场",
                address="景山西街44号",
                location=self.loc_jingshan,
                rating=4.7,
                photos=[],
                ticket_price=10,
            ),
        }

        self.candidate_hotels = {
            "HOTEL_1": HotelCandidate(
                poi_id="HOTEL_1",
                name="全季酒店(王府井店)",
                type="经济型酒店",
                address="王府井大街100号",
                location=self.loc_hotel,
                rating="4.8",
                estimated_cost=380,
            )
        }

        self.candidate_restaurants = {
            "REST_1": RestaurantCandidate(
                poi_id="REST_1",
                name="四季民福烤鸭店",
                cuisine="北京菜",
                address="故宫东华门旁",
                location=self.loc_gugong,
                rating=4.8,
                estimated_cost=120,
            )
        }

    def test_normalize_city_name(self):
        """测试城市名称规范化"""
        self.assertEqual(normalize_city_name("成都市"), "成都")
        self.assertEqual(normalize_city_name("北京市"), "北京")
        self.assertEqual(normalize_city_name(" 上海 "), "上海")
        self.assertEqual(normalize_city_name("吉林市"), "吉林")

    def test_input_normalization_and_validation_success(self):
        """测试合法输入的归一化与天数自动对齐"""
        req = TripRequest(
            city="成都市",
            start_date="2026-10-01",
            end_date="2026-10-03",
            travel_days=5,  # 填写了5天，但跨度为3天
            transportation="公共交通",
            accommodation="舒适型",
            preferences=["休闲"],
        )
        state: TripPlannerState = {"request": req}

        update = normalize_and_validate_input(state)
        self.assertEqual(update["city"], "成都")
        self.assertEqual(update["travel_days"], 3, "旅行天数必须与日期跨度强制一致")
        self.assertTrue(update["validation_passed"])
        self.assertFalse(update["is_failed"])
        self.assertTrue(len(update.get("warnings", [])) > 0)

    def test_input_normalization_date_error(self):
        """测试倒错日期的错误拦截"""
        req = TripRequest(
            city="西安市",
            start_date="2026-10-10",
            end_date="2026-10-05",  # 开始晚于结束
            travel_days=3,
            transportation="公共交通",
            accommodation="舒适型",
        )
        state: TripPlannerState = {"request": req}

        update = normalize_and_validate_input(state)
        self.assertFalse(update["validation_passed"])
        self.assertTrue(update["is_failed"])
        self.assertIn("不能晚于结束日期", update["validation_errors"][0])

    def test_rehydrate_entities_grounding_by_id(self):
        """测试基于 POI ID 还原真实实体，坐标与名称 100% 保持官方原样"""
        skeleton = ItineraryDraftSkeleton(
            days=[
                DayAssignment(
                    day_index=0,
                    date="2026-10-01",
                    theme_description="古都风华游",
                    attraction_poi_ids=["POI_GUGONG", "POI_JINGSHAN"],
                    hotel_poi_id="HOTEL_1",
                    meals=[
                        MealAssignment(
                            type="breakfast",
                            name="地道豆汁",
                            description="品尝老北京风味",
                        ),
                        MealAssignment(
                            type="lunch",
                            name="四季民福烤鸭",
                            restaurant_poi_id="REST_1",
                            description="品尝正宗烤鸭",
                        ),
                    ],
                )
            ],
            overall_suggestions="建议提早预约故宫门票。",
        )

        state: TripPlannerState = {
            "draft_skeleton": skeleton,
            "candidate_attractions": self.candidate_attractions,
            "candidate_hotels": self.candidate_hotels,
            "candidate_restaurants": self.candidate_restaurants,
            "transportation": "公共交通",
            "accommodation": "经济型酒店",
        }

        update = rehydrate_entities_node(state)
        rehydrated_days = update["rehydrated_days"]
        self.assertEqual(len(rehydrated_days), 1)

        day0: DayPlan = rehydrated_days[0]
        self.assertEqual(len(day0.attractions), 2)

        # 验证景点 1: 故宫
        gugong: Attraction = day0.attractions[0]
        self.assertEqual(gugong.name, "故宫博物院")
        self.assertEqual(gugong.poi_id, "POI_GUGONG")
        self.assertAlmostEqual(gugong.location.longitude, 116.397026)
        self.assertEqual(gugong.ticket_price, 60)

        # 验证酒店: 全季酒店
        self.assertIsNotNone(day0.hotel)
        self.assertEqual(day0.hotel.name, "全季酒店(王府井店)")
        self.assertEqual(day0.hotel.estimated_cost, 380)

        # 验证餐厅
        lunch = [m for m in day0.meals if m.type == "lunch"][0]
        self.assertEqual(lunch.name, "四季民福烤鸭")
        self.assertEqual(lunch.estimated_cost, 120)
        self.assertAlmostEqual(lunch.location.longitude, 116.397026)

    @patch("app.workflow.nodes.postprocess_nodes.get_amap_service")
    def test_rehydrate_entities_on_demand_location(self, mock_get_amap):
        """测试初筛无坐标候选在还原阶段触发按需调用补全坐标"""
        mock_amap = MagicMock()
        mock_amap.get_poi_detail.side_effect = lambda poi_id: {
            "id": poi_id,
            "name": "按需详情",
            "location": "114.016584,33.580456",
        }
        mock_get_amap.return_value = mock_amap

        cand_no_loc = AttractionCandidate(
            poi_id="POI_LUOHE_1",
            name="漯河开源森林公园",
            type="风景名胜",
            address="漯河市源汇区开源路",
            location=None,  # 初筛阶段无坐标
        )
        cand_hotel_no_loc = HotelCandidate(
            poi_id="HOTEL_LUOHE_1",
            name="漯河福朋喜来登酒店",
            type="高档型",
            address="漯河市郾城区淮河路",
            location=None,  # 初筛阶段无坐标
        )

        skeleton = ItineraryDraftSkeleton(
            days=[
                DayAssignment(
                    day_index=0,
                    date="2026-09-05",
                    theme_description="漯河一日游",
                    attraction_poi_ids=["POI_LUOHE_1"],
                    hotel_poi_id="HOTEL_LUOHE_1",
                    meals=[],
                )
            ],
            overall_suggestions="游玩建议",
        )

        state: TripPlannerState = {
            "city": "漯河",
            "draft_skeleton": skeleton,
            "candidate_attractions": {"POI_LUOHE_1": cand_no_loc},
            "candidate_hotels": {"HOTEL_LUOHE_1": cand_hotel_no_loc},
            "candidate_restaurants": {},
        }

        update = rehydrate_entities_node(state)
        self.assertNotIn("validation_errors", update)
        rehydrated_days = update["rehydrated_days"]
        self.assertEqual(len(rehydrated_days), 1)

        attr = rehydrated_days[0].attractions[0]
        self.assertIsNotNone(attr.location)
        self.assertAlmostEqual(attr.location.longitude, 114.016584)
        self.assertAlmostEqual(attr.location.latitude, 33.580456)

        hotel = rehydrated_days[0].hotel
        self.assertIsNotNone(hotel)
        self.assertIsNotNone(hotel.location)
        self.assertAlmostEqual(hotel.location.longitude, 114.016584)
        self.assertAlmostEqual(hotel.location.latitude, 33.580456)

    def test_rehydrate_entities_rejects_hallucinated_poi_id(self):
        """测试大模型捏造不存在的 POI ID 时被确定性捕获并记录错误"""
        skeleton = ItineraryDraftSkeleton(
            days=[
                DayAssignment(
                    day_index=0,
                    date="2026-10-01",
                    theme_description="虚构一日游",
                    attraction_poi_ids=["POI_NOT_EXIST_XYZ"],  # 幻觉 POI
                    hotel_poi_id="HOTEL_NOT_EXIST",  # 幻觉酒店
                )
            ],
            overall_suggestions="虚假建议",
        )

        state: TripPlannerState = {
            "draft_skeleton": skeleton,
            "candidate_attractions": self.candidate_attractions,
            "candidate_hotels": self.candidate_hotels,
            "candidate_restaurants": {},
        }

        update = rehydrate_entities_node(state)
        errors = update.get("validation_errors", [])
        self.assertTrue(len(errors) >= 2)
        self.assertTrue(any("POI_NOT_EXIST_XYZ" in e for e in errors))
        self.assertTrue(any("HOTEL_NOT_EXIST" in e for e in errors))

    def test_calculate_budget_exact_math(self):
        """测试预算数学加法确定性 (total == attractions + hotels + meals + transport)"""
        loc = Location(longitude=116.397, latitude=39.908)
        day_plan = DayPlan(
            date="2026-10-01",
            day_index=0,
            description="第1天游览",
            transportation="公共交通",
            accommodation="舒适型酒店",
            hotel=Hotel(
                name="全季酒店",
                address="东城区",
                location=loc,
                estimated_cost=400,
            ),
            attractions=[
                Attraction(
                    name="故宫",
                    address="景山前街4号",
                    location=loc,
                    visit_duration=120,
                    description="故宫游览",
                    ticket_price=60,
                ),
                Attraction(
                    name="景山",
                    address="景山西街44号",
                    location=loc,
                    visit_duration=60,
                    description="景山游览",
                    ticket_price=10,
                ),
            ],
            meals=[
                Meal(type="breakfast", name="早点", estimated_cost=30),
                Meal(type="lunch", name="午餐", estimated_cost=70),
                Meal(type="dinner", name="晚餐", estimated_cost=100),
            ],
        )

        state: TripPlannerState = {
            "city": "北京",
            "start_date": "2026-10-01",
            "end_date": "2026-10-01",
            "travel_days": 1,
            "transportation": "公共交通",
            "rehydrated_days": [day_plan],
            "raw_weather": [],
        }

        update = calculate_budget_node(state)
        budget = update["budget"]
        final_plan = update["final_plan"]

        # attractions: 60 + 10 = 70
        # hotels: 400
        # meals: 30 + 70 + 100 = 200
        # transportation: 公共交通 30 * 1 = 30
        # total = 70 + 400 + 200 + 30 = 700
        self.assertEqual(budget.total_attractions, 70)
        self.assertEqual(budget.total_hotels, 400)
        self.assertEqual(budget.total_meals, 200)
        self.assertEqual(budget.total_transportation, 30)
        self.assertEqual(budget.total, 700)
        self.assertEqual(
            budget.total,
            budget.total_attractions
            + budget.total_hotels
            + budget.total_meals
            + budget.total_transportation,
        )

        self.assertIsNotNone(final_plan)
        self.assertEqual(final_plan.city, "北京")
        self.assertEqual(len(final_plan.days), 1)

    def test_validate_grounding_detects_coordinate_drift(self):
        """核心规范测试: 严格真实性校验器检测出篡改的经纬度坐标"""
        # 故宫真实坐标为 116.397026, 39.918058
        tampered_loc = Location(longitude=116.499999, latitude=39.999999)  # 发生漂移
        tampered_attr = Attraction(
            name="故宫博物院",
            address="景山前街4号",
            location=tampered_loc,
            visit_duration=120,
            description="篡改后的故宫",
            poi_id="POI_GUGONG",
            ticket_price=60,
        )
        day_plan = DayPlan(
            date="2026-10-01",
            day_index=0,
            description="第1天",
            transportation="公共交通",
            accommodation="舒适型酒店",
            attractions=[tampered_attr],
            meals=[],
        )

        state: TripPlannerState = {
            "travel_days": 1,
            "rehydrated_days": [day_plan],
            "candidate_attractions": self.candidate_attractions,
            "candidate_hotels": self.candidate_hotels,
        }

        val_result = validate_grounding_node(state)
        self.assertFalse(val_result["validation_passed"])
        self.assertTrue(
            any("坐标漂移篡改警告" in e for e in val_result["validation_errors"])
        )

    def test_failure_node_sets_explicit_failure_without_fake_data(self):
        """核心规范测试: 修补重试耗尽后流转至 failure_node，返回 is_failed=True 且绝不生成假数据"""
        state: TripPlannerState = {
            "repair_count": 2,
            "validation_errors": ["景点 POI_A 不存在", "景点 POI_B 坐标漂移"],
        }

        result = failure_node(state)
        self.assertTrue(result["is_failed"])
        self.assertIsNone(result["final_plan"])
        self.assertIn("未通过真实性与完整性校验", result["error_message"])
        self.assertIn("POI_A", result["error_message"])


if __name__ == "__main__":
    unittest.main()
