# 前端

Vue 3、TypeScript、Ant Design Vue 与 Vite，沿用现有旅行规划 API。

## 开发与验证

```sh
npm install
npm run dev
npm run build
npm test
```

构建沿用原有 Node.js 18+ 要求。单元测试直接加载 TypeScript，需 Node.js 22.6+；本次在 Node.js 24.19.0 验证。

## 页面与模块

- `App.vue`、`styles.css`：应用导航、Ant Design 主题、共享样式与响应式规则。
- `views/Home.vue`：目的地、日期、交通、住宿、偏好和补充要求；调用真实规划接口。
- `views/Result.vue`：会话恢复、日期选择、编辑保存/取消、景点顺序与导出调度。
- `components/ItineraryDay.vue`：景点时间线、餐饮和住宿；通过事件向结果页提交排序/删除操作。
- `components/TripMap.vue`：高德 SDK、当日景点标记与顺序示意、加载失败后的重试和销毁。
- `components/TripSummary.vue`：预算和真实天气信息。
- `components/AppIcon.vue`：统一 24px viewBox、1.7px 线宽的 SVG 图标。
- `utils/trip.ts`：日期范围、会话数据检查和删除景点后的预算同步。
- `utils/exportTrip.ts`、`utils/pagination.ts`：统一桌面排版的长图和多页 PDF；保护标题、内容行和日期标题的分页边界。

## 视觉规范

白色背景 `#ffffff`，主色 `#184c3c`，正文 `#1f2925`，辅助文字 `#747c85`，分隔线 `#e6ebe7`。面板采用开放式布局和细分隔线；表单控件、选中标签与图标共用主题。

桌面首页采用表单与山水图双列；手机优先显示完整表单。结果页在窄屏改为单列，景点、餐厅地址和完整天气信息保留。日期标签支持左右方向键及 Home/End。动效遵循 `prefers-reduced-motion`。

## 服务与数据

- 按 `.env.example` 配置后端地址和 `VITE_AMAP_WEB_JS_KEY`。未配置地图时显示明确的不可用提示。
- 景点图片优先使用响应中的 `image_url`，否则通过统一 API 客户端请求 `/api/poi/photo`；失败时不展示伪造景点图。
- 首页的 `public/images/guilin-river.webp` 是通过 ImageGen 为本次设计生成的独立视觉素材，非行程景点的替代照片。
- 等待规划期间展示真实等待状态；不模拟后台执行阶段或百分比。
- 行程保存在当前会话的 `sessionStorage`。损坏或不完整的数据显示空状态。
- 导出包含全部日期。交互地图在文件中替换为在线查看提示，避免跨域画布导致文件导出失败或出现空白地图。
- 浏览器集成验证使用独立的临时测试 API；应用中没有内置模拟行程，也没有改动后端接口。
