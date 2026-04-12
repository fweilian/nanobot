# WebUI Module Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 创建独立的 webui 前端模块，基于 nanobot cloud FastAPI 后端实现多 Agent 对话界面。

**Architecture:** 独立 `webui/` 目录，React 18 + TypeScript + Vite + Zustand + TailwindCSS。前端通过 REST API 与 cloud 后端通信，支持流式对话和会话持久化。

**Tech Stack:** React 18, TypeScript, Vite, pnpm, Zustand, TailwindCSS, lucide-react

---

## File Structure

```
webui/
├── public/
│   └── favicon.svg
├── src/
│   ├── api/
│   │   ├── client.ts
│   │   ├── agents.ts
│   │   ├── models.ts
│   │   └── chat.ts
│   ├── components/
│   │   ├── Layout/
│   │   │   └── MainLayout.tsx
│   │   ├── Chat/
│   │   │   ├── MessageList.tsx
│   │   │   ├── ChatInput.tsx
│   │   │   └── Message.tsx
│   │   ├── Sidebar/
│   │   │   ├── Sidebar.tsx
│   │   │   ├── AgentSelector.tsx
│   │   │   └── SessionList.tsx
│   │   └── Settings/
│   │       └── SettingsDrawer.tsx
│   ├── hooks/
│   │   └── useChatStream.ts
│   ├── stores/
│   │   ├── configStore.ts
│   │   ├── agentStore.ts
│   │   └── chatStore.ts
│   ├── types/
│   │   └── index.ts
│   ├── App.tsx
│   ├── main.tsx
│   └── index.css
├── index.html
├── vite.config.ts
├── tsconfig.json
├── tsconfig.node.json
├── tailwind.config.js
├── postcss.config.js
└── package.json
```

---

## Task 1: Project Scaffolding

**Files:**
- Create: `webui/package.json`
- Create: `webui/vite.config.ts`
- Create: `webui/tsconfig.json`
- Create: `webui/tsconfig.node.json`
- Create: `webui/tailwind.config.js`
- Create: `webui/postcss.config.js`
- Create: `webui/index.html`
- Create: `webui/public/favicon.svg`

- [ ] **Step 1: Create package.json**

```json
{
  "name": "nanobot-webui",
  "private": true,
  "version": "0.1.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc && vite build",
    "preview": "vite preview"
  },
  "dependencies": {
    "react": "^18.3.1",
    "react-dom": "^18.3.1",
    "zustand": "^4.5.2",
    "lucide-react": "^0.400.0"
  },
  "devDependencies": {
    "@types/react": "^18.3.3",
    "@types/react-dom": "^18.3.0",
    "@vitejs/plugin-react": "^4.3.1",
    "autoprefixer": "^10.4.19",
    "postcss": "^8.4.38",
    "tailwindcss": "^3.4.4",
    "typescript": "^5.5.2",
    "vite": "^5.3.1"
  }
}
```

- [ ] **Step 2: Create vite.config.ts**

```typescript
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000,
    proxy: {
      '/api': {
        target: 'http://localhost:8890',
        changeOrigin: true,
      },
    },
  },
})
```

- [ ] **Step 3: Create tsconfig.json**

```json
{
  "compilerOptions": {
    "target": "ES2020",
    "useDefineForClassFields": true,
    "lib": ["ES2020", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "skipLibCheck": true,
    "moduleResolution": "bundler",
    "allowImportingTsExtensions": true,
    "resolveJsonModule": true,
    "isolatedModules": true,
    "noEmit": true,
    "jsx": "react-jsx",
    "strict": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "noFallthroughCasesInSwitch": true
  },
  "include": ["src"],
  "references": [{ "path": "./tsconfig.node.json" }]
}
```

- [ ] **Step 4: Create tsconfig.node.json**

```json
{
  "compilerOptions": {
    "composite": true,
    "skipLibCheck": true,
    "module": "ESNext",
    "moduleResolution": "bundler",
    "allowSyntheticDefaultImports": true,
    "strict": true
  },
  "include": ["vite.config.ts"]
}
```

- [ ] **Step 5: Create tailwind.config.js**

```javascript
/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  darkMode: 'class',
  theme: {
    extend: {},
  },
  plugins: [],
}
```

- [ ] **Step 6: Create postcss.config.js**

```javascript
export default {
  plugins: {
    tailwindcss: {},
    autoprefixer: {},
  },
}
```

- [ ] **Step 7: Create index.html**

```html
<!DOCTYPE html>
<html lang="zh-CN">
  <head>
    <meta charset="UTF-8" />
    <link rel="icon" type="image/svg+xml" href="/favicon.svg" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Nanobot WebUI</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

- [ ] **Step 8: Create favicon.svg**

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">
  <circle cx="50" cy="50" r="45" fill="#4F46E5"/>
  <text x="50" y="65" font-size="50" text-anchor="middle" fill="white">N</text>
</svg>
```

- [ ] **Step 9: Commit**

```bash
git add webui/package.json webui/vite.config.ts webui/tsconfig.json webui/tsconfig.node.json webui/tailwind.config.js webui/postcss.config.js webui/index.html webui/public/favicon.svg
git commit -m "feat(webui): scaffold project with vite + react + ts + tailwind"
```

---

## Task 2: Type Definitions

**Files:**
- Create: `webui/src/types/index.ts`

- [ ] **Step 1: Create types/index.ts**

```typescript
export interface Agent {
  id: string;
  name: string;
  description?: string;
  model?: string;
}

export interface Message {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  createdAt: number;
}

export interface Session {
  id: string;
  agentId: string;
  title: string;
  messages: Message[];
  createdAt: number;
  updatedAt: number;
}

export interface ChatRequest {
  model?: string;
  messages: Array<{ role: string; content: string }>;
  stream?: boolean;
  agent?: string;
}

export interface ChatResponse {
  id: string;
  choices: Array<{
    message: { role: string; content: string };
    finish_reason: string;
  }>;
}

export interface Config {
  apiUrl: string;
  apiKey: string;
  theme: 'light' | 'dark';
}
```

- [ ] **Step 2: Commit**

```bash
git add webui/src/types/index.ts
git commit -m "feat(webui): add TypeScript type definitions"
```

---

## Task 3: API Client Layer

**Files:**
- Create: `webui/src/api/client.ts`
- Create: `webui/src/api/agents.ts`
- Create: `webui/src/api/models.ts`
- Create: `webui/src/api/chat.ts`

- [ ] **Step 1: Create api/client.ts**

```typescript
import { useConfigStore } from '../stores/configStore';

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
    this.name = 'ApiError';
  }
}

export async function apiRequest<T>(
  endpoint: string,
  options: RequestInit = {}
): Promise<T> {
  const { apiUrl, apiKey } = useConfigStore.getState();

  const headers: HeadersInit = {
    'Content-Type': 'application/json',
    ...options.headers,
  };

  if (apiKey) {
    headers['Authorization'] = `Bearer ${apiKey}`;
  }

  const response = await fetch(`${apiUrl}${endpoint}`, {
    ...options,
    headers,
  });

  if (!response.ok) {
    throw new ApiError(response.status, await response.text());
  }

  return response.json();
}
```

- [ ] **Step 2: Create api/agents.ts**

```typescript
import { apiRequest } from './client';
import type { Agent } from '../types';

export async function fetchAgents(): Promise<Agent[]> {
  return apiRequest<Agent[]>('/v1/agents');
}
```

- [ ] **Step 3: Create api/models.ts**

```typescript
import { apiRequest } from './client';

interface Model {
  id: string;
  name?: string;
  object?: string;
}

interface ModelsResponse {
  data: Model[];
  object: string;
}

export async function fetchModels(): Promise<Model[]> {
  const response = await apiRequest<ModelsResponse>('/v1/models');
  return response.data;
}
```

- [ ] **Step 4: Create api/chat.ts**

```typescript
import { apiRequest } from './client';
import type { ChatRequest, ChatResponse } from '../types';

export async function sendChatMessage(request: ChatRequest): Promise<ChatResponse> {
  return apiRequest<ChatResponse>('/v1/chat/completions', {
    method: 'POST',
    body: JSON.stringify(request),
  });
}

export function createChatStream(
  request: ChatRequest,
  onChunk: (content: string) => void,
  onDone: () => void,
  onError: (error: Error) => void
): () => void {
  const { apiUrl, apiKey } = useConfigStore.getState();

  const headers: HeadersInit = {
    'Content-Type': 'application/json',
  };

  if (apiKey) {
    headers['Authorization'] = `Bearer ${apiKey}`;
  }

  const controller = new AbortController();

  fetch(`${apiUrl}/v1/chat/completions`, {
    method: 'POST',
    headers,
    body: JSON.stringify({ ...request, stream: true }),
    signal: controller.signal,
  })
    .then(async (response) => {
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }
      const reader = response.body?.getReader();
      if (!reader) throw new Error('No response body');

      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            const data = line.slice(6);
            if (data === '[DONE]') {
              onDone();
              return;
            }
            try {
              const parsed = JSON.parse(data);
              const content = parsed.choices?.[0]?.delta?.content;
              if (content) onChunk(content);
            } catch {
              // skip invalid JSON
            }
          }
        }
      }
      onDone();
    })
    .catch((err) => {
      if (err.name !== 'AbortError') {
        onError(err);
      }
    });

  return () => controller.abort();
}

// Need to import useConfigStore
import { useConfigStore } from '../stores/configStore';
```

- [ ] **Step 5: Commit**

```bash
git add webui/src/api/
git commit -m "feat(webui): add API client layer"
```

---

## Task 4: Zustand Stores

**Files:**
- Create: `webui/src/stores/configStore.ts`
- Create: `webui/src/stores/agentStore.ts`
- Create: `webui/src/stores/chatStore.ts`

- [ ] **Step 1: Create stores/configStore.ts**

```typescript
import { create } from 'zustand';
import { persist } from 'zustand/middleware';

interface ConfigState {
  apiUrl: string;
  apiKey: string;
  theme: 'light' | 'dark';
  setApiUrl: (url: string) => void;
  setApiKey: (key: string) => void;
  setTheme: (theme: 'light' | 'dark') => void;
}

export const useConfigStore = create<ConfigState>()(
  persist(
    (set) => ({
      apiUrl: 'http://localhost:8890',
      apiKey: '',
      theme: 'light',
      setApiUrl: (url) => set({ apiUrl: url }),
      setApiKey: (key) => set({ apiKey: key }),
      setTheme: (theme) => set({ theme }),
    }),
    { name: 'nanobot-config' }
  )
);
```

- [ ] **Step 2: Create stores/agentStore.ts**

```typescript
import { create } from 'zustand';
import type { Agent } from '../types';
import { fetchAgents } from '../api/agents';

interface AgentState {
  agents: Agent[];
  selectedAgent: Agent | null;
  loading: boolean;
  error: string | null;
  loadAgents: () => Promise<void>;
  selectAgent: (agent: Agent | null) => void;
}

export const useAgentStore = create<AgentState>((set) => ({
  agents: [],
  selectedAgent: null,
  loading: false,
  error: null,
  loadAgents: async () => {
    set({ loading: true, error: null });
    try {
      const agents = await fetchAgents();
      set({ agents, loading: false });
    } catch (err) {
      set({ error: err instanceof Error ? err.message : 'Failed to load agents', loading: false });
    }
  },
  selectAgent: (agent) => set({ selectedAgent: agent }),
}));
```

- [ ] **Step 3: Create stores/chatStore.ts**

```typescript
import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import type { Session, Message } from '../types';

function generateId(): string {
  return crypto.randomUUID();
}

interface ChatState {
  sessions: Session[];
  currentSessionId: string | null;
  streaming: boolean;
  createSession: (agentId: string) => string;
  deleteSession: (id: string) => void;
  selectSession: (id: string) => void;
  addMessage: (sessionId: string, message: Omit<Message, 'id' | 'createdAt'>) => void;
  updateStreamingMessage: (sessionId: string, messageId: string, content: string) => void;
  setStreaming: (streaming: boolean) => void;
  getCurrentSession: () => Session | null;
}

export const useChatStore = create<ChatState>()(
  persist(
    (set, get) => ({
      sessions: [],
      currentSessionId: null,
      streaming: false,
      createSession: (agentId) => {
        const id = generateId();
        const now = Date.now();
        const session: Session = {
          id,
          agentId,
          title: '新对话',
          messages: [],
          createdAt: now,
          updatedAt: now,
        };
        set((state) => ({
          sessions: [session, ...state.sessions],
          currentSessionId: id,
        }));
        return id;
      },
      deleteSession: (id) =>
        set((state) => {
          const sessions = state.sessions.filter((s) => s.id !== id);
          const currentSessionId =
            state.currentSessionId === id
              ? sessions[0]?.id || null
              : state.currentSessionId;
          return { sessions, currentSessionId };
        }),
      selectSession: (id) => set({ currentSessionId: id }),
      addMessage: (sessionId, message) =>
        set((state) => ({
          sessions: state.sessions.map((s) =>
            s.id === sessionId
              ? {
                  ...s,
                  messages: [
                    ...s.messages,
                    {
                      ...message,
                      id: generateId(),
                      createdAt: Date.now(),
                    },
                  ],
                  updatedAt: Date.now(),
                  title:
                    s.messages.length === 0 && message.role === 'user'
                      ? message.content.slice(0, 20) + (message.content.length > 20 ? '...' : '')
                      : s.title,
                }
              : s
          ),
        })),
      updateStreamingMessage: (sessionId, messageId, content) =>
        set((state) => ({
          sessions: state.sessions.map((s) =>
            s.id === sessionId
              ? {
                  ...s,
                  messages: s.messages.map((m) =>
                    m.id === messageId ? { ...m, content } : m
                  ),
                }
              : s
          ),
        })),
      setStreaming: (streaming) => set({ streaming }),
      getCurrentSession: () => {
        const state = get();
        return state.sessions.find((s) => s.id === state.currentSessionId) || null;
      },
    }),
    { name: 'nanobot-sessions' }
  )
);
```

- [ ] **Step 4: Commit**

```bash
git add webui/src/stores/
git commit -m "feat(webui): add Zustand stores with localStorage persistence"
```

---

## Task 5: Custom Hooks

**Files:**
- Create: `webui/src/hooks/useChatStream.ts`

- [ ] **Step 1: Create hooks/useChatStream.ts**

```typescript
import { useCallback } from 'react';
import { createChatStream } from '../api/chat';
import { useChatStore } from '../stores/chatStore';
import type { ChatRequest } from '../types';

export function useChatStream() {
  const { addMessage, updateStreamingMessage, setStreaming, getCurrentSession } =
    useChatStore();

  const sendMessage = useCallback(
    async (content: string, request: Omit<ChatRequest, 'messages'>) => {
      const session = getCurrentSession();
      if (!session) return;

      // Add user message
      addMessage(session.id, { role: 'user', content });

      // Create placeholder for assistant
      const assistantMsgId = crypto.randomUUID();
      addMessage(session.id, { role: 'assistant', content: '' });

      setStreaming(true);

      let fullContent = '';

      createChatStream(
        {
          ...request,
          messages: [
            ...session.messages.map((m) => ({ role: m.role, content: m.content })),
            { role: 'user', content },
          ],
        },
        (chunk) => {
          fullContent += chunk;
          updateStreamingMessage(session.id, assistantMsgId, fullContent);
        },
        () => {
          setStreaming(false);
        },
        (err) => {
          console.error('Chat error:', err);
          updateStreamingMessage(session.id, assistantMsgId, `错误: ${err.message}`);
          setStreaming(false);
        }
      );
    },
    [addMessage, updateStreamingMessage, setStreaming, getCurrentSession]
  );

  return { sendMessage };
}
```

- [ ] **Step 2: Commit**

```bash
git add webui/src/hooks/useChatStream.ts
git commit -m "feat(webui): add useChatStream hook for streaming chat"
```

---

## Task 6: Chat Components

**Files:**
- Create: `webui/src/components/Chat/Message.tsx`
- Create: `webui/src/components/Chat/MessageList.tsx`
- Create: `webui/src/components/Chat/ChatInput.tsx`

- [ ] **Step 1: Create Chat/Message.tsx**

```tsx
import type { Message } from '../../types';

interface MessageProps {
  message: Message;
}

export function Message({ message }: MessageProps) {
  const isUser = message.role === 'user';

  return (
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'}`}>
      <div
        className={`max-w-[70%] rounded-lg px-4 py-2 ${
          isUser
            ? 'bg-indigo-600 text-white'
            : 'bg-gray-200 dark:bg-gray-700 text-gray-900 dark:text-white'
        }`}
      >
        <p className="whitespace-pre-wrap break-words">{message.content || '...'}</p>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Create Chat/MessageList.tsx**

```tsx
import { useChatStore } from '../../stores/chatStore';
import { Message } from './Message';

export function MessageList() {
  const { getCurrentSession } = useChatStore();
  const session = getCurrentSession();

  if (!session) {
    return (
      <div className="flex items-center justify-center h-full text-gray-500">
        选择 Agent 并开始对话
      </div>
    );
  }

  if (session.messages.length === 0) {
    return (
      <div className="flex items-center justify-center h-full text-gray-500">
        开始发送消息吧
      </div>
    );
  }

  return (
    <div className="flex-1 overflow-y-auto p-4 space-y-4">
      {session.messages.map((msg) => (
        <Message key={msg.id} message={msg} />
      ))}
    </div>
  );
}
```

- [ ] **Step 3: Create Chat/ChatInput.tsx**

```tsx
import { useState, useRef, useEffect } from 'react';
import { Send } from 'lucide-react';
import { useAgentStore } from '../../stores/agentStore';
import { useChatStore } from '../../stores/chatStore';
import { useChatStream } from '../../hooks/useChatStream';

export function ChatInput() {
  const [input, setInput] = useState('');
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const { selectedAgent } = useAgentStore();
  const { streaming } = useChatStore();
  const { sendMessage } = useChatStream();

  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
      textareaRef.current.style.height = `${textareaRef.current.scrollHeight}px`;
    }
  }, [input]);

  const handleSubmit = async () => {
    if (!input.trim() || !selectedAgent || streaming) return;

    const content = input.trim();
    setInput('');

    await sendMessage(content, {
      agent: selectedAgent.id,
      model: selectedAgent.model,
    });
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  if (!selectedAgent) {
    return (
      <div className="p-4 border-t border-gray-200 dark:border-gray-700">
        <div className="bg-gray-100 dark:bg-gray-800 rounded-lg p-4 text-center text-gray-500">
          请先在左侧选择一个 Agent
        </div>
      </div>
    );
  }

  return (
    <div className="p-4 border-t border-gray-200 dark:border-gray-700">
      <div className="flex items-end gap-2">
        <textarea
          ref={textareaRef}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="输入消息... (Shift+Enter 换行)"
          className="flex-1 resize-none rounded-lg border border-gray-300 dark:border-gray-600 px-4 py-2 focus:outline-none focus:ring-2 focus:ring-indigo-500 dark:bg-gray-800 dark:text-white"
          rows={1}
          disabled={streaming}
        />
        <button
          onClick={handleSubmit}
          disabled={!input.trim() || streaming}
          className="p-2 rounded-lg bg-indigo-600 text-white hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          <Send size={20} />
        </button>
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Commit**

```bash
git add webui/src/components/Chat/
git commit -m "feat(webui): add Chat components (Message, MessageList, ChatInput)"
```

---

## Task 7: Sidebar Components

**Files:**
- Create: `webui/src/components/Sidebar/AgentSelector.tsx`
- Create: `webui/src/components/Sidebar/SessionList.tsx`
- Create: `webui/src/components/Sidebar/Sidebar.tsx`

- [ ] **Step 1: Create Sidebar/AgentSelector.tsx**

```tsx
import { useEffect } from 'react';
import { Bot } from 'lucide-react';
import { useAgentStore } from '../../stores/agentStore';
import { useChatStore } from '../../stores/chatStore';

export function AgentSelector() {
  const { agents, selectedAgent, loading, error, loadAgents, selectAgent } =
    useAgentStore();
  const { createSession } = useChatStore();

  useEffect(() => {
    loadAgents();
  }, [loadAgents]);

  const handleAgentChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    const agentId = e.target.value;
    if (agentId === '') {
      selectAgent(null);
    } else {
      const agent = agents.find((a) => a.id === agentId);
      if (agent) {
        selectAgent(agent);
        createSession(agent.id);
      }
    }
  };

  return (
    <div className="p-4 border-b border-gray-200 dark:border-gray-700">
      <div className="flex items-center gap-2 mb-2">
        <Bot size={18} />
        <label className="text-sm font-medium">Agent</label>
      </div>
      <select
        value={selectedAgent?.id || ''}
        onChange={handleAgentChange}
        disabled={loading}
        className="w-full rounded-lg border border-gray-300 dark:border-gray-600 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 dark:bg-gray-800"
      >
        <option value="">选择 Agent...</option>
        {agents.map((agent) => (
          <option key={agent.id} value={agent.id}>
            {agent.name}
          </option>
        ))}
      </select>
      {error && <p className="mt-2 text-xs text-red-500">{error}</p>}
      {selectedAgent && (
        <p className="mt-2 text-xs text-gray-500">{selectedAgent.description}</p>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Create Sidebar/SessionList.tsx**

```tsx
import { MessageSquare, Plus, Trash2 } from 'lucide-react';
import { useChatStore } from '../../stores/chatStore';

export function SessionList() {
  const { sessions, currentSessionId, selectSession, deleteSession, createSession } =
    useChatStore();
  const { selectedAgent } = useAgentStore();

  const handleNewSession = () => {
    if (selectedAgent) {
      createSession(selectedAgent.id);
    }
  };

  return (
    <div className="flex-1 overflow-y-auto">
      <div className="p-4">
        <button
          onClick={handleNewSession}
          disabled={!selectedAgent}
          className="w-full flex items-center gap-2 px-3 py-2 rounded-lg bg-indigo-600 text-white hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          <Plus size={18} />
          新建会话
        </button>
      </div>
      <div className="space-y-1 px-2">
        {sessions.map((session) => (
          <div
            key={session.id}
            className={`group flex items-center gap-2 px-3 py-2 rounded-lg cursor-pointer transition-colors ${
              session.id === currentSessionId
                ? 'bg-indigo-100 dark:bg-indigo-900'
                : 'hover:bg-gray-100 dark:hover:bg-gray-800'
            }`}
            onClick={() => selectSession(session.id)}
          >
            <MessageSquare size={16} className="flex-shrink-0" />
            <span className="flex-1 truncate text-sm">{session.title}</span>
            <button
              onClick={(e) => {
                e.stopPropagation();
                deleteSession(session.id);
              }}
              className="opacity-0 group-hover:opacity-100 p-1 hover:text-red-500"
            >
              <Trash2 size={14} />
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}
```

Import fix needed - SessionList also uses useAgentStore. Add to imports:
```tsx
import { useAgentStore } from '../../stores/agentStore';
```

- [ ] **Step 3: Create Sidebar/Sidebar.tsx**

```tsx
import { Settings } from 'lucide-react';
import { AgentSelector } from './AgentSelector';
import { SessionList } from './SessionList';

interface SidebarProps {
  onSettingsClick: () => void;
}

export function Sidebar({ onSettingsClick }: SidebarProps) {
  return (
    <div className="w-64 h-full flex flex-col bg-gray-50 dark:bg-gray-900 border-r border-gray-200 dark:border-gray-700">
      <div className="flex items-center justify-between p-4 border-b border-gray-200 dark:border-gray-700">
        <h1 className="font-bold text-lg">Nanobot</h1>
        <button
          onClick={onSettingsClick}
          className="p-2 rounded-lg hover:bg-gray-200 dark:hover:bg-gray-800"
        >
          <Settings size={18} />
        </button>
      </div>
      <AgentSelector />
      <SessionList />
    </div>
  );
}
```

- [ ] **Step 4: Commit**

```bash
git add webui/src/components/Sidebar/
git commit -m "feat(webui): add Sidebar components (AgentSelector, SessionList, Sidebar)"
```

---

## Task 8: Settings Drawer

**Files:**
- Create: `webui/src/components/Settings/SettingsDrawer.tsx`

- [ ] **Step 1: Create Settings/SettingsDrawer.tsx**

```tsx
import { X } from 'lucide-react';
import { useConfigStore } from '../../stores/configStore';

interface SettingsDrawerProps {
  open: boolean;
  onClose: () => void;
}

export function SettingsDrawer({ open, onClose }: SettingsDrawerProps) {
  const { apiUrl, apiKey, theme, setApiUrl, setApiKey, setTheme } = useConfigStore();

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex">
      <div className="flex-1 bg-black/50" onClick={onClose} />
      <div className="w-80 h-full bg-white dark:bg-gray-900 shadow-xl p-6 overflow-y-auto">
        <div className="flex items-center justify-between mb-6">
          <h2 className="text-xl font-bold">设置</h2>
          <button
            onClick={onClose}
            className="p-2 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800"
          >
            <X size={20} />
          </button>
        </div>

        <div className="space-y-6">
          <div>
            <label className="block text-sm font-medium mb-2">API 地址</label>
            <input
              type="text"
              value={apiUrl}
              onChange={(e) => setApiUrl(e.target.value)}
              placeholder="http://localhost:8890"
              className="w-full rounded-lg border border-gray-300 dark:border-gray-600 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 dark:bg-gray-800"
            />
          </div>

          <div>
            <label className="block text-sm font-medium mb-2">API Key (Bearer Token)</label>
            <input
              type="password"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder="输入 API Key"
              className="w-full rounded-lg border border-gray-300 dark:border-gray-600 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 dark:bg-gray-800"
            />
          </div>

          <div>
            <label className="block text-sm font-medium mb-2">主题</label>
            <div className="flex gap-2">
              <button
                onClick={() => setTheme('light')}
                className={`flex-1 px-3 py-2 rounded-lg border text-sm ${
                  theme === 'light'
                    ? 'border-indigo-500 bg-indigo-50 text-indigo-600'
                    : 'border-gray-300'
                }`}
              >
                浅色
              </button>
              <button
                onClick={() => setTheme('dark')}
                className={`flex-1 px-3 py-2 rounded-lg border text-sm ${
                  theme === 'dark'
                    ? 'border-indigo-500 bg-indigo-50 text-indigo-600'
                    : 'border-gray-300'
                }`}
              >
                深色
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add webui/src/components/Settings/SettingsDrawer.tsx
git commit -m "feat(webui): add Settings drawer component"
```

---

## Task 9: Layout and App Assembly

**Files:**
- Create: `webui/src/components/Layout/MainLayout.tsx`
- Create: `webui/src/App.tsx`
- Create: `webui/src/main.tsx`
- Create: `webui/src/index.css`

- [ ] **Step 1: Create Layout/MainLayout.tsx**

```tsx
import { useState } from 'react';
import { Sidebar } from '../Sidebar/Sidebar';
import { MessageList } from '../Chat/MessageList';
import { ChatInput } from '../Chat/ChatInput';
import { SettingsDrawer } from '../Settings/SettingsDrawer';
import { useAgentStore } from '../../stores/agentStore';

export function MainLayout() {
  const [settingsOpen, setSettingsOpen] = useState(false);
  const { selectedAgent } = useAgentStore();

  return (
    <div className="flex h-screen">
      <Sidebar onSettingsClick={() => setSettingsOpen(true)} />
      <div className="flex-1 flex flex-col">
        <div className="h-14 px-4 flex items-center border-b border-gray-200 dark:border-gray-700">
          {selectedAgent ? (
            <span className="font-medium">{selectedAgent.name}</span>
          ) : (
            <span className="text-gray-500">未选择 Agent</span>
          )}
        </div>
        <MessageList />
        <ChatInput />
      </div>
      <SettingsDrawer open={settingsOpen} onClose={() => setSettingsOpen(false)} />
    </div>
  );
}
```

- [ ] **Step 2: Create App.tsx**

```tsx
import { MainLayout } from './components/Layout/MainLayout';

function App() {
  return <MainLayout />;
}

export default App;
```

- [ ] **Step 3: Create main.tsx**

```tsx
import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';
import './index.css';

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
```

- [ ] **Step 4: Create index.css**

```css
@tailwind base;
@tailwind components;
@tailwind utilities;

body {
  margin: 0;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen,
    Ubuntu, Cantarell, 'Open Sans', 'Helvetica Neue', sans-serif;
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
}
```

- [ ] **Step 5: Commit**

```bash
git add webui/src/components/Layout/MainLayout.tsx webui/src/App.tsx webui/src/main.tsx webui/src/index.css
git commit -m "feat(webui): add MainLayout and App assembly"
```

---

## Task 10: Dark Mode Support

**Files:**
- Modify: `webui/src/App.tsx`
- Modify: `webui/src/index.css`

- [ ] **Step 1: Update App.tsx to apply theme class**

```tsx
import { useEffect } from 'react';
import { MainLayout } from './components/Layout/MainLayout';
import { useConfigStore } from './stores/configStore';

function App() {
  const { theme } = useConfigStore();

  useEffect(() => {
    if (theme === 'dark') {
      document.documentElement.classList.add('dark');
    } else {
      document.documentElement.classList.remove('dark');
    }
  }, [theme]);

  return <MainLayout />;
}

export default App;
```

- [ ] **Step 2: Update index.css for dark mode base styles**

```css
@tailwind base;
@tailwind components;
@tailwind utilities;

body {
  margin: 0;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen,
    Ubuntu, Cantarell, 'Open Sans', 'Helvetica Neue', sans-serif;
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
}

.dark {
  color-scheme: dark;
}
```

- [ ] **Step 3: Commit**

```bash
git add webui/src/App.tsx webui/src/index.css
git commit -m "feat(webui): add dark mode theme support"
```

---

## Task 11: Install Dependencies and Verify Build

**Files:**
- None (verification step)

- [ ] **Step 1: Install dependencies**

Run: `cd webui && pnpm install`
Expected: Dependencies installed successfully

- [ ] **Step 2: Run TypeScript check**

Run: `cd webui && pnpm exec tsc --noEmit`
Expected: No TypeScript errors

- [ ] **Step 3: Run build**

Run: `cd webui && pnpm build`
Expected: Build succeeds, output in webui/dist/

- [ ] **Step 4: Commit the built assets (optional)**

```bash
git add webui/dist/ 2>/dev/null || true
git commit -m "feat(webui): build output" 2>/dev/null || true
```

---

## Implementation Complete

After all tasks complete, the webui module will be ready with:
- Project scaffolding (Vite + React + TypeScript + TailwindCSS)
- Type definitions for Agent, Session, Message, ChatRequest/Response
- API client layer with JWT Bearer token authentication
- Zustand stores with localStorage persistence
- Chat UI components with streaming support
- Sidebar with Agent selector and Session list
- Settings drawer for API configuration
- Dark/Light theme support

Run in webui directory:
```bash
pnpm install
pnpm dev
```
