"""API 接口测试 (test_api_trip)

测试范围:
1. test_health_check: 验证 /api/trip/health 健康检查接口
2. test_plan_trip_success: 验证 /api/trip/plan 成功生成旅行计划并返回 200 与合规数据
3. test_plan_trip_input_validation_failure: 验证前置输入参数校验未通过返回 400 Bad Request
4. test_plan_trip_workflow_execution_failure: 验证工作流校验修补超限显式失败返回 500
5. test_multi_agent_adapter_compatibility: 验证向后兼容适配器 MultiAgentTripPlanner 的正常委托与异常抛出
"""

import unittest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from app.api.main import app
from app.models.schemas import (
    TripRequest,
    TripPlan,
    DayPlan,
    Attraction,
    Location,
    Budget,
)
from app.agents.trip_planner_agent import get_trip_planner_agent


class TestTripAPI(unittest.TestCase):
    """旅行规划 API 端点与兼容适配层测试"""

    def setUp(self):
        self.client = TestClient(app)
        self.valid_payload = {
            "city": "杭州",
            "start_date": "2026-10-01",
            "end_date": "2026-10-01",
            "travel_days": 1,
            "transportation": "公共交通",
            "accommodation": "经济型酒店",
            "preferences": ["自然风光"],
            "free_text_input": "想去西湖",
        }

        self.mock_plan = TripPlan(
            city="杭州",
            start_date="2026-10-01",
            end_date="2026-10-01",
            days=[
                DayPlan(
                    date="2026-10-01",
                    day_index=0,
                    description="西湖一日游",
                    transportation="公共交通",
                    accommodation="经济型酒店",
                    attractions=[
                        Attraction(
                            name="西湖风景区",
                            address="杭州市西湖区南山路",
                            location=Location(longitude=120.14, latitude=30.24),
                            visit_duration=180,
                            description="著名自然文化景区",
                            category="名胜古迹",
                            rating=4.9,
                            ticket_price=0,
                        )
                    ],
                    meals=[],
                )
            ],
            weather_info=[],
            overall_suggestions="建议穿舒适鞋子。",
            budget=Budget(
                total_attractions=0,
                total_hotels=200,
                total_meals=100,
                total_transportation=50,
                total=350,
            ),
        )

    def test_health_check(self):
        """测试 /api/trip/health 健康检查"""
        response = self.client.get("/api/trip/health")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data.get("status"), "healthy")
        self.assertEqual(data.get("engine"), "langgraph-stategraph")
        self.assertTrue(data.get("graph_compiled"))

    @patch("app.api.routes.trip.run_trip_planner_workflow")
    def test_plan_trip_success(self, mock_run_workflow):
        """测试成功生成旅行计划并返回 200"""
        mock_run_workflow.return_value = {
            "is_failed": False,
            "validation_passed": True,
            "final_plan": self.mock_plan,
        }

        response = self.client.post("/api/trip/plan", json=self.valid_payload)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data.get("success"))
        self.assertEqual(data.get("message"), "旅行计划生成成功")
        self.assertIsNotNone(data.get("data"))
        self.assertEqual(data["data"]["city"], "杭州")
        self.assertEqual(len(data["data"]["days"]), 1)
        self.assertEqual(data["data"]["budget"]["total"], 350)

    @patch("app.api.routes.trip.run_trip_planner_workflow")
    def test_plan_trip_input_validation_failure(self, mock_run_workflow):
        """测试前置参数校验不通过返回 400 Bad Request"""
        mock_run_workflow.return_value = {
            "is_failed": True,
            "validation_passed": False,
            "draft_skeleton": None,
            "error_message": "出发日期不能晚于返程日期",
        }

        response = self.client.post("/api/trip/plan", json=self.valid_payload)
        self.assertEqual(response.status_code, 400)
        self.assertIn("出发日期不能晚于返程日期", response.json().get("detail", ""))

    @patch("app.api.routes.trip.run_trip_planner_workflow")
    def test_plan_trip_workflow_execution_failure(self, mock_run_workflow):
        """测试工作流执行/修补超限失败返回 500 Internal Server Error"""
        mock_run_workflow.return_value = {
            "is_failed": True,
            "validation_passed": False,
            "draft_skeleton": MagicMock(),  # 已经历了推理生成骨架
            "error_message": "修补次数已达上限 (2/2) 仍未通过校验",
        }

        response = self.client.post("/api/trip/plan", json=self.valid_payload)
        self.assertEqual(response.status_code, 500)
        self.assertIn("修补次数已达上限", response.json().get("detail", ""))

    @patch("app.agents.trip_planner_agent.run_trip_planner_workflow")
    def test_multi_agent_adapter_compatibility(self, mock_run_workflow):
        """测试向后兼容适配层 MultiAgentTripPlanner"""
        adapter = get_trip_planner_agent()
        req = TripRequest(**self.valid_payload)

        # 成功场景
        mock_run_workflow.return_value = {
            "is_failed": False,
            "validation_passed": True,
            "final_plan": self.mock_plan,
        }
        plan = adapter.plan_trip(req)
        self.assertEqual(plan.city, "杭州")
        self.assertEqual(len(plan.days), 1)

        # 失败场景 - 显式抛出 RuntimeError，绝不使用 fallback 假数据
        mock_run_workflow.return_value = {
            "is_failed": True,
            "error_message": "候选池资源耗尽",
        }
        with self.assertRaises(RuntimeError) as ctx:
            adapter.plan_trip(req)
        self.assertIn("候选池资源耗尽", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
