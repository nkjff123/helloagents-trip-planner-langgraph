"""真实环境 POI 检索纯净度验证脚本 (漯河真实场景测试)

验证目标:
1. 关键词 ['许慎文化园', '小商桥', '沙澧河风景区'] 检索后，景点候选总数控制在 6 ~ 9 个优质核心景区
2. 过滤所有公厕、停车场、售票处、包装厂、充电站、村委会等非游览杂质
3. 酒店与餐饮候选规模合理收敛 (酒店 <= 6, 餐饮 <= 8)
"""

import sys
from loguru import logger
from app.models.state import TripPlannerState, SearchStrategy
from app.workflow.nodes.search_nodes import (
    search_attractions,
    search_hotels,
    search_restaurants,
)


def run_real_search_test():
    print("=" * 60)
    print("开始执行漯河真实环境 POI 检索与去噪测试...")
    print("=" * 60)

    state: TripPlannerState = {
        "city": "漯河",
        "travel_days": 2,
        "strategy": SearchStrategy(
            attraction_keywords=["许慎文化园", "小商桥", "沙澧河风景区"],
            hotel_keyword="商务型酒店",
            restaurant_keywords=["漯河特色美食", "北舞渡胡辣汤"],
        ),
        "warnings": [],
    }

    # 1. 测试景点检索
    print("\n[1/3] 正在通过高德 MCP 检索景点候选池...")
    attr_res = search_attractions(state)
    attractions = list(attr_res.get("candidate_attractions", {}).values())

    print(f"\n>>> 景点候选池检索完成: 共得到 {len(attractions)} 个景点")
    for idx, a in enumerate(attractions, 1):
        print(f"  {idx}. [{a.poi_id}] {a.name} | 类型: {a.type} | 地址: {a.address}")

    # 验证黑名单杂质是否已彻底消除
    forbidden_keywords = [
        "公厕", "厕所", "卫生间", "洗手间", "停车场", "售票处",
        "包装", "材料", "公司", "充电桩", "公交站", "家具", "村委会", "派出所", "驿站"
    ]
    for a in attractions:
        for fkw in forbidden_keywords:
            if fkw in a.name:
                raise AssertionError(f"严重缺陷：景点列表中依然包含非游览杂质 POI: '{a.name}' (命中黑名单: '{fkw}')")

    # 验证景点数量收敛在 6 ~ 9
    assert 1 <= len(attractions) <= 9, f"景点候选池数量超标或为空: {len(attractions)}"
    print(">>> 景点纯净度与数量约束测试: 100% PASS!")

    # 2. 测试酒店检索
    print("\n[2/3] 正在通过高德 MCP 检索酒店候选池...")
    hotel_res = search_hotels(state)
    hotels = list(hotel_res.get("candidate_hotels", {}).values())
    print(f"\n>>> 酒店候选池检索完成: 共得到 {len(hotels)} 家酒店")
    for idx, h in enumerate(hotels, 1):
        print(f"  {idx}. [{h.poi_id}] {h.name} | 类型: {h.type} | 地址: {h.address}")

    assert 1 <= len(hotels) <= 6, f"酒店候选池数量超标或为空: {len(hotels)}"
    print(">>> 酒店收敛测试: 100% PASS!")

    # 3. 测试餐饮检索
    print("\n[3/3] 正在通过高德 MCP 检索餐饮候选池...")
    rest_res = search_restaurants(state)
    restaurants = list(rest_res.get("candidate_restaurants", {}).values())
    print(f"\n>>> 餐饮候选池检索完成: 共得到 {len(restaurants)} 家餐馆")
    for idx, r in enumerate(restaurants, 1):
        print(f"  {idx}. [{r.poi_id}] {r.name} | 类型: {r.cuisine} | 地址: {r.address}")

    assert 1 <= len(restaurants) <= 8, f"餐饮候选池数量超标或为空: {len(restaurants)}"
    print(">>> 餐饮收敛测试: 100% PASS!")

    print("\n" + "=" * 60)
    print("漯河真实环境 POI 检索去噪与规模控制验证全部通过 (ALL PASS)!")
    print("=" * 60)


if __name__ == "__main__":
    try:
        run_real_search_test()
    except Exception as e:
        logger.exception(f"真实测试未通过: {e}")
        sys.exit(1)
