# 基于 LangChain 的旅游知识库对话式 RAG 助手系统设计规范

## 1. 概述与目标

### 1.1 背景
本项目已具备基于 LangGraph 状态图与高德地图 MCP 的多天行程规划能力。为进一步提升用户的交互体验，本项目新增“支持对话式交互，基于 RAG 检索旅游知识库回答用户问题”的全局助手能力。

### 1.2 目标
1. **权威知识库检索（RAG）**：以 `resource/tourism_knowledge_documents` 下文化和旅游部等官方发布的 15 份法规、安全手册、合同规范及标准文件为核心底座，并支持本地扩展 Markdown/TXT 旅游攻略。
2. **现代 LangChain 架构**：采用 LangChain 官方最新标准体系（`langchain-core`、`langchain-openai`、`langchain-chroma`、`langchain-text-splitters`）替代零散自定义脚本，统一检索器规范。
3. **Agentic RAG 交互模式**：将知识库检索封装为标准 Tool，由大模型自适应决定何时检索，避免无效检索造成的性能损耗与噪声注入。
4. **当前行程上下文联动**：助手能感知用户在前端正在浏览或刚规划好的行程详情（城市、天数、POI 列表、预算等），提供结合实际行程的避坑、维权与安全咨询。
5. **打字机流式体验（SSE）**：后端通过 Server-Sent Events 流式输出 Token 及知识库引用来源，前端提供常驻全局悬浮对话组件。

---

## 2. 知识库数据资产与处理流水线（Ingestion Pipeline）

### 2.1 知识源资产定义
- **核心数据目录**：`resource/tourism_knowledge_documents/`
  - 12 份官方 PDF（包括《旅游法》、《旅游投诉处理办法》、《旅游安全实务手册》、景区与住宿服务规范等）。
  - 3 份官方示范合同 DOC/DOCX（境内旅游、一日游、研学旅游合同）。
  - 配套元数据文件：`resource/tourism_kb_sources.json`。
- **自定义攻略目录**：`backend/data/knowledge/`（预留给开发者或用户自由放入 `.md`、`.txt` 格式的城市避坑与美食攻略）。

### 2.2 文档加载与元数据注入 (`app/rag/loader.py`)
1. **PDF 文档解析**：采用 `pypdf` 进行文本提取，按页记录页码（`page: int`）。
2. **DOC 文档解析**：采用 `docx2txt` 解析 Word 示范文本。
3. **元数据关联注入**：读取 `tourism_kb_sources.json`，根据文件名映射并注入关键元数据：
   - `doc_id`: 整数标识
   - `title`: 文档正式中文标题（例如："中华人民共和国旅游法（2018年修正）"）
   - `category`: 文档分类（"旅游法规"、"旅游安全"、"旅游合同"、"景区服务"等）
   - `year`: 发布年份
   - `source`: 官方出处机构
   - `page`: 所在页码（对于 PDF）

### 2.3 智能文本切分 (`app/rag/splitter.py`)
- 使用 `RecursiveCharacterTextSplitter`：
  - `chunk_size = 600`（中文字符）
  - `chunk_overlap = 80`
  - 分隔符优先级：`["\n\n", "\n", "。", "！", "？", "；", " ", ""]`
  - `add_start_index = True`，记录字符偏移。
- 自动将元数据标题（如 `【中华人民共和国旅游法 - 第3章】`）作为语义前缀融入切片，提升检索匹配精度。

### 2.4 增量索引与构建脚本 (`app/rag/ingest.py`)
- 提供命令行维护指令：`python -m app.rag.ingest`
- **增量哈希检测**：在 `backend/data/vector_store/.index_cache.json` 中维护各源文件的 MD5 哈希戳。文件无变化时直接跳过，仅当文件新增或内容修改时才调用 Embedding 模型，避免不必要的 Token 消耗与构建耗时。

---

## 3. 向量存储与检索系统设计

### 3.1 向量存储规范 (`app/rag/vector_store.py`)
- **向量库选型**：`langchain_chroma.Chroma`。
- **持久化路径**：`backend/data/vector_store/`（自动在 `.gitignore` 中忽略向量数据库文件）。
- **Embedding 模型配置**：
  - 复用现有的 OpenAI 兼容网关，采用 `langchain_openai.OpenAIEmbeddings`。
  - 支持在 `app/config.py` 中配置 `embedding_model`（默认 `text-embedding-3-small`，支持自由调整为其他 OpenAI 兼容的 embedding 模型）。
- **集合名称（Collection Name）**：`travel_knowledge`。

### 3.2 检索策略与 Tool 封装
- 检索器参数：
  - 搜索模式：支持余弦相似度检索或 MMR（最大边际相关性，用于去重提升多样性）。
  - `k = 4`（召回最相关的 4 个切片）。
- **封装为 LangChain Tool**：
  ```python
  @tool
  def search_tourism_knowledge(query: str) -> str:
      """检索文化和旅游部官方旅游法规、投诉办法、安全手册、合同示范文本及避坑指南。
      适合回答旅游纠纷索赔、跟团游退改、安全事故应对、景区服务规范等专业问题。"""
  ```
  检索返回格式经过结构化拼接，包含原切片正文、所属文档标题、分类及出处。

---

## 4. 对话引擎架构设计（Conversational RAG Engine）

### 4.1 编排架构 (`app/rag/agent.py`)
采用 LangChain 官方最新的 **Agentic RAG** 模式：
1. **模型实例化**：采用 `langchain_openai.ChatOpenAI`，继承现有的 `openai_api_key`、`openai_base_url`、`openai_model`。
2. **工具绑定**：将 `search_tourism_knowledge` 工具绑定至聊天模型（`.bind_tools`）。
3. **会话状态流转**：
   - 采用标准 `MessagesState`，包含 `messages` 数组。
   - 使用轻量 `InMemorySaver`（或基于会话 ID 的持久记忆），每个用户/页面对应一个 `thread_id`（`conversation_id`）。
4. **决策循环**：
   - 用户输入普通闲聊（如“你好”、“你是谁”）-> 直接生成友好回答，不触发检索。
   - 用户询问专业知识/维权/合同/安全规则 -> 模型自主调用检索工具，获取权威条款后综合生成回答。

### 4.2 行程上下文注入（Trip Context Enrichment）
当用户正在查看某个规划好的行程并提问时，前端将轻量行程摘要传递给后端：
- 摘要包含：目的地城市、天数、主要游览 POI 名称、总预算区间。
- 系统提示词动态追加：
  ```
  【当前行程背景（用户正在浏览）】
  目的地：{city}
  天数：{days}天
  涉及景点/地点：{poi_list}
  如果用户的提问与当前行程相关，请结合当前行程进行分析解答；如果是独立问题，请专注回答用户所问。
  ```

---

## 5. 后端 API 接口设计 (`app/api/routes/chat.py`)

### 5.1 流式对话接口 (`POST /api/chat/stream`)
- **请求体（JSON）**：
  ```json
  {
    "message": "如果旅行社中途强制要求加自费项目，我该如何维权？",
    "conversation_id": "conv-uuid-1234",
    "current_trip_context": {
      "destination": "西安",
      "days": 3,
      "poi_names": ["秦始皇帝陵博物院", "大雁塔", "回民街"]
    }
  }
  ```
- **响应格式**：`text/event-stream`（Server-Sent Events）。
- **事件结构**：
  - `data: {"type": "tool_start", "content": "正在检索官方旅游法规知识库..."}`
  - `data: {"type": "token", "content": "依据"}`
  - `data: {"type": "token", "content": "《中华人民共和国旅游法》"}`
  - `data: {"type": "sources", "content": [{"title": "中华人民共和国旅游法（2018年修正）", "category": "旅游法规", "page": 12}]}`
  - `data: {"type": "done"}`

### 5.2 知识库状态接口 (`GET /api/rag/status`)
- 返回知识库当前统计数据：
  ```json
  {
    "status": "ready",
    "indexed_docs_count": 15,
    "total_chunks_count": 486,
    "collection_name": "travel_knowledge"
  }
  ```

---

## 6. 前端全局悬浮组件设计 (`frontend/src/components/ChatAssistant.vue`)

### 6.1 UI 与交互布局
- **入口**：在页面右下角常驻圆形悬浮球（带指南针/机器人图标），点击展开对话抽屉/气泡窗口（宽 380px，高 540px）。
- **挂载点**：直接挂载在 `frontend/src/App.vue` 根节点，全站所有页面均可一键唤起。
- **特性**：
  - **打字机动态展示**：接收 SSE 事件流，实时渲染 Markdown 富文本回答。
  - **工具状态提示**：检索中展示“📚 正在查阅旅游知识库...”加载气泡。
  - **来源引用（Citations）**：回答底部折叠展开“参考资料来源”，点击可查看依据的法规/标准名称及所属分类。
  - **快捷预置提问（Quick Prompts）**：首次打开展示常见问题气泡（如“跟团游被强制购物如何维权？”、“高山徒步有哪些防失温常识？”、“酒店在线预订后被临时取消怎么办？”）。

### 6.2 状态与行程上下文联动
- 组件监听 Pinia 或当前页面的行程状态。
- 如果用户位于 `/result` 路由，自动提取页面顶部的城市与已生成的日程概览传入请求；离开结果页时则仅以通用旅游顾问模式交互。

---

## 7. 依赖项与配置调整

### 7.1 后端依赖 (`backend/requirements.txt`)
新增以下依赖：
```
# LangChain 与 RAG 核心支持
langchain>=0.3.0
langchain-core>=0.3.0
langchain-openai>=0.2.0
langchain-chroma>=0.1.4
langchain-text-splitters>=0.3.0

# 文档格式解析支持
pypdf>=5.0.0
docx2txt>=0.8
```

### 7.2 配置扩展 (`backend/app/config.py`)
在 `Settings` 中新增：
```python
embedding_model: str = "text-embedding-3-small"
vector_store_dir: str = "data/vector_store"
```

---

## 8. 测试与验证计划

1. **知识库切分与入库测试 (`tests/test_rag_ingest.py`)**：
   - 验证 `pypdf` 和 `docx2txt` 是否正确解析 15 份官方文档。
   - 验证 `RecursiveCharacterTextSplitter` 是否正确注入元数据（标题、分类、年份、页码）。
   - 验证向量切片成功持久化写入本地 Chroma 数据库。
2. **检索器工具测试 (`tests/test_rag_retriever.py`)**：
   - 模拟查询“跟团游强制购物违规”，验证召回结果包含《旅游法》第35条相关切片，且相关性排名正确。
3. **Agent 对话与流式输出测试 (`tests/test_chat_stream.py`)**：
   - 测试普通打招呼（不触发检索工具）。
   - 测试法规问答（正确触发检索工具并综合输出）。
   - 验证 SSE 数据流的报文格式完整合规。
4. **前端交互与端到端验证**：
   - 启动本地前端开发服务器，验证悬浮球打开、折叠、多轮提问、打字机渲染、来源展示。
   - 在行程结果页提问，验证当前行程上下文被正确引用。
