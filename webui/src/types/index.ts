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
