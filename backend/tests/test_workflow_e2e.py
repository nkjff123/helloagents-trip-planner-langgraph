"""端到端状态图测试 (test_workflow_e2e)

测试范围:
1. test_graph_compilation: 验证 StateGraph 结构合法性与正常编译
2. test_workflow_input_validation_failure_route: 输入参数校验失败直接路由至 failure_node
3. test_workflow_successful_e2e_execution: 完整多路并行与后处理成功交付闭环
4. test_workflow_repair_loop_e2e: 模拟首次校验失败触发自愈修补后重试成功
5. test_workflow_failure_when_repair_exhausted: 校验修补超限后显式失败终结（彻底杜绝假数据）
"""

import unittest
from unittest.mock import patch, MagicMock

from app.models.schemas import (
    TripRequest,
    Location,
    WeatherInfo,
    DayPlan,
    Attraction,
)
from app.models.state import (
    SearchStrategy,
    CuratedAttractions,
    ItineraryDraftSkeleton,
    DayAssignment,
    MealAssignment,
    AttractionCandidate,
    HotelCandidate,
    RestaurantCandidate,
)
from app.workflow.graph import (
    build_trip_planner_graph,
    run_trip_planner_workflow,
)


class TestWorkflowE2E(unittest.TestCase):
    """LangGraph 旅行规划端到端集成测试"""

    def setUp(self):
        # 预设候选数据池
        self.mock_attr_1 = AttractionCandidate(
            poi_id="POI_WEST_LAKE",
            name="西湖风景区",
            type="名胜古迹",
            address="杭州市西湖区南山路",
            location=Location(longitude=120.14, latitude=30.24),
            rating=4.9,
            ticket_price=0,
        )
        self.mock_attr_2 = AttractionCandidate(
            poi_id="POI_LINGYIN",
            name="灵隐寺",
            type="佛教寺庙",
            address="杭州市西湖区法云弄1号",
            location=Location(longitude=120.10, latitude=30.23),
            rating=4.8,
            ticket_price=45,
        )
        self.mock_hotel = HotelCandidate(
            poi_id="HOTEL_WEST_LAKE",
            name="西湖晴澜酒店",
            type="高档型",
            address="杭州市西湖区北山路",
            location=Location(longitude=120.15, latitude=30.25),
            estimated_cost=400,
        )
        self.mock_rest_1 = RestaurantCandidate(
            poi_id="REST_LOUWAILOU",
            name="楼外楼",
            cuisine="杭帮菜",
            address="杭州市孤山路30号",
            location=Location(longitude=120.14, latitude=30.25),
            estimated_cost=150,
        )
        self.mock_rest_2 = RestaurantCandidate(
            poi_id="REST_ZHIWEIGUAN",
            name="知味观",
            cuisine="特色小吃",
            address="杭州市仁和路83号",
            location=Location(longitude=120.16, latitude=30.25),
            estimated_cost=80,
        )

    def test_graph_compilation(self):
        """测试图结构定义合法并能成功编译"""
        graph = build_trip_planner_graph().compile()
        self.assertIsNotNone(graph)

    def test_workflow_input_validation_failure_route(self):
        """测试前置参数校验失败时，直接路由至 failure_node 并显式拒绝"""
        invalid_request = TripRequest(
            city="",  # 城市为空
            start_date="2026-10-05",
            end_date="2026-10-01",  # 日期倒挂
            travel_days=5,
            transportation="公共交通",
            accommodation="经济型酒店",
        )

        final_state = run_trip_planner_workflow(invalid_request)
        self.assertTrue(final_state.get("is_failed"))
        self.assertFalse(final_state.get("validation_passed"))
        self.assertIsNone(final_state.get("final_plan"))
        self.assertIn("不能为空", final_state.get("error_message", ""))

    @patch("app.workflow.nodes.reasoning_nodes.generate_structured")
    @patch("app.workflow.nodes.search_nodes.get_amap_service")
    def test_workflow_successful_e2e_execution(
        self, mock_get_amap, mock_generate_structured
    ):
        """测试完整工作流成功执行闭环"""
        # 1. Mock 高德服务
        mock_amap = MagicMock()
        mock_amap.get_weather.return_value = [
            WeatherInfo(
                date="2026-10-01",
                day_weather="晴",
                night_weather="多云",
                day_temp="25",
                night_temp="18",
            )
        ]
        mock_amap.search_attraction_candidates.return_value = [
            self.mock_attr_1,
            self.mock_attr_2,
        ]
        mock_amap.search_hotel_candidates.return_value = [self.mock_hotel]
        mock_amap.search_restaurant_candidates.return_value = [
            self.mock_rest_1,
            self.mock_rest_2,
        ]
        mock_amap.plan_route.return_value = None  # 路线丰富降级为默认
        mock_get_amap.return_value = mock_amap

        # 2. Mock 大模型推理
        mock_strategy = SearchStrategy(
            attraction_keywords=["西湖景区", "灵隐寺"],
            hotel_keyword="高档型酒店",
            restaurant_keywords=["杭帮菜"],
        )
        mock_curation = CuratedAttractions(
            selected_poi_ids=["POI_WEST_LAKE", "POI_LINGYIN"],
            reasoning="精选西湖与灵隐寺",
        )
        mock_skeleton = ItineraryDraftSkeleton(
            days=[
                DayAssignment(
                    day_index=0,
                    date="2026-10-01",
                    theme_description="西湖灵隐禅韵一日游",
                    attraction_poi_ids=["POI_WEST_LAKE", "POI_LINGYIN"],
                    hotel_poi_id="HOTEL_WEST_LAKE",
                    meals=[
                        MealAssignment(type="breakfast", name="酒店早茶"),
                        MealAssignment(
                            type="lunch",
                            name="楼外楼午宴",
                            restaurant_poi_id="REST_LOUWAILOU",
                        ),
                        MealAssignment(
                            type="dinner",
                            name="知味观小吃",
                            restaurant_poi_id="REST_ZHIWEIGUAN",
                        ),
                    ],
                )
            ],
            overall_suggestions="建议轻装便行。",
        )

        mock_generate_structured.side_effect = [
            mock_strategy,  # generate_search_strategy_node
            mock_curation,  # curate_attractions_node
            mock_skeleton,  # synthesize_itinerary_node
        ]

        valid_request = TripRequest(
            city="杭州市",  # 测试去缀归一化
            start_date="2026-10-01",
            end_date="2026-10-01",
            travel_days=1,
            preferences=["自然风光"],
            transportation="公共交通",
            accommodation="高档型",
            free_text_input="想多品尝本地美食",
        )

        final_state = run_trip_planner_workflow(valid_request)

        # 验证工作流成功
        self.assertTrue(final_state.get("validation_passed"))
        self.assertFalse(final_state.get("is_failed"))
        self.assertIsNotNone(final_state.get("final_plan"))

        plan = final_state["final_plan"]
        self.assertEqual(plan.city, "杭州")  # 验证城市已归一化
        self.assertEqual(len(plan.days), 1)

        day1 = plan.days[0]
        self.assertEqual(len(day1.attractions), 2)
        # 验证实体已 100% 真实还原且坐标精确匹配
        self.assertEqual(day1.attractions[0].name, "西湖风景区")
        self.assertEqual(day1.attractions[0].location.longitude, 120.14)
        self.assertIsNotNone(day1.hotel)
        self.assertEqual(day1.hotel.name, "西湖晴澜酒店")

        # 验证预算经过精准数学计算
        self.assertIsNotNone(plan.budget)
        self.assertEqual(
            plan.budget.total,
            plan.budget.total_attractions
            + plan.budget.total_hotels
            + plan.budget.total_meals
            + plan.budget.total_transportation,
        )

    @patch("app.workflow.nodes.reasoning_nodes.generate_structured")
    @patch("app.workflow.nodes.search_nodes.get_amap_service")
    def test_workflow_repair_loop_e2e(self, mock_get_amap, mock_generate_structured):
        """测试首次校验失败（如引用未识别的假 POI），自愈修补循环成功修复"""
        mock_amap = MagicMock()
        mock_amap.get_weather.return_value = []
        mock_amap.search_attraction_candidates.return_value = [
            self.mock_attr_1,
            self.mock_attr_2,
        ]
        mock_amap.search_hotel_candidates.return_value = [self.mock_hotel]
        mock_amap.search_restaurant_candidates.return_value = [self.mock_rest_1]
        mock_amap.plan_route.return_value = None
        mock_get_amap.return_value = mock_amap

        mock_strategy = SearchStrategy(
            attraction_keywords=["西湖"],
            hotel_keyword="酒店",
            restaurant_keywords=["特色菜"],
        )
        mock_curation = CuratedAttractions(
            selected_poi_ids=["POI_WEST_LAKE"],
            reasoning="西湖",
        )

        # 首次生成：骨架引用的景点列表为空或缺失景点
        flawed_skeleton = ItineraryDraftSkeleton(
            days=[
                DayAssignment(
                    day_index=0,
                    date="2026-10-01",
                    theme_description="有缺陷的行程",
                    attraction_poi_ids=["UNKNOWN_FAKE_ID"],  # 假 ID 将导致真实还原失败
                    meals=[],
                )
            ],
            overall_suggestions="待完善",
        )

        # 修复后的合规骨架
        fixed_skeleton = ItineraryDraftSkeleton(
            days=[
                DayAssignment(
                    day_index=0,
                    date="2026-10-01",
                    theme_description="已修复行程",
                    attraction_poi_ids=["POI_WEST_LAKE"],  # 修复为合法真实 ID
                    meals=[
                        MealAssignment(type="breakfast", name="早茶"),
                        MealAssignment(type="lunch", name="午餐"),
                        MealAssignment(type="dinner", name="晚餐"),
                    ],
                )
            ],
            overall_suggestions="修复完毕",
        )

        mock_generate_structured.side_effect = [
            mock_strategy,  # generate_search_strategy_node
            mock_curation,  # curate_attractions_node
            flawed_skeleton,  # synthesize_itinerary_node (出错)
            fixed_skeleton,  # repair_skeleton_node (修复成功)
        ]

        req = TripRequest(
            city="杭州",
            start_date="2026-10-01",
            end_date="2026-10-01",
            travel_days=1,
            transportation="公共交通",
            accommodation="经济型酒店",
        )

        final_state = run_trip_planner_workflow(req)
        # 验证经历了一次修复且最终通过
        self.assertEqual(final_state.get("repair_count"), 1)
        self.assertTrue(final_state.get("validation_passed"))
        self.assertFalse(final_state.get("is_failed"))
        self.assertIsNotNone(final_state.get("final_plan"))

    @patch("app.workflow.nodes.reasoning_nodes.generate_structured")
    @patch("app.workflow.nodes.search_nodes.get_amap_service")
    def test_workflow_failure_when_repair_exhausted(
        self, mock_get_amap, mock_generate_structured
    ):
        """测试修补达到上限 (>=2) 仍不符合规则时，显式终止于 failure_node，绝不使用 fallback 假数据"""
        mock_amap = MagicMock()
        mock_amap.get_weather.return_value = []
        mock_amap.search_attraction_candidates.return_value = [self.mock_attr_1]
        mock_amap.search_hotel_candidates.return_value = []
        mock_amap.search_restaurant_candidates.return_value = []
        mock_amap.plan_route.return_value = None
        mock_get_amap.return_value = mock_amap

        mock_strategy = SearchStrategy(
            attraction_keywords=["西湖"],
            hotel_keyword="酒店",
            restaurant_keywords=["特色菜"],
        )
        mock_curation = CuratedAttractions(
            selected_poi_ids=["POI_WEST_LAKE"],
            reasoning="西湖",
        )

        # 始终返回存在假 ID 的顽固错误骨架
        persistent_flawed_skeleton = ItineraryDraftSkeleton(
            days=[
                DayAssignment(
                    day_index=0,
                    date="2026-10-01",
                    theme_description="持续存在伪造 ID 的骨架",
                    attraction_poi_ids=["ALWAYS_FAKE_ID_999"],
                    meals=[],
                )
            ],
            overall_suggestions="建议",
        )

        mock_generate_structured.side_effect = [
            mock_strategy,  # generate_search_strategy_node
            mock_curation,  # curate_attractions_node
            persistent_flawed_skeleton,  # synthesize_itinerary_node
            persistent_flawed_skeleton,  # repair 1
            persistent_flawed_skeleton,  # repair 2
        ]

        req = TripRequest(
            city="杭州",
            start_date="2026-10-01",
            end_date="2026-10-01",
            travel_days=1,
            transportation="公共交通",
            accommodation="经济型酒店",
        )

        final_state = run_trip_planner_workflow(req)
        # 验证达到最大修补次数，显式流转至 failure_node
        self.assertGreaterEqual(final_state.get("repair_count"), 2)
        self.assertTrue(final_state.get("is_failed"))
        self.assertFalse(final_state.get("validation_passed"))
        self.assertIsNone(final_state.get("final_plan"))
        self.assertIn("生成失败", final_state.get("error_message", ""))


if __name__ == "__main__":
    unittest.main()
