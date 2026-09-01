"""单元测试：LLM 推理节点测试 (test_reasoning_nodes)

测试范围:
1. generate_search_strategy_node: 正常生成与大模型异常降级兜底
2. curate_attractions_node: 实体真实性过滤（物理剔除虚构 ID）、数量保障补充、候选池为空容错
3. synthesize_itinerary_node: 行程骨架结构化生成
4. repair_skeleton_node: 修补计数器累加与定向修补
"""

import unittest
from unittest.mock import patch

from app.models.schemas import Location
from app.models.state import (
    TripPlannerState,
    SearchStrategy,
    CuratedAttractions,
    ItineraryDraftSkeleton,
    DayAssignment,
    MealAssignment,
    AttractionCandidate,
    HotelCandidate,
    RestaurantCandidate,
)
from app.workflow.nodes.reasoning_nodes import (
    generate_search_strategy_node,
    curate_attractions_node,
    synthesize_itinerary_node,
    repair_skeleton_node,
)


class TestReasoningNodes(unittest.TestCase):
    """LLM 推理节点单元测试"""

    def setUp(self):
        self.candidate_attrs = {
            f"ATTR_{i}": AttractionCandidate(
                poi_id=f"ATTR_{i}",
                name=f"景点_{i}",
                location=Location(longitude=120.0 + i * 0.01, latitude=30.0 + i * 0.01),
                rating=4.5 + (i % 5) * 0.1,
            )
            for i in range(1, 10)
        }

        self.base_state: TripPlannerState = {
            "city": "杭州",
            "travel_days": 2,
            "start_date": "2026-10-01",
            "end_date": "2026-10-02",
            "preferences": ["文化古迹"],
            "transportation": "公共交通",
            "accommodation": "经济舒适",
            "free_text_input": "想去西湖游船",
            "candidate_attractions": self.candidate_attrs,
            "candidate_hotels": {},
            "candidate_restaurants": {},
            "warnings": [],
            "repair_count": 0,
        }

    @patch("app.workflow.nodes.reasoning_nodes.generate_structured")
    def test_generate_search_strategy_success(self, mock_generate):
        """测试正常生成搜索策略"""
        expected_strat = SearchStrategy(
            attraction_keywords=["西湖风景名胜区", "灵隐景区"],
            hotel_keyword="西湖快捷酒店",
            restaurant_keywords=["杭州传统面馆", "杭帮菜"],
        )
        mock_generate.return_value = expected_strat

        result = generate_search_strategy_node(self.base_state)
        self.assertIn("strategy", result)
        self.assertEqual(result["strategy"].hotel_keyword, "西湖快捷酒店")
        self.assertEqual(len(result["strategy"].attraction_keywords), 2)

    @patch("app.workflow.nodes.reasoning_nodes.generate_structured")
    def test_generate_search_strategy_fallback(self, mock_generate):
        """测试 LLM 异常时优雅降级为兜底策略，保障流水线不崩塌"""
        mock_generate.side_effect = RuntimeError("LLM API 熔断")

        result = generate_search_strategy_node(self.base_state)
        self.assertIn("strategy", result)
        self.assertIn("warnings", result)
        self.assertGreater(len(result["strategy"].attraction_keywords), 0)

    @patch("app.workflow.nodes.reasoning_nodes.generate_structured")
    def test_curate_attractions_filters_fake_ids(self, mock_generate):
        """测试景点精选节点严格过滤不存在的假 POI ID"""
        # 模型返回了一个不存在的伪造 ID 和一个合法 ID
        mock_generate.return_value = CuratedAttractions(
            selected_poi_ids=["FAKE_POI_999", "ATTR_1"],
            reasoning="推荐西湖",
        )

        result = curate_attractions_node(self.base_state)
        self.assertIn("selected_attraction_ids", result)
        selected_ids = result["selected_attraction_ids"]

        # 假 ID 必须被剔除
        self.assertNotIn("FAKE_POI_999", selected_ids)
        # 真 ID 必须保留
        self.assertIn("ATTR_1", selected_ids)
        # 且天数=2 时，自动补充满足至少 4 个景点
        self.assertGreaterEqual(len(selected_ids), 4)

    def test_curate_attractions_empty_candidates(self):
        """测试候选池为空时的健壮处理"""
        empty_state = dict(self.base_state)
        empty_state["candidate_attractions"] = {}

        result = curate_attractions_node(empty_state)
        self.assertEqual(result["selected_attraction_ids"], [])
        self.assertIn("warnings", result)

    @patch("app.workflow.nodes.reasoning_nodes.generate_structured")
    def test_synthesize_itinerary_node(self, mock_generate):
        """测试行程骨架合成"""
        skeleton = ItineraryDraftSkeleton(
            days=[
                DayAssignment(
                    day_index=0,
                    date="2026-10-01",
                    theme_description="西湖人文漫步",
                    attraction_poi_ids=["ATTR_1", "ATTR_2"],
                    meals=[
                        MealAssignment(type="breakfast", name="小笼包早餐"),
                        MealAssignment(type="lunch", name="杭帮特色菜"),
                        MealAssignment(type="dinner", name="西湖醋鱼晚宴"),
                    ],
                ),
                DayAssignment(
                    day_index=1,
                    date="2026-10-02",
                    theme_description="灵隐祈福古刹游",
                    attraction_poi_ids=["ATTR_3", "ATTR_4"],
                    meals=[
                        MealAssignment(type="breakfast", name="素斋面"),
                        MealAssignment(type="lunch", name="茶餐厅"),
                        MealAssignment(type="dinner", name="特色小吃"),
                    ],
                ),
            ],
            overall_suggestions="建议准备舒适跑鞋，携带雨具。",
        )
        mock_generate.return_value = skeleton

        result = synthesize_itinerary_node(self.base_state)
        self.assertIn("draft_skeleton", result)
        self.assertEqual(len(result["draft_skeleton"].days), 2)

    @patch("app.workflow.nodes.reasoning_nodes.generate_structured")
    def test_repair_skeleton_node(self, mock_generate):
        """测试骨架修复节点修补计数器累加"""
        repaired_skeleton = ItineraryDraftSkeleton(
            days=[
                DayAssignment(
                    day_index=0,
                    date="2026-10-01",
                    theme_description="已修复主题",
                    attraction_poi_ids=["ATTR_1", "ATTR_2"],
                    meals=[
                        MealAssignment(type="breakfast", name="早餐"),
                        MealAssignment(type="lunch", name="午餐"),
                        MealAssignment(type="dinner", name="晚餐"),
                    ],
                )
            ],
            overall_suggestions="修复后建议",
        )
        mock_generate.return_value = repaired_skeleton

        state_with_error = dict(self.base_state)
        state_with_error["repair_count"] = 0
        state_with_error["validation_errors"] = ["第 1 天未安排任何景点"]

        result = repair_skeleton_node(state_with_error)
        self.assertIn("draft_skeleton", result)
        self.assertEqual(result["repair_count"], 1)


if __name__ == "__main__":
    unittest.main()
