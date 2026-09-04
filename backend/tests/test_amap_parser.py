"""高德地图 MCP 响应解析器单元测试 (涵盖天气、POI、路线、地理编码、候选转换及无虚构数据保障)"""

import unittest
from app.models.schemas import Location, POIInfo, WeatherInfo, RouteInfo
from app.services.amap_service import (
    parse_location_str,
    extract_json_from_mcp_response,
    parse_weather_list,
    parse_poi_list,
    parse_route_info,
    parse_geocode,
    parse_poi_detail,
    poi_to_attraction_candidate,
    poi_to_hotel_candidate,
    poi_to_restaurant_candidate,
)


class TestAmapParser(unittest.TestCase):
    """测试高德 MCP 原始文本与数据解析"""

    def test_parse_location_str(self):
        """测试经纬度解析"""
        loc1 = parse_location_str("116.397026,39.918058")
        self.assertIsNotNone(loc1)
        self.assertAlmostEqual(loc1.longitude, 116.397026)
        self.assertAlmostEqual(loc1.latitude, 39.918058)

        # 字典格式
        loc2 = parse_location_str({"longitude": 121.47, "latitude": 31.23})
        self.assertIsNotNone(loc2)
        self.assertEqual(loc2.longitude, 121.47)

        # 异常数据
        self.assertIsNone(parse_location_str(""))
        self.assertIsNone(parse_location_str("invalid,coords"))
        self.assertIsNone(parse_location_str("999.0,39.0"))  # 超出范围

    def test_extract_json_from_mcp_response(self):
        """测试从 MCP 工具输出中提取 JSON (包括工具名前缀和代码块)"""
        # 1. 包含 MCP 工具前缀输出
        raw_mcp = (
            "工具 'maps_text_search' 执行结果:\n"
            '{"status": "1", "count": "1", "pois": [{"id": "B1", "name": "故宫"}]}'
        )
        data = extract_json_from_mcp_response(raw_mcp)
        self.assertIsInstance(data, dict)
        self.assertEqual(data["count"], "1")

        # 2. Markdown 代码块
        raw_md = "```json\n{\"city\": \"北京\"}\n```"
        data_md = extract_json_from_mcp_response(raw_md)
        self.assertEqual(data_md.get("city"), "北京")

        # 3. 错误提示拦截
        error_output = "错误：必须指定 action 参数或 tool_name 参数"
        self.assertIsNone(extract_json_from_mcp_response(error_output))

        mcp_fail = "MCP 操作失败: Connection refused"
        self.assertIsNone(extract_json_from_mcp_response(mcp_fail))

    def test_parse_weather_forecasts(self):
        """测试高德预报天气解析 (forecasts -> casts)"""
        raw_weather = """
        工具 'maps_weather' 执行结果:
        {
            "status": "1",
            "count": "1",
            "info": "OK",
            "infocode": "10000",
            "forecasts": [
                {
                    "city": "北京市",
                    "adcode": "110000",
                    "province": "北京",
                    "reporttime": "2026-10-01 11:00:00",
                    "casts": [
                        {
                            "date": "2026-10-01",
                            "week": "4",
                            "dayweather": "晴",
                            "nightweather": "多云",
                            "daytemp": "24",
                            "nighttemp": "12",
                            "daywind": "北",
                            "nightwind": "北",
                            "daypower": "1-3",
                            "nightpower": "1-3"
                        },
                        {
                            "date": "2026-10-02",
                            "week": "5",
                            "dayweather": "阴",
                            "nightweather": "小雨",
                            "daytemp": "19",
                            "nighttemp": "10",
                            "daywind": "南",
                            "nightwind": "南",
                            "daypower": "1-2",
                            "nightpower": "1-2"
                        }
                    ]
                }
            ]
        }
        """
        weather_list = parse_weather_list(raw_weather)
        self.assertEqual(len(weather_list), 2)
        self.assertEqual(weather_list[0].date, "2026-10-01")
        self.assertEqual(weather_list[0].day_weather, "晴")
        self.assertEqual(weather_list[0].day_temp, 24)
        self.assertEqual(weather_list[0].night_temp, 12)
        self.assertEqual(weather_list[1].day_weather, "阴")

    def test_parse_weather_mcp_format(self):
        """测试 amap-mcp-server 扁平预报天气格式 (forecasts 下直接为单日预报对象)"""
        mcp_weather_raw = """
        工具 'maps_weather' 执行结果:
        {
            "city": "漯河市",
            "forecasts": [
                {
                    "date": "2026-09-04",
                    "dayweather": "晴",
                    "nightweather": "晴",
                    "daytemp": "31",
                    "nighttemp": "21",
                    "daywind": "东北",
                    "daypower": "≤3",
                    "nightpower": "≤3"
                },
                {
                    "date": "2026-09-05",
                    "dayweather": "多云",
                    "nightweather": "晴",
                    "daytemp": "30",
                    "nighttemp": "22",
                    "daywind": "东",
                    "daypower": "≤3",
                    "nightpower": "≤3"
                }
            ]
        }
        """
        weather_list = parse_weather_list(mcp_weather_raw)
        self.assertEqual(len(weather_list), 2)
        self.assertEqual(weather_list[0].date, "2026-09-04")
        self.assertEqual(weather_list[0].day_weather, "晴")
        self.assertEqual(weather_list[0].day_temp, 31)
        self.assertEqual(weather_list[0].night_temp, 21)
        self.assertEqual(weather_list[1].date, "2026-09-05")
        self.assertEqual(weather_list[1].day_weather, "多云")

    def test_parse_weather_failure_returns_empty_list(self):
        """核心规范测试: 外部天气服务失败时返回空列表，绝对不伪造假晴天"""
        bad_response = "MCP 操作失败: API key quota exceeded"
        weather_list = parse_weather_list(bad_response)
        self.assertEqual(weather_list, [], "天气查询失败时必须返回空列表，绝不填充假天气数据")

    def test_parse_poi_list_and_candidates(self):
        """测试 POI 解析及候选模型映射 (无伪造默认值)"""
        raw_poi_json = """
        {
            "status": "1",
            "count": "2",
            "pois": [
                {
                    "id": "B000A83M61",
                    "name": "故宫博物院",
                    "type": "风景名胜;风景名胜;国家级景点",
                    "address": "景山前街4号",
                    "location": "116.397026,39.918058",
                    "tel": "010-85007421",
                    "biz_ext": {
                        "rating": "4.9",
                        "cost": "60.00"
                    },
                    "photos": [
                        {"title": "太和殿", "url": "https://example.com/gugong1.jpg"}
                    ]
                },
                {
                    "id": "B000A83HOTEL",
                    "name": "王府井大饭店",
                    "type": "住宿服务;宾馆酒店;五星级宾馆",
                    "address": "王府井大街57号",
                    "location": "116.417026,39.918058",
                    "biz_ext": {
                        "rating": "4.6",
                        "cost": "850.00"
                    }
                }
            ]
        }
        """
        # 1. 基础 POI 列表解析
        pois = parse_poi_list(raw_poi_json)
        self.assertEqual(len(pois), 2)
        self.assertEqual(pois[0].id, "B000A83M61")
        self.assertEqual(pois[0].name, "故宫博物院")
        self.assertAlmostEqual(pois[0].location.longitude, 116.397026)

        # 2. 转换为景点候选
        data = extract_json_from_mcp_response(raw_poi_json)
        gugong_dict = data["pois"][0]
        attr_cand = poi_to_attraction_candidate(gugong_dict)
        self.assertIsNotNone(attr_cand)
        self.assertEqual(attr_cand.name, "故宫博物院")
        self.assertEqual(attr_cand.rating, 4.9)
        self.assertEqual(attr_cand.ticket_price, 60)
        self.assertEqual(attr_cand.photos, ["https://example.com/gugong1.jpg"])
        self.assertIsNone(attr_cand.estimated_duration, "API 未提供游览时长时必须为 None")

        # 3. 转换为酒店候选
        hotel_dict = data["pois"][1]
        hotel_cand = poi_to_hotel_candidate(hotel_dict)
        self.assertIsNotNone(hotel_cand)
        self.assertEqual(hotel_cand.name, "王府井大饭店")
        self.assertEqual(hotel_cand.rating, "4.6")
        self.assertEqual(hotel_cand.estimated_cost, 850)
        self.assertIsNone(hotel_cand.price_range, "API 未提供价格区间时必须为 None")

    def test_poi_candidate_without_location(self):
        """测试 maps_text_search 裁剪返回无 location 字段时的 POI 候选保留 (严禁误杀丢弃)"""
        mcp_poi = {
            "id": "B018B0M9TX",
            "name": "许慎文化园",
            "address": "河南省漯河市郾城区龙江路与中山路交叉口向东500米",
            "typecode": "110202",
        }
        cand = poi_to_attraction_candidate(mcp_poi)
        self.assertIsNotNone(cand, "无 location 字段的 POI 不能被过滤丢弃")
        self.assertEqual(cand.poi_id, "B018B0M9TX")
        self.assertEqual(cand.name, "许慎文化园")
        self.assertIsNone(cand.location, "初筛阶段无经纬度时允许 location 为 None，由还原阶段按需补齐")

        # 酒店无坐标同样保留
        hotel_cand = poi_to_hotel_candidate(mcp_poi)
        self.assertIsNotNone(hotel_cand)
        self.assertIsNone(hotel_cand.location)

        # 餐饮无坐标同样保留
        rest_cand = poi_to_restaurant_candidate(mcp_poi)
        self.assertIsNotNone(rest_cand)
        self.assertIsNone(rest_cand.location)

    def test_parse_route_info(self):
        """测试路线规划解析 (步行与公共交通)"""
        # 步行路线
        walking_json = """
        {
            "status": "1",
            "route": {
                "paths": [
                    {
                        "distance": "1250",
                        "duration": "950",
                        "steps": [
                            {"instruction": "向东走100米"},
                            {"instruction": "向北走500米"}
                        ]
                    }
                ]
            }
        }
        """
        route = parse_route_info(walking_json, route_type="walking")
        self.assertIsNotNone(route)
        self.assertEqual(route.distance, 1250.0)
        self.assertEqual(route.duration, 950)
        self.assertEqual(route.route_type, "walking")
        self.assertIn("向东走100米", route.description)

        # 异常数据返回 None
        self.assertIsNone(parse_route_info("{}", route_type="walking"))

    def test_parse_geocode(self):
        """测试地理编码解析"""
        geo_json = """
        {
            "status": "1",
            "geocodes": [
                {
                    "formatted_address": "北京市东城区天安门广场",
                    "location": "116.397755,39.903179"
                }
            ]
        }
        """
        loc = parse_geocode(geo_json)
        self.assertIsNotNone(loc)
        self.assertAlmostEqual(loc.longitude, 116.397755)
        self.assertAlmostEqual(loc.latitude, 39.903179)


if __name__ == "__main__":
    unittest.main()
