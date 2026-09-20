# 前端界面

本目录是 Argus 的网页界面，由 FastAPI 后端直接提供静态文件，**没有独立的前端服务**。

## 运行

1. 安装依赖：

   ```
   pip install -r requirements.txt
   ```

2. 启动后端（会同时提供本目录的界面）：

   ```
   python -m uvicorn main:app
   ```

3. 浏览器打开 `http://localhost:8000`

> 注意：`frontend/static/` 是**服务启动的硬依赖**——`backend/server/app.py` 在模块顶层
> `app.mount(..., StaticFiles(directory=...))`，该目录缺失会导致应用无法导入。不要删除。

## 文件说明

| 文件 | 用途 |
|---|---|
| `index.html` | 页面结构 |
| `scripts.js` | 全部前端逻辑，含 `BACKEND_MESSAGE_RULES`（后端英文进度消息的中文映射表） |
| `styles.css` | 样式 |
| `static/` | logo、favicon、Agent 头像等静态资源 |

## 界面语言

界面为**中文硬编码**，不含语言切换。

后端通过 websocket 推送的研究进度提示，其文案写在 Python 源码里（`argus/skills/*.py`）。
这些消息在浏览器端由 `scripts.js` 的 `BACKEND_MESSAGE_RULES` + `translateBackendMessage()`
统一转换，接入点是 `addAgentResponse()`——**所有**后端日志消息都经过这一个函数。

新增后端消息时，记得同步添加一条映射规则，否则该条会以英文显示。

生成的**研究报告**语言由 `argus/config/variables/default.py` 的 `LANGUAGE` 控制（当前为 `chinese`）。

## 功能

- 研究查询输入，支持报告类型、语气、数据源等参数
- 研究过程实时进度展示
- 报告渲染与导出（Word / Markdown / JSON）
- 针对报告的追问对话
- 研究历史记录（本地存储）
- MCP 服务器配置

## 历史说明

本目录曾并存一套 Next.js 前端（`nextjs/`，即 npm 包 `argus-ui`），
已于结构精简时移除。当前后端提供的界面自始至终都是这里的静态版本。
