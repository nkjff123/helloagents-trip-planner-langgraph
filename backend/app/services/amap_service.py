"""高德地图 MCP 服务封装与解析器模块

提供对高德 MCP 服务 (maps_text_search, maps_weather, maps_direction_*, maps_geo, maps_search_detail)
的健壮调用与解析，严格切断虚构数据，确保真实 POI/天气/路线/坐标落地。
"""

import json
import re
from datetime import date
from typing import List, Dict, Any, Optional, Union
from loguru import logger
from hello_agents.tools import MCPTool

from ..config import get_settings
from ..models.schemas import Location, POIInfo, WeatherInfo, RouteInfo
from ..models.state import AttractionCandidate, HotelCandidate, RestaurantCandidate

# 全局 MCP 工具实例
_amap_mcp_tool: Optional[MCPTool] = None


def get_amap_mcp_tool() -> MCPTool:
    """获取高德地图 MCP 工具实例 (单例模式)"""
    global _amap_mcp_tool

    if _amap_mcp_tool is None:
        settings = get_settings()

        if not settings.amap_api_key:
            raise ValueError("高德地图 API Key 未配置，请在 .env 文件中设置 AMAP_API_KEY")

        # 创建 MCP 工具
        _amap_mcp_tool = MCPTool(
            name="amap",
            description="高德地图服务，支持 POI 搜索、路线规划、天气查询等功能",
            server_command=["uvx", "amap-mcp-server"],
            env={"AMAP_MAPS_API_KEY": settings.amap_api_key},
            auto_expand=True,
        )

        logger.info(
            f"高德地图 MCP 工具初始化成功 | 可用工具数: {len(_amap_mcp_tool._available_tools)}"
        )

    return _amap_mcp_tool


# ============ 解析辅助函数 (纯确定性解析，便于独立单测) ============


def parse_location_str(loc_data: Any) -> Optional[Location]:
    """解析经纬度格式，支持 'lng,lat' 字符串或已有字典/模型"""
    if isinstance(loc_data, Location):
        return loc_data
    if isinstance(loc_data, dict):
        try:
            return Location(
                longitude=float(loc_data["longitude"]),
                latitude=float(loc_data["latitude"]),
            )
        except (KeyError, ValueError, TypeError):
            return None

    if not isinstance(loc_data, str) or "," not in loc_data:
        return None

    parts = loc_data.split(",")
    if len(parts) >= 2:
        try:
            lon = float(parts[0].strip())
            lat = float(parts[1].strip())
            # 经纬度合法性基本范围过滤
            if -180.0 <= lon <= 180.0 and -90.0 <= lat <= 90.0:
                return Location(longitude=lon, latitude=lat)
        except (ValueError, TypeError):
            return None
    return None


def extract_json_from_mcp_response(raw_output: Any) -> Optional[Union[Dict[str, Any], List[Any]]]:
    """从 MCP 工具输出中稳健提取 JSON 数据结构

    支持:
    - 字典/列表直接透传
    - 工具输出包含前缀说明文本 (如 "工具 'maps_text_search' 执行结果:\n{...}")
    - Markdown ```json 代码块包裹
    - 纯 JSON 文本
    """
    if raw_output is None:
        return None
    if isinstance(raw_output, (dict, list)):
        return raw_output

    if not isinstance(raw_output, str):
        raw_output = str(raw_output)

    trimmed = raw_output.strip()
    if not trimmed:
        return None

    # MCP 错误拦截
    if (
        trimmed.startswith("错误：")
        or trimmed.startswith("MCP 操作失败")
        or trimmed.startswith("异步操作失败")
    ):
        logger.warning(f"MCP 工具执行报错: {trimmed[:200]}")
        return None

    # 1. 尝试直接反序列化
    try:
        return json.loads(trimmed)
    except json.JSONDecodeError:
        pass

    # 2. 匹配 Markdown 代码块
    code_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", trimmed, re.IGNORECASE)
    if code_match:
        try:
            return json.loads(code_match.group(1).strip())
        except json.JSONDecodeError:
            pass

    # 3. 匹配最外层花括号 {...}
    first_brace = trimmed.find("{")
    last_brace = trimmed.rfind("}")
    if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
        try:
            return json.loads(trimmed[first_brace : last_brace + 1].strip())
        except json.JSONDecodeError:
            pass

    # 4. 匹配最外层方括号 [...]
    first_bracket = trimmed.find("[")
    last_bracket = trimmed.rfind("]")
    if first_bracket != -1 and last_bracket != -1 and last_bracket > first_bracket:
        try:
            return json.loads(trimmed[first_bracket : last_bracket + 1].strip())
        except json.JSONDecodeError:
            pass

    return None


def parse_weather_list(raw_response: Any) -> List[WeatherInfo]:
    """解析高德天气响应为 List[WeatherInfo]

    支持:
    - 预报天气 forecasts -> casts
    - 实时天气 lives
    - 失败或空时返回空列表 (绝不注入伪造天气)
    """
    data = extract_json_from_mcp_response(raw_response)
    if not data:
        return []

    # 兼容已结构化的数据列表
    if isinstance(data, list):
        items = []
        for item in data:
            if isinstance(item, dict):
                try:
                    items.append(WeatherInfo.model_validate(item))
                except Exception:
                    pass
        if items:
            return items

    if not isinstance(data, dict):
        return []

    weather_list: List[WeatherInfo] = []

    # 1. 优先解析预报 forecasts
    forecasts = data.get("forecasts", [])
    if isinstance(forecasts, list) and forecasts:
        for f in forecasts:
            if not isinstance(f, dict):
                continue
            casts = f.get("casts", [])
            if isinstance(casts, list):
                for cast in casts:
                    if not isinstance(cast, dict):
                        continue
                    try:
                        weather_info = WeatherInfo(
                            date=str(cast.get("date", "")),
                            day_weather=str(cast.get("dayweather", "")),
                            night_weather=str(cast.get("nightweather", "")),
                            day_temp=cast.get("daytemp") or cast.get("daytemp_float") or 0,
                            night_temp=cast.get("nighttemp") or cast.get("nighttemp_float") or 0,
                            wind_direction=str(cast.get("daywind", "") or cast.get("nightwind", "")),
                            wind_power=str(cast.get("daypower", "") or cast.get("nightpower", "")),
                        )
                        weather_list.append(weather_info)
                    except Exception as e:
                        logger.warning(f"解析预报天气单日数据失败: {str(e)}, 数据: {cast}")

    # 2. 若无 forecasts，尝试解析实时天气 lives
    if not weather_list:
        lives = data.get("lives", [])
        if isinstance(lives, list) and lives:
            for live in lives:
                if not isinstance(live, dict):
                    continue
                try:
                    report_date = str(live.get("reporttime", ""))[:10] or str(date.today())
                    temp = live.get("temperature", 0)
                    weather_info = WeatherInfo(
                        date=report_date,
                        day_weather=str(live.get("weather", "")),
                        night_weather=str(live.get("weather", "")),
                        day_temp=temp,
                        night_temp=temp,
                        wind_direction=str(live.get("winddirection", "")),
                        wind_power=str(live.get("windpower", "")),
                    )
                    weather_list.append(weather_info)
                except Exception as e:
                    logger.warning(f"解析实时天气数据失败: {str(e)}")

    return weather_list


def parse_poi_list(raw_response: Any) -> List[POIInfo]:
    """解析高德 POI 文本搜索响应为 List[POIInfo]"""
    data = extract_json_from_mcp_response(raw_response)
    if not data:
        return []

    pois_raw = []
    if isinstance(data, dict):
        pois_raw = data.get("pois", [])
        if not pois_raw and "data" in data and isinstance(data["data"], dict):
            pois_raw = data["data"].get("pois", [])
    elif isinstance(data, list):
        pois_raw = data

    if not isinstance(pois_raw, list):
        return []

    poi_list: List[POIInfo] = []
    for p in pois_raw:
        if not isinstance(p, dict):
            continue
        poi_id = p.get("id") or p.get("poi_id")
        name = p.get("name")
        if not poi_id or not name:
            continue

        loc = parse_location_str(p.get("location"))
        if loc is None:
            continue

        address = p.get("address")
        if not isinstance(address, str):
            address = ""

        poi_type = p.get("type", "景点")
        if not isinstance(poi_type, str):
            poi_type = "景点"

        tel = p.get("tel")
        if isinstance(tel, list):
            tel = ",".join(tel) if tel else None
        elif not isinstance(tel, str) or not tel:
            tel = None

        poi_list.append(
            POIInfo(
                id=str(poi_id),
                name=str(name),
                type=poi_type,
                address=address,
                location=loc,
                tel=tel,
            )
        )
    return poi_list


def parse_route_info(raw_response: Any, route_type: str = "walking") -> Optional[RouteInfo]:
    """解析高德路线规划响应为 RouteInfo"""
    data = extract_json_from_mcp_response(raw_response)
    if not data or not isinstance(data, dict):
        return None

    route = data.get("route", {})
    if not isinstance(route, dict):
        return None

    # 1. 步行或驾车: paths
    paths = route.get("paths", [])
    if isinstance(paths, list) and paths:
        path = paths[0]
        if isinstance(path, dict):
            try:
                distance = float(path.get("distance", 0))
                duration = int(float(path.get("duration", 0)))
                steps = path.get("steps", [])
                instructions = []
                if isinstance(steps, list):
                    for s in steps:
                        if isinstance(s, dict) and s.get("instruction"):
                            instructions.append(str(s["instruction"]))
                desc = (
                    "；".join(instructions[:5])
                    if instructions
                    else f"{route_type}出行，全程约 {int(distance)} 米"
                )
                return RouteInfo(
                    distance=distance,
                    duration=duration,
                    route_type=route_type,
                    description=desc,
                )
            except Exception as e:
                logger.warning(f"解析 path 路线失败: {str(e)}")

    # 2. 公共交通: transits
    transits = route.get("transits", [])
    if isinstance(transits, list) and transits:
        transit = transits[0]
        if isinstance(transit, dict):
            try:
                distance = float(transit.get("distance", 0))
                duration = int(float(transit.get("duration", 0)))
                cost = transit.get("cost", "0")
                segments = transit.get("segments", [])
                seg_descs = []
                if isinstance(segments, list):
                    for seg in segments:
                        if isinstance(seg, dict):
                            bus = seg.get("bus", {})
                            if isinstance(bus, dict):
                                buslines = bus.get("buslines", [])
                                if isinstance(buslines, list) and buslines:
                                    line_name = buslines[0].get("name", "")
                                    if line_name:
                                        seg_descs.append(f"乘坐{line_name}")
                desc = (
                    " -> ".join(seg_descs)
                    if seg_descs
                    else f"公交出行，全程约 {duration // 60} 分钟，费用约 {cost} 元"
                )
                return RouteInfo(
                    distance=distance,
                    duration=duration,
                    route_type="transit",
                    description=desc,
                )
            except Exception as e:
                logger.warning(f"解析 transit 路线失败: {str(e)}")

    return None


def parse_geocode(raw_response: Any) -> Optional[Location]:
    """解析高德地理编码响应为 Location"""
    data = extract_json_from_mcp_response(raw_response)
    if not data or not isinstance(data, dict):
        return None

    geocodes = data.get("geocodes", [])
    if isinstance(geocodes, list) and geocodes:
        first = geocodes[0]
        if isinstance(first, dict):
            return parse_location_str(first.get("location"))

    return None


def parse_poi_detail(raw_response: Any) -> Dict[str, Any]:
    """解析 POI 详情数据"""
    data = extract_json_from_mcp_response(raw_response)
    if isinstance(data, dict):
        pois = data.get("pois", [])
        if isinstance(pois, list) and pois and isinstance(pois[0], dict):
            return pois[0]
        return data
    elif isinstance(data, list) and data and isinstance(data[0], dict):
        return data[0]
    return {}


def extract_photos_from_poi(poi_dict: Dict[str, Any]) -> List[str]:
    """提取 POI 关联的真实图片列表"""
    photos_raw = poi_dict.get("photos", [])
    photos = []
    if isinstance(photos_raw, list):
        for p in photos_raw:
            if isinstance(p, dict) and p.get("url"):
                photos.append(str(p["url"]))
            elif isinstance(p, str) and p.startswith("http"):
                photos.append(p)
    return photos


def poi_to_attraction_candidate(poi: Dict[str, Any]) -> Optional[AttractionCandidate]:
    """将原始 POI 字典转换为无伪造默认值的 AttractionCandidate"""
    poi_id = poi.get("id") or poi.get("poi_id")
    name = poi.get("name")
    if not poi_id or not name:
        return None
    loc = parse_location_str(poi.get("location"))
    if loc is None:
        return None

    biz_ext = poi.get("biz_ext") if isinstance(poi.get("biz_ext"), dict) else {}
    rating_val = biz_ext.get("rating") or poi.get("rating")
    rating: Optional[float] = None
    if rating_val is not None:
        try:
            rating = float(rating_val)
        except (ValueError, TypeError):
            rating = None

    cost_val = biz_ext.get("cost") or poi.get("cost")
    ticket_price: Optional[int] = None
    if cost_val is not None:
        try:
            ticket_price = int(float(cost_val))
        except (ValueError, TypeError):
            ticket_price = None

    tel = poi.get("tel")
    if isinstance(tel, list):
        tel = ",".join(tel) if tel else None
    elif not isinstance(tel, str) or not tel:
        tel = None

    return AttractionCandidate(
        poi_id=str(poi_id),
        name=str(name),
        type=str(poi.get("type", "景点")),
        address=str(poi.get("address", "") or ""),
        location=loc,
        rating=rating,
        photos=extract_photos_from_poi(poi),
        ticket_price=ticket_price,
        estimated_duration=None,
        description=str(poi.get("type", "")),
        tel=tel,
    )


def poi_to_hotel_candidate(poi: Dict[str, Any]) -> Optional[HotelCandidate]:
    """将原始 POI 字典转换为无伪造默认值的 HotelCandidate"""
    poi_id = poi.get("id") or poi.get("poi_id")
    name = poi.get("name")
    if not poi_id or not name:
        return None
    loc = parse_location_str(poi.get("location"))
    if loc is None:
        return None

    biz_ext = poi.get("biz_ext") if isinstance(poi.get("biz_ext"), dict) else {}
    rating_val = biz_ext.get("rating") or poi.get("rating")
    rating: Optional[str] = str(rating_val) if rating_val else None

    cost_val = biz_ext.get("cost") or poi.get("cost")
    estimated_cost: Optional[int] = None
    if cost_val is not None:
        try:
            estimated_cost = int(float(cost_val))
        except (ValueError, TypeError):
            estimated_cost = None

    return HotelCandidate(
        poi_id=str(poi_id),
        name=str(name),
        type=str(poi.get("type", "酒店")),
        address=str(poi.get("address", "") or ""),
        location=loc,
        rating=rating,
        price_range=None,
        estimated_cost=estimated_cost,
        distance=None,
    )


def poi_to_restaurant_candidate(poi: Dict[str, Any]) -> Optional[RestaurantCandidate]:
    """将原始 POI 字典转换为无伪造默认值的 RestaurantCandidate"""
    poi_id = poi.get("id") or poi.get("poi_id")
    name = poi.get("name")
    if not poi_id or not name:
        return None
    loc = parse_location_str(poi.get("location"))
    if loc is None:
        return None

    biz_ext = poi.get("biz_ext") if isinstance(poi.get("biz_ext"), dict) else {}
    rating_val = biz_ext.get("rating") or poi.get("rating")
    rating: Optional[float] = None
    if rating_val is not None:
        try:
            rating = float(rating_val)
        except (ValueError, TypeError):
            rating = None

    cost_val = biz_ext.get("cost") or poi.get("cost")
    estimated_cost: Optional[int] = None
    if cost_val is not None:
        try:
            estimated_cost = int(float(cost_val))
        except (ValueError, TypeError):
            estimated_cost = None

    return RestaurantCandidate(
        poi_id=str(poi_id),
        name=str(name),
        cuisine=str(poi.get("type", "特色餐饮")),
        address=str(poi.get("address", "") or ""),
        location=loc,
        rating=rating,
        estimated_cost=estimated_cost,
    )


# ============ 高德地图服务类 ============


class AmapService:
    """高德地图服务封装类 (支持健壮 MCP 响应解析与候选实体映射)"""

    def __init__(self):
        """初始化服务 (延迟加载 MCP 工具)"""
        self._mcp_tool: Optional[MCPTool] = None

    @property
    def mcp_tool(self) -> MCPTool:
        """获取 MCP 工具 (延迟初始化)"""
        if self._mcp_tool is None:
            self._mcp_tool = get_amap_mcp_tool()
        return self._mcp_tool

    def _call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> str:
        """底层统一 MCP 工具调用封装"""
        return self.mcp_tool.run({
            "action": "call_tool",
            "tool_name": tool_name,
            "arguments": arguments,
        })

    def search_poi(self, keywords: str, city: str, citylimit: bool = True) -> List[POIInfo]:
        """搜索 POI 并返回结构化 POIInfo 列表

        Args:
            keywords: 搜索关键词
            city: 城市
            citylimit: 是否限制在城市范围内

        Returns:
            POI 信息列表 (失败或无结果时返回空列表)
        """
        try:
            result = self._call_tool(
                tool_name="maps_text_search",
                arguments={
                    "keywords": keywords,
                    "city": city,
                    "citylimit": str(citylimit).lower(),
                },
            )
            return parse_poi_list(result)
        except Exception as e:
            logger.error(f"POI 搜索失败 (关键词: {keywords}, 城市: {city}): {str(e)}")
            return []

    def get_weather(self, city: str) -> List[WeatherInfo]:
        """查询指定城市的天气信息

        Args:
            city: 城市名称

        Returns:
            天气信息列表 (外部服务失败时返回空列表，绝不注入假天气)
        """
        try:
            result = self._call_tool(
                tool_name="maps_weather",
                arguments={"city": city},
            )
            return parse_weather_list(result)
        except Exception as e:
            logger.error(f"天气查询失败 (城市: {city}): {str(e)}")
            return []

    def plan_route(
        self,
        origin_address: str,
        destination_address: str,
        origin_city: Optional[str] = None,
        destination_city: Optional[str] = None,
        route_type: str = "walking",
    ) -> Optional[RouteInfo]:
        """规划两点之间的路线

        Args:
            origin_address: 起点地址
            destination_address: 终点地址
            origin_city: 起点城市
            destination_city: 终点城市
            route_type: 路线类型 (walking/driving/transit)

        Returns:
            RouteInfo 实体 (失败或不可达时返回 None)
        """
        try:
            tool_map = {
                "walking": "maps_direction_walking_by_address",
                "driving": "maps_direction_driving_by_address",
                "transit": "maps_direction_transit_integrated_by_address",
            }
            tool_name = tool_map.get(route_type, "maps_direction_walking_by_address")

            arguments = {
                "origin_address": origin_address,
                "destination_address": destination_address,
            }
            if origin_city:
                arguments["origin_city"] = origin_city
            if destination_city:
                arguments["destination_city"] = destination_city

            result = self._call_tool(tool_name=tool_name, arguments=arguments)
            return parse_route_info(result, route_type=route_type)
        except Exception as e:
            logger.error(
                f"路线规划失败 ({origin_address} -> {destination_address}, 类型: {route_type}): {str(e)}"
            )
            return None

    def geocode(self, address: str, city: Optional[str] = None) -> Optional[Location]:
        """地理编码 (地址转坐标)"""
        try:
            arguments = {"address": address}
            if city:
                arguments["city"] = city

            result = self._call_tool(tool_name="maps_geo", arguments=arguments)
            return parse_geocode(result)
        except Exception as e:
            logger.error(f"地理编码失败 (地址: {address}, 城市: {city}): {str(e)}")
            return None

    def get_poi_detail(self, poi_id: str) -> Dict[str, Any]:
        """获取 POI 详情信息"""
        try:
            result = self._call_tool(
                tool_name="maps_search_detail",
                arguments={"id": poi_id},
            )
            return parse_poi_detail(result)
        except Exception as e:
            logger.error(f"获取 POI 详情失败 (ID: {poi_id}): {str(e)}")
            return {}

    # ============ 领域候选检索扩展 (供 LangGraph 确定性节点使用) ============

    def search_attraction_candidates(
        self, keywords: str, city: str, citylimit: bool = True
    ) -> List[AttractionCandidate]:
        """检索景点候选池 (严格去虚假默认值)"""
        try:
            result = self._call_tool(
                tool_name="maps_text_search",
                arguments={
                    "keywords": keywords,
                    "city": city,
                    "citylimit": str(citylimit).lower(),
                },
            )
            data = extract_json_from_mcp_response(result)
            pois_raw = []
            if isinstance(data, dict):
                pois_raw = data.get("pois", [])
            elif isinstance(data, list):
                pois_raw = data

            candidates: List[AttractionCandidate] = []
            for p in pois_raw:
                if isinstance(p, dict):
                    cand = poi_to_attraction_candidate(p)
                    if cand:
                        candidates.append(cand)
            return candidates
        except Exception as e:
            logger.error(f"检索景点候选失败 ({keywords}): {str(e)}")
            return []

    def search_hotel_candidates(
        self, keywords: str, city: str, citylimit: bool = True
    ) -> List[HotelCandidate]:
        """检索酒店候选池 (严格去虚假默认值)"""
        try:
            result = self._call_tool(
                tool_name="maps_text_search",
                arguments={
                    "keywords": keywords,
                    "city": city,
                    "citylimit": str(citylimit).lower(),
                },
            )
            data = extract_json_from_mcp_response(result)
            pois_raw = []
            if isinstance(data, dict):
                pois_raw = data.get("pois", [])
            elif isinstance(data, list):
                pois_raw = data

            candidates: List[HotelCandidate] = []
            for p in pois_raw:
                if isinstance(p, dict):
                    cand = poi_to_hotel_candidate(p)
                    if cand:
                        candidates.append(cand)
            return candidates
        except Exception as e:
            logger.error(f"检索酒店候选失败 ({keywords}): {str(e)}")
            return []

    def search_restaurant_candidates(
        self, keywords: str, city: str, citylimit: bool = True
    ) -> List[RestaurantCandidate]:
        """检索餐饮候选池 (真实餐饮，拒绝凭空捏造)"""
        try:
            result = self._call_tool(
                tool_name="maps_text_search",
                arguments={
                    "keywords": keywords,
                    "city": city,
                    "citylimit": str(citylimit).lower(),
                },
            )
            data = extract_json_from_mcp_response(result)
            pois_raw = []
            if isinstance(data, dict):
                pois_raw = data.get("pois", [])
            elif isinstance(data, list):
                pois_raw = data

            candidates: List[RestaurantCandidate] = []
            for p in pois_raw:
                if isinstance(p, dict):
                    cand = poi_to_restaurant_candidate(p)
                    if cand:
                        candidates.append(cand)
            return candidates
        except Exception as e:
            logger.error(f"检索餐饮候选失败 ({keywords}): {str(e)}")
            return []


# 全局单例服务
_amap_service: Optional[AmapService] = None


def get_amap_service() -> AmapService:
    """获取高德地图服务实例 (单例模式)"""
    global _amap_service

    if _amap_service is None:
        _amap_service = AmapService()

    return _amap_service
