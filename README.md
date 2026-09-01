# HelloAgents 智能旅行规划助手 🌍✈️

> 基于 **LangGraph StateGraph** 状态图工作流与高德地图 MCP 真实服务构建的企业级智能多日旅行规划系统。

---

## 🌟 架构升级与核心特性

本项目已全面升级为基于 **LangGraph** 的确定性与大模型推理分离架构，彻底清除了旧版中大模型经纬度幻觉、硬编码伪造数据兜底及脆弱的字符串正则工具调用，构建了高可靠性、真实实体锚定与精准预算交付闭环：

- 🗺️ **真实实体锚定与还原 (Grounding & Rehydration)**: LLM 仅负责语义规划与日程编排，严格仅输出 `poi_id` 引用；真实经纬度坐标 (GCJ-02)、官方地址、门票与评分由确定性节点 100% 从高德真实候选池还原，杜绝任何地理位置漂移。
- ⚡ **解耦并行检索与 Barrier 严格同步**: 搜索策略规划后扇出至三路独立检索（景点、酒店、餐厅）与天气查询，利用 LangGraph 边缘汇聚机制严格同步等待所有候选就绪。
- 🛡️ **自愈修补循环与真实性强校验 (Self-Healing Loop)**: 规划结果必须通过真实候选池校验与经纬度零漂移校验；若未通过则携带定向错误反馈进入修补循环（最多 2 次），修补超限则显式拒绝，**绝不返回硬编码虚假数据**。
- 💰 **确定性精准数学预算**: 门票、住宿、餐饮与交通预算由纯 Python 数学节点累加计算，确保 `total == sum(items)`，消除大模型算术失误。
- 🌤️ **透明天气策略**: 针对查询超时或无返回的情况透明呈现空列表降级，杜绝无依据捏造假天气。
- 🎨 **现代化交互体验**: Vue 3 + TypeScript + Vite + Ant Design Vue，集成高德地图 JS API 路线轨迹可视化与 PDF/图片高清导出。

---

## 📊 新旧架构对比

| 维度 | 旧版架构 (HelloAgents SimpleAgent) | 新版架构 (LangGraph StateGraph) |
| :--- | :--- | :--- |
| **编排引擎** | 4 个串行 SimpleAgent 自由文本传递 | 强类型状态图 (`TripPlannerState`)，明确确定性与推理分离 |
| **工具调用** | 文本正则匹配 `[TOOL_CALL:...]`，极易格式崩坏 | 解耦确定性 Python MCP 节点与 Pydantic 结构化输出协议 |
| **实体真实性** | 大模型直接输出坐标，频繁地理漂移或幻觉 | **Grounding by POI-ID**: 模型仅产出 ID，官方数据 100% 还原 |
| **异常处理** | 失败时回退至固定的虚假北京坐标假数据 (`_create_fallback_plan`) | **自愈修复环路**: 针对性错误反馈修补；超限显式报错拒绝假数据 |
| **并发性能** | 串行执行检索，耗时长 | 天气预报与三路检索解耦扇出并发，Barrier 机制安全汇聚 |
| **费用计算** | 大模型直接生成各项数字，加总极易不吻合 | 纯 Python 确定性算术加总，数学保证绝对精准一致 |

---

## 🏗️ 系统拓扑与工作流

```text
               ┌───────────────────────────┐
               │           START           │
               └─────────────┬─────────────┘
                             │
            ┌────────────────▼────────────────┐
            │   normalize_and_validate_input  │ (城市名称去缀规范化/严格日期天数校验)
            └────────┬────────────────────────┘
                     │
          [校验失败] │              [校验成功]
          ┌──────────┴────────┐   ┌──────────────────────────┐
          │                   │   │                          │
          ▼                   ▼   ▼                          ▼
   ┌──────────────┐     ┌───────────────────┐     ┌───────────────────────────────┐
   │ failure_node │     │ fetch_weather_node│     │ generate_search_strategy_node │
   └──────┬───────┘     └─────────┬─────────┘     └───────────────┬───────────────┘
          │                       │                               │ (扇出三路并行检索)
          │                       │                 ┌─────────────┼─────────────┐
          │                       │                 ▼             ▼             ▼
          │                       │         ┌────────────┐ ┌────────────┐ ┌─────────────┐
          │                       │         │search_attrs│ │search_hotel│ │search_restau│
          │                       │         └─────┬──────┘ └─────┬──────┘ └──────┬──────┘
          │                       │               └──────────────┼───────────────┘
          │                       │                              │
          │                       │                              ▼ [Barrier 汇聚同步]
          │                       │                   ┌───────────────────────┐
          │                       │                   │curate_attractions_node│ (初筛并过滤伪造 ID)
          │                       │                   └──────────┬────────────┘
          │                       │                              │
          │                       └───────────────┬──────────────┘
          │                                       │ [Barrier 汇聚同步]
          │                                       ▼
          │                         ┌───────────────────────────┐
          │                         │ synthesize_itinerary_node │ (仅引用真实 POI ID 编排骨架)
          │                         └─────────────┬─────────────┘
          │                                       │
          │                         ┌─────────────▼─────────────┐
          │                         │  rehydrate_entities_node  │◄─────────────────────┐
          │                         └─────────────┬─────────────┘                      │
          │                                       │                                    │
          │                         ┌─────────────▼─────────────┐                      │
          │                         │     enrich_routes_node    │                      │
          │                         └─────────────┬─────────────┘                      │
          │                                       │                                    │
          │                         ┌─────────────▼─────────────┐                      │
          │                         │   calculate_budget_node   │                      │
          │                         └─────────────┬─────────────┘                      │
          │                                       │                                    │
          │                         ┌─────────────▼─────────────┐                      │
          │                         │  validate_grounding_node  │                      │
          │                         └─────────────┬─────────────┘                      │
          │                                       │                                    │
          │                 ┌─────────────────────┴──────────────────┐                 │
          │                 │                                        │                 │
          │          [通过] │                   [未通过且修补次数 < 2] │ [修补次数 >= 2] │
          │                 ▼                                        ▼                 ▼
          │          ┌─────────────┐                      ┌────────────────────┐       │
          │          │     END     │                      │repair_skeleton_node├───────┘
          │          └─────────────┘                      └────────────────────┘
          ▼
   ┌─────────────┐
   │     END     │ (返回显式失败原因)
   └─────────────┘
```

---

## 📁 项目目录结构

```
helloagents-trip-planner-langgraph/
├── backend/                              # 后端服务源码
│   ├── app/
│   │   ├── agents/                       # 兼容适配层
│   │   │   └── trip_planner_agent.py     # MultiAgentTripPlanner (委托至 LangGraph)
│   │   ├── api/                          # FastAPI 接口层
│   │   │   ├── main.py                   # 启动入口与中间件配置
│   │   │   └── routes/
│   │   │       ├── trip.py               # /api/trip/plan 与 /api/trip/health
│   │   │       ├── map.py                # 地图服务路由
│   │   │       └── poi.py                # POI 详情路由
│   │   ├── models/                       # 数据模型层
│   │   │   ├── schemas.py                # 请求/响应 Pydantic 模型
│   │   │   └── state.py                  # 候选领域模型与 LangGraph 全局状态
│   │   ├── services/                     # 基础服务层
│   │   │   ├── amap_service.py           # 高德地图 MCP 解析与候选映射封装
│   │   │   ├── llm_service.py            # Pydantic 结构化输出支持与模型适配
│   │   │   └── unsplash_service.py       # 图片检索服务
│   │   ├── workflow/                     # LangGraph 核心工作流
│   │   │   ├── graph.py                  # StateGraph 拓扑构建与编译
│   │   │   ├── prompts.py                # 实体隔离 Prompt 模板库
│   │   │   └── nodes/                    # 细分工作流节点
│   │   │       ├── input_nodes.py        # 前置输入规范化与参数强校验
│   │   │       ├── search_nodes.py       # 解耦候选检索与天气查询
│   │   │       ├── reasoning_nodes.py    # 策略规划、初筛、骨架编排与自愈修补
│   │   │       └── postprocess_nodes.py  # 实体还原、路线丰富、精准预算与防篡改校验
│   │   └── config.py                     # 全局配置管理
│   ├── tests/                            # 自动化测试套件 (44 项单测与端到端测试)
│   │   ├── test_schemas.py               # 状态模型与 Reducer 测试
│   │   ├── test_amap_parser.py           # 高德 MCP 解析与候选转换测试
│   │   ├── test_deterministic_nodes.py   # 确定性后处理节点测试
│   │   ├── test_search_nodes.py          # 检索与天气节点测试
│   │   ├── test_reasoning_nodes.py       # LLM 推理节点测试
│   │   ├── test_workflow_e2e.py          # LangGraph 完整端到端测试
│   │   └── test_api_trip.py              # API 端点与兼容层测试
│   ├── run.py                            # 后端运行脚本
│   ├── requirements.txt                  # Python 依赖清单
│   └── .env.example                      # 后端环境变量模板
├── frontend/                             # 前端应用源码
│   ├── src/
│   │   ├── components/                   # 公共组件 (地图、行程卡片等)
│   │   ├── services/                     # Axios API 客户端
│   │   ├── types/                        # 前后端对齐 TypeScript 接口定义
│   │   └── views/
│   │       ├── Home.vue                  # 旅行配置表单页
│   │       └── Result.vue                # 规划成果展示、高德地图轨迹交互与导出页
│   ├── package.json
│   └── vite.config.ts
├── memory-bank/                          # 系统设计与重构知识库
└── README.md
```

---

## 🚀 快速启动指南

### 1. 前提环境要求

- **Python**: `3.10` 及以上版本 (推荐使用 Anaconda 或 venv)
- **Node.js**: `18.0.0` 及以上版本
- **包管理工具**: `npm` 或 `pnpm`
- **高德地图开放平台密钥**:
  - **Web 服务 API Key**: 用于后端高德 MCP 候选检索与路线规划 (`AMAP_API_KEY`)
  - **Web 端 JS API Key & 安全密钥**: 用于前端浏览器地图打点与路线渲染 (`VITE_AMAP_WEB_KEY`, `VITE_AMAP_WEB_JS_KEY`)
- **LLM API Key**: 任何兼容 OpenAI 协议的模型提供商 (如 DeepSeek, OpenAI, Qwen 等)
- **uv / uvx**: 用于运行高德地图 MCP 服务 (`uvx amap-mcp-server`)，可通过 `pip install uv` 自动获得

---

### 2. 后端启动步骤

#### 步骤 2.1：进入后端目录并配置虚拟环境
```bash
cd backend

# 创建并激活虚拟环境 (二选一)
# 方式 A (venv):
python -m venv venv
# Linux/macOS:
source venv/bin/activate
# Windows:
venv\Scripts\activate

# 方式 B (conda):
# conda create -n agent python=3.11 -y
# conda activate agent
```

#### 步骤 2.2：安装依赖
```bash
pip install -r requirements.txt
```

#### 步骤 2.3：配置环境变量
复制环境变量样例文件并填入真实密钥：
```bash
cp .env.example .env
```
编辑 `backend/.env`，确保以下核心项已正确配置：
```ini
# LLM 模型配置 (以 DeepSeek 为例)
LLM_MODEL_ID=deepseek-chat
LLM_API_KEY=sk-your-llm-api-key
LLM_BASE_URL=https://api.deepseek.com/v1
LLM_TIMEOUT=60

# 高德地图 Web 服务 Key (必须申请 Web服务类型)
AMAP_API_KEY=your_amap_web_service_key

# 运行端口与跨域配置
HOST=0.0.0.0
PORT=8000
CORS_ORIGINS=http://localhost:5173,http://localhost:3000
LOG_LEVEL=INFO
```

#### 步骤 2.4：启动后端服务
您可以通过以下任意一种方式启动后端服务：
```bash
# 方式一：使用 uvicorn
uvicorn app.api.main:app --reload --host 0.0.0.0 --port 8000

# 方式二：使用内置启动脚本
python run.py
```
启动成功后，可在浏览器访问 API 交互文档：
- **Swagger UI 交互文档**: `http://localhost:8000/docs`
- **ReDoc 文档**: `http://localhost:8000/redoc`
- **工作流健康检查**: `http://localhost:8000/api/trip/health`

#### 步骤 2.5：运行自动化测试 (可选，验证环境完整性)
```bash
python -m unittest discover
```
预期输出：`Ran 44 tests ... OK`。

---

### 3. 前端启动步骤

#### 步骤 3.1：进入前端目录并安装依赖
在新的终端窗口中：
```bash
cd frontend
npm install
```

#### 步骤 3.2：配置前端环境变量
```bash
cp .env.example .env
```
编辑 `frontend/.env`：
```ini
# 后端 API 地址 (本地开发默认即可)
VITE_API_BASE_URL=http://localhost:8000

# 高德地图 Web JS API Key
VITE_AMAP_WEB_KEY=your_amap_web_key
VITE_AMAP_WEB_JS_KEY=your_amap_web_js_key
```

#### 步骤 3.3：启动开发服务器
```bash
npm run dev
```
控制台将输出服务地址，在浏览器中打开：
```
  ➜  Local:   http://localhost:5173/
```

#### 步骤 3.4：生产环境构建 (可选)
```bash
npm run build
```
将执行 `vue-tsc && vite build`，产物输出至 `frontend/dist/`。

---

## 📖 使用指南

1. **输入旅行需求**:
   - 打开首页 `http://localhost:5173`。
   - 输入目标城市（如：`杭州`、`成都`、`北京`）。
   - 选择出行起止日期及游玩天数。
   - 选择意向交通（公共交通/出租车/租车自驾/步行）。
   - 选择住宿档次（经济型酒店/舒适型酒店/高档豪华酒店/特色民宿）。
   - 勾选旅行偏好标签（自然风光、历史古迹、美食品尝、拍照打卡等）。
   - 可在自由文本中补充特殊诉求（例如：“多安排当地老字号小吃，避开人流密集的网红店”）。

2. **生成与自愈校验**:
   - 点击 **“🚀 开始定制旅行计划”**。
   - 后端 LangGraph 引擎执行策略规划、高德多路候选召回、景点精选与日程编排。
   - 自动执行坐标零漂移防篡改校验，若发现异常自动触发定向自愈修补。

3. **交互与成果导出**:
   - **行程概览**: 查看多日主题、总体贴士与穿衣防晒防雨指南。
   - **高德地图交互**: 查看每日精选景点分布，高德路线规划打点连线，支持地图缩放与点位详情联动。
   - **每日日程明细**: 查看早中晚三餐安排、推荐景点官方地址与建议游玩时长、住宿酒店。
   - **费用明细**: 查看门票、住宿、餐饮与交通的精准数学汇总。
   - **导出计划**: 支持一键导出为高清长图或多页 PDF 文件，方便离线携带。

---

## 🛠️ 常见问题排查 (FAQ)

### Q1: 后端启动报错 `ImportError: cannot import name 'StateGraph' from 'langgraph.graph'`
**A**: 请确保激活了正确的 Python 虚拟环境，并执行了 `pip install -r requirements.txt`。可以通过 `pip show langgraph` 确认版本需 `>=0.2.0`。

### Q2: 路线规划或高德检索失败
**A**: 
1. 检查 `backend/.env` 中的 `AMAP_API_KEY` 是否有效，并且开通了**Web 服务 API**权限（非 Web 端 JS API）。
2. 高德 MCP 服务基于 `uvx amap-mcp-server` 运行，请确保本地可通过终端执行 `uv` 命令（通过 `pip install uv` 自动获得）。
3. 本项目已做透明降级，若由于配额用尽或网络波动导致检索部分缺失，系统将以可用候选池为准安全生成，或显式给出具体错误反馈。

### Q3: 前端地图无法正常显示或标记点偏移
**A**: 
1. 检查 `frontend/.env` 中的 `VITE_AMAP_WEB_KEY` 是否属于**Web 端 (JS API)** 类型。
2. 本项目后端输出的所有坐标均为高德官方真实 GCJ-02 坐标，与高德 JS API 完全对齐，无需二次坐标系纠偏转换。

---

## 📜 开源许可

本项目遵循 [CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/) 许可协议。

---

## 🙏 致谢

- [LangGraph](https://github.com/langchain-ai/langgraph) - 业内领先的有状态多智能体图工作流编排框架
- [HelloAgents](https://github.com/datawhalechina/Hello-Agents) - 优秀的智能体开源教程体系
- [高德地图开放平台](https://lbs.amap.com/) - 权威精确的地理信息与路线规划服务
- [amap-mcp-server](https://github.com/sugarforever/amap-mcp-server) - 优秀的高德地图 MCP 适配服务

---

**HelloAgents 智能旅行规划助手** - 用确定性守护真实，让大模型赋能每一次美好出行 🌈
