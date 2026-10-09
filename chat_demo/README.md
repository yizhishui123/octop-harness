# octop-harness Chat Demo

一个基于 Vue 3 + FastAPI(SSE) 的聊天界面演示，真实驱动 `octop-harness` 的
`HarnessAgentManager`（流式 token、工具调用卡片、HITL 审批、上下文用量、
斜杠命令、多会话、多 agent）。

> 这是演示代码（与 `multi_agent_demo/` 同级），**不属于**发布包，也不进质量门禁。
> 视觉风格参照 Kimi Code / Codex CLI 的暗色终端风。

## 目录结构

```
chat_demo/
├── server/                 # FastAPI + SSE 后端（驱动 HarnessAgentManager）
│   ├── main.py             #   app 入口（uvicorn server.main:app）
│   ├── routes.py           #   /api 端点
│   ├── runtime.py          #   manager 单例 + agents.json/.env 加载
│   ├── serialize.py        #   事件/消息 → JSON-safe 序列化
│   └── smoke_fake.py       #   无 API key 的离线冒烟（fake model）
├── web/                    # Vue 3 + Vite + TypeScript + Pinia 前端
├── agents.example.json     # 多 agent 配置示例（复制为 agents.json 后生效）
└── .env.example            # provider 凭据占位（复制为 .env 填真实 key）
```

## 启动

### 1. 后端（仓库根目录的 venv）

```bash
# 一次性：安装演示后端依赖（不改动 pyproject）
uv pip install -r chat_demo/server/requirements.txt

# 配置 provider 凭据（任选其一）
cp chat_demo/.env.example chat_demo/.env   # 然后编辑填入真实 key
# 或直接在 shell 里 export OPENAI_API_KEY=... 等

# 从 chat_demo/ 目录启动
cd chat_demo && uvicorn server.main:app --reload --port 8000

# 无真实 key 的离线演示：fake model 应答，用于试 UI
cd chat_demo && OPENAI_API_KEY=sk-fake CHAT_DEMO_FAKE_MODEL=1 uvicorn server.main:app --port 8000
```

### 2. 前端

```bash
cd chat_demo/web
npm install
npm run dev        # http://localhost:5173（/api 已代理到 :8000）

# 端口被占用时可用环境变量覆盖：
VITE_PORT=5174 VITE_API_TARGET=http://localhost:8765 npm run dev
```

### 3. 离线冒烟（无 API key）

```bash
cd chat_demo && ../.venv/bin/python -m server.smoke_fake
```

## 配置

- **provider 凭据**：`chat_demo/.env`（或进程环境变量）。火山引擎 Ark 设
  `VOLCES_API_KEY` 即可（base_url 与模型目录走内置预设）——但该 key 会同时命中
  三个火山预设（开放平台/Coding Plan/Agent Plan），请配合
  `HARNESS_DEFAULT_MODEL=volcengine-cn/<model_id>` 钉住默认模型；用推理接入点
  ID（ep-xxx）时改用 `OPENAI_API_KEY`+`OPENAI_BASE_URL`+`OPENAI_MODEL_NAME`。
  其它写法见 `.env.example` 注释。
- **多 agent / HITL**：复制 `agents.example.json` 为 `agents.json`：
  - `agents[]`：`name`（必填）、`workspace_dir`、`default_model`、`system_prompt`、
    `backend`、`language`。
  - `"hitl": true`：对全部 agent 启用工具执行审批（默认工具集：
    bash/execute/write_file/edit_file/delete）。`ask_user_question` 工具的提问
    中断默认始终启用，无需此开关。
- **模型目录外的模型 id**：预设目录（`providers/provider_template.json`）通常滞后于厂商
  新模型。若 `HARNESS_DEFAULT_MODEL` / `default_model` / `agents.json` 的 `models`
  引用了已知 provider 下未收录的 model id，demo 后端会按你配置的原样注册并打
  warning（真实可用性由 provider 决定），因此 .env 里可以直接写新模型名。
- 密钥只存在于后端，前端永远接触不到。

## API 摘要

| 端点 | 说明 |
|---|---|
| `GET /api/agents` | agent 列表 + 可用模型 |
| `POST /api/chat/stream` | SSE 流式对话（事件帧 + 终止 `done` 哨兵） |
| `POST /api/chat/resume` | HITL 决策后的 SSE 续流 |
| `POST /api/chat/stop` | 取消当前线程的流 |
| `GET /api/threads/{tid}/history` | 会话历史（checkpointer） |
| `GET /api/threads/{tid}/context` | 上下文用量（分段明细） |

会话列表元数据由前端 localStorage 持久化；消息历史由后端 checkpointer
按 `thread_id` 提供。
