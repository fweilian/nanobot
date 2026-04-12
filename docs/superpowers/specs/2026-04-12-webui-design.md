# WebUI Module Design

## Overview

基于 `nanobot/cloud` 模块的 FastAPI 后端，创建一个独立的前端 webui 模块。用户可通过浏览器访问，与 nanobot agents 进行对话。

## Architecture

### 项目位置
- 独立目录 `webui/`，与 `nanobot/` 平级
- 前端独立构建，不依赖 nanobot 后端代码

### 技术栈
- React 18 + TypeScript
- Vite (构建工具)
- pnpm (包管理器)
- Zustand (状态管理)
- TailwindCSS (样式)
- lucide-react (图标)

## Project Structure

```
webui/
├── public/
│   └── favicon.svg
├── src/
│   ├── api/               # API 客户端封装
│   │   ├── client.ts      # 基础 fetch 封装 (自动注入 Authorization header)
│   │   ├── agents.ts      # /v1/agents 接口
│   │   ├── models.ts      # /v1/models 接口
│   │   └── chat.ts        # /v1/chat/completions 接口
│   ├── components/        # React 组件
│   │   ├── Layout/        # 主布局 (Sidebar + Main)
│   │   ├── Chat/           # 聊天相关 (MessageList, ChatInput, etc.)
│   │   ├── Sidebar/        # 侧边栏 (AgentSelector, SessionList)
│   │   └── Settings/       # 设置弹窗
│   ├── hooks/              # 自定义 hooks
│   ├── stores/             # Zustand stores
│   │   ├── configStore.ts  # API 配置 (持久化)
│   │   ├── agentStore.ts    # Agent 状态
│   │   └── chatStore.ts     # 聊天状态 (持久化)
│   ├── types/              # TypeScript 类型定义
│   ├── App.tsx
│   └── main.tsx
├── index.html
├── vite.config.ts
├── tsconfig.json
├── package.json
└── pnpm-lock.yaml
```

## Components

### Layout Structure

**左侧边栏 (240-280px)**
- 顶部：Logo + 应用名 + 设置按钮
- 中部：Agent 选择器（下拉列表，从 `/v1/agents` 获取）
- 下部：会话列表（支持切换/新建/删除）

**右侧主区域**
- 顶部：当前 Agent 名称 + 模型信息
- 中部：消息展示区（支持流式响应）
- 底部：输入框（Textarea 自动扩展）+ 发送按钮

### Settings Drawer
- API 地址输入
- API Key 输入 (Bearer Token)
- 主题偏好 (浅色/深色)

## API Integration

### Endpoints

| 前端操作 | 调用后端 | 认证 |
|---------|---------|------|
| 获取 Agent 列表 | `GET /v1/agents` | Bearer Token |
| 获取模型列表 | `GET /v1/models` | 无 |
| 发送消息 | `POST /v1/chat/completions` | Bearer Token |

### Authentication
- 使用固定配置密钥
- 请求时注入 `Authorization: Bearer <token>` HTTP Header
- 无登录页面

### Streaming
- 使用 `fetch` + `ReadableStream` 读取 SSE 增量数据
- 实时渲染流式响应到聊天区

## State Management (Zustand)

### configStore
- `apiUrl`: API 地址
- `apiKey`: Bearer Token
- `theme`: 主题偏好
- 持久化到 localStorage

### agentStore
- `agents`: Agent 列表
- `selectedAgent`: 当前选中的 Agent
- `models`: 模型列表

### chatStore
- `sessions`: 会话历史列表 (持久化)
- `currentSessionId`: 当前会话 ID
- `messages`: 当前会话的消息列表
- `streaming`: 是否正在流式响应

## Data Models

### Session
```typescript
interface Session {
  id: string;           // UUID
  agentId: string;     // 关联的 Agent ID
  title: string;        // 会话标题 (取首条消息前20字符)
  messages: Message[];  // 消息列表
  createdAt: number;    // 创建时间戳
  updatedAt: number;    // 更新时间戳
}
```

### Message
```typescript
interface Message {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  createdAt: number;
}
```

### Agent
```typescript
interface Agent {
  id: string;
  name: string;
  description?: string;
  model?: string;
}
```

## Implementation Notes

1. 会话存储在 localStorage，每个会话包含完整的 messages 数组
2. 新建会话时生成 UUID
3. 流式响应使用 `text/event-stream` 格式解析
4. 输入框支持 Shift+Enter 换行，Enter 发送
5. API 调用错误时显示 toast 提示
