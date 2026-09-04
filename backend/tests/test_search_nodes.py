"""单元测试：搜索与天气节点测试 (test_search_nodes)

测试范围:
1. fetch_weather_node: 正常获取、服务无数据、异常捕获 (天气透明策略)
2. search_attractions: 多关键词检索、候选去重与空保护
3. search_hotels: 关键词检索与候选池聚合
4. search_restaurants: 真实餐饮检索与候选池聚合
"""

import unittest
from unittest.mock import patch, MagicMock

from app.models.schemas import WeatherInfo, Location
from app.models.state import (
    TripPlannerState,
    SearchStrategy,
    AttractionCandidate,
    HotelCandidate,
    RestaurantCandidate,
)
from app.workflow.nodes.search_nodes import (
    fetch_weather_node,
    search_attractions,
    search_hotels,
    search_restaurants,
)


class TestSearchNodes(unittest.TestCase):
    """搜索与天气节点单元测试"""

    def setUp(self):
        self.base_state: TripPlannerState = {
            "city": "杭州",
            "travel_days": 2,
            "start_date": "2026-10-01",
            "end_date": "2026-10-02",
            "preferences": ["文化古迹", "自然风光"],
            "strategy": SearchStrategy(
                attraction_keywords=["西湖风景区", "灵隐寺"],
                hotel_keyword="西湖边精品民宿",
                restaurant_keywords=["杭帮菜", "西湖醋鱼"],
            ),
            "warnings": [],
        }

    @patch("app.workflow.nodes.search_nodes.get_amap_service")
    def test_fetch_weather_success(self, mock_get_amap):
        """测试正常天气检索成功"""
        mock_service = MagicMock()
        mock_weather = [
            WeatherInfo(
                date="2026-10-01",
                day_weather="多云",
                night_weather="晴",
                day_temp="24",
                night_temp="16",
                day_wind="微风",
                night_wind="微风",
            )
        ]
        mock_service.get_weather.return_value = mock_weather
        mock_get_amap.return_value = mock_service

        result = fetch_weather_node(self.base_state)
        self.assertIn("raw_weather", result)
        self.assertEqual(len(result["raw_weather"]), 1)
        self.assertEqual(result["raw_weather"][0].day_weather, "多云")

    @patch("app.workflow.nodes.search_nodes.get_amap_service")
    def test_fetch_weather_transparent_policy(self, mock_get_amap):
        """测试天气透明原则：服务不可用时返回空列表与 warning，不伪造假天气"""
        mock_service = MagicMock()
        mock_service.get_weather.return_value = []
        mock_get_amap.return_value = mock_service

        result = fetch_weather_node(self.base_state)
        self.assertEqual(result["raw_weather"], [])
        self.assertIn("warnings", result)
        self.assertTrue(any("未返回" in w for w in result["warnings"]))

    @patch("app.workflow.nodes.search_nodes.get_amap_service")
    def test_fetch_weather_exception_handling(self, mock_get_amap):
        """测试天气查询发生异常时的健壮处理"""
        mock_service = MagicMock()
        mock_service.get_weather.side_effect = RuntimeError("网络超时连接失败")
        mock_get_amap.return_value = mock_service

        result = fetch_weather_node(self.base_state)
        self.assertEqual(result["raw_weather"], [])
        self.assertIn("warnings", result)

    @patch("app.workflow.nodes.search_nodes.get_amap_service")
    def test_search_attractions_deduplication(self, mock_get_amap):
        """测试景点多关键词检索与 POI ID 去重"""
        mock_service = MagicMock()
        cand1 = AttractionCandidate(
            poi_id="POI_WEST_LAKE",
            name="西湖",
            type="风景名胜",
            location=Location(longitude=120.14, latitude=30.24),
        )
        cand2 = AttractionCandidate(
            poi_id="POI_LINGYIN",
            name="灵隐寺",
            type="寺庙古迹",
            location=Location(longitude=120.10, latitude=30.23),
        )
        # 模拟两个关键词分别返回相同和不同的景点
        mock_service.search_attraction_candidates.side_effect = [
            [cand1],
            [cand1, cand2],
        ]
        mock_get_amap.return_value = mock_service

        result = search_attractions(self.base_state)
        self.assertIn("candidate_attractions", result)
        candidates = result["candidate_attractions"]
        # 去重后应当为 2
        self.assertEqual(len(candidates), 2)
        self.assertIn("POI_WEST_LAKE", candidates)
        self.assertIn("POI_LINGYIN", candidates)

    @patch("app.workflow.nodes.search_nodes.get_amap_service")
    def test_search_attractions_fallback_on_empty(self, mock_get_amap):
        """测试专属关键词命中数为0时，自动触发通用兜底词泛搜机制"""
        mock_service = MagicMock()
        fallback_cand = AttractionCandidate(
            poi_id="POI_FALLBACK",
            name="漯河市沙澧河风景区",
            type="风景名胜",
            location=None,
        )
        # 初始专属关键词均返回空列表，兜底词搜索命中
        mock_service.search_attraction_candidates.side_effect = [
            [],  # kw 1: 西湖风景区 -> 0
            [],  # kw 2: 灵隐寺 -> 0
            [fallback_cand],  # 兜底词 -> 命中 1 个
        ]
        mock_get_amap.return_value = mock_service

        result = search_attractions(self.base_state)
        self.assertIn("candidate_attractions", result)
        self.assertEqual(len(result["candidate_attractions"]), 1)
        self.assertIn("POI_FALLBACK", result["candidate_attractions"])
        self.assertIn("warnings", result)
        self.assertTrue(any("兜底泛搜" in w for w in result["warnings"]))

    @patch("app.workflow.nodes.search_nodes.get_amap_service")
    def test_search_hotels(self, mock_get_amap):
        """测试酒店检索与候选池聚合"""
        mock_service = MagicMock()
        hotel_cand = HotelCandidate(
            poi_id="HOTEL_01",
            name="西湖晴澜客栈",
            location=Location(longitude=120.15, latitude=30.25),
            estimated_cost=380,
        )
        mock_service.search_hotel_candidates.return_value = [hotel_cand]
        mock_get_amap.return_value = mock_service

        result = search_hotels(self.base_state)
        self.assertIn("candidate_hotels", result)
        self.assertIn("HOTEL_01", result["candidate_hotels"])

    @patch("app.workflow.nodes.search_nodes.get_amap_service")
    def test_search_restaurants(self, mock_get_amap):
        """测试真实特色餐厅检索"""
        mock_service = MagicMock()
        rest_cand = RestaurantCandidate(
            poi_id="REST_01",
            name="楼外楼",
            cuisine="杭帮菜",
            location=Location(longitude=120.14, latitude=30.25),
            estimated_cost=150,
        )
        mock_service.search_restaurant_candidates.return_value = [rest_cand]
        mock_get_amap.return_value = mock_service

        result = search_restaurants(self.base_state)
        self.assertIn("candidate_restaurants", result)
        self.assertIn("REST_01", result["candidate_restaurants"])

    @patch("app.workflow.nodes.search_nodes.get_amap_service")
    def test_search_nodes_top_k_truncation(self, mock_get_amap):
        """测试检索节点按关键词 Top-K 裁剪防候选池无序膨胀 (用例 2)"""
        mock_service = MagicMock()
        mock_get_amap.return_value = mock_service

        # 1. 景点 Mock：每个关键词返回 10 个候选，单关键词应严格截取前 3 个
        mock_attractions_raw = [
            AttractionCandidate(
                poi_id=f"ATTR_{i:02d}",
                name=f"景区_{i:02d}",
                type="风景名胜",
                location=Location(longitude=120.0 + i * 0.01, latitude=30.0),
            )
            for i in range(10)
        ]
        mock_service.search_attraction_candidates.return_value = mock_attractions_raw

        single_kw_state: TripPlannerState = {
            "city": "杭州",
            "strategy": SearchStrategy(
                attraction_keywords=["西湖"],
                hotel_keyword="酒店",
                restaurant_keywords=["特色菜"],
            ),
        }
        attr_result = search_attractions(single_kw_state)
        # 单个关键词原本 10 个，截断后候选池数量必须为 3
        self.assertEqual(len(attr_result["candidate_attractions"]), 3)
        self.assertIn("ATTR_00", attr_result["candidate_attractions"])
        self.assertIn("ATTR_01", attr_result["candidate_attractions"])
        self.assertIn("ATTR_02", attr_result["candidate_attractions"])
        self.assertNotIn("ATTR_03", attr_result["candidate_attractions"])

        # 2. 酒店 Mock：返回 15 个候选，严格截取前 6 个
        mock_hotels_raw = [
            HotelCandidate(
                poi_id=f"HOTEL_{i:02d}",
                name=f"酒店_{i:02d}",
                location=Location(longitude=120.0, latitude=30.0),
            )
            for i in range(15)
        ]
        mock_service.search_hotel_candidates.return_value = mock_hotels_raw
        hotel_result = search_hotels(single_kw_state)
        self.assertEqual(len(hotel_result["candidate_hotels"]), 6)
        self.assertIn("HOTEL_05", hotel_result["candidate_hotels"])
        self.assertNotIn("HOTEL_06", hotel_result["candidate_hotels"])

        # 3. 餐饮 Mock：返回 12 个候选，单关键词严格截取前 4 个
        mock_rests_raw = [
            RestaurantCandidate(
                poi_id=f"REST_{i:02d}",
                name=f"餐厅_{i:02d}",
                cuisine="当地特色",
                location=Location(longitude=120.0, latitude=30.0),
            )
            for i in range(12)
        ]
        mock_service.search_restaurant_candidates.return_value = mock_rests_raw
        rest_result = search_restaurants(single_kw_state)
        self.assertEqual(len(rest_result["candidate_restaurants"]), 4)
        self.assertIn("REST_03", rest_result["candidate_restaurants"])
        self.assertNotIn("REST_04", rest_result["candidate_restaurants"])


if __name__ == "__main__":
    unittest.main()
