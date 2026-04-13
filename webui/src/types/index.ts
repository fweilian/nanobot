export interface Agent {
  id: string;
  name: string;
  description?: string;
  model?: string;
}

export type MessageRole = 'user' | 'assistant';

export interface MarkdownBlock {
  id: string;
  type: 'markdown';
  content: string;
  sequence: number;
}

export interface ToolCallBlock {
  id: string;
  type: 'tool_call';
  toolCallId: string;
  toolName: string;
  status: 'started' | 'streaming' | 'completed' | 'failed';
  argsText?: string;
  resultText?: string;
  sequence: number;
}

export interface StatusBlock {
  id: string;
  type: 'status';
  label: string;
  sequence: number;
}

export type MessageBlock = MarkdownBlock | ToolCallBlock | StatusBlock;

export interface Message {
  id: string;
  role: MessageRole;
  blocks: MessageBlock[];
  createdAt: number;
}

export interface SessionSummaryDTO {
  id: string;
  agentId: string;
  title: string;
  createdAt: number;
  updatedAt: number;
}

export interface SessionDetailDTO extends SessionSummaryDTO {
  messages: Message[];
}

export interface CreateSessionResponse extends SessionSummaryDTO {}

export interface RenameSessionRequest {
  title: string;
}

export interface ChatRequest {
  model?: string;
  messages: Array<{ role: string; content: string }>;
  stream?: boolean;
  agent?: string;
  sessionId?: string;
  cleanupEmptySessionOnError?: boolean;
}

export interface AssistantMessagePayload {
  id: string;
  role: 'assistant';
  blocks: MessageBlock[];
}

export interface ChatResponse {
  id: string;
  choices: Array<{
    message: { role: string; content: string };
    finish_reason: string;
  }>;
  message?: AssistantMessagePayload;
}

export interface ToolCallEventPayload {
  event:
    | 'tool_call_started'
    | 'tool_call_updated'
    | 'tool_call_completed'
    | 'tool_call_failed';
  message_id: string;
  block_id: string;
  tool_call_id: string;
  tool_name: string;
  sequence: number;
  args_text?: string;
  result_text?: string;
}

export interface AssistantTextDeltaPayload {
  event: 'assistant_text_delta';
  message_id: string;
  block_id: string;
  sequence: number;
  content: string;
}

export interface StreamErrorPayload {
  error: {
    code: string;
    message: string;
    retryable: boolean;
  };
}

export type ChatStreamEvent =
  | ToolCallEventPayload
  | AssistantTextDeltaPayload
  | StreamErrorPayload;

export interface ParsedChatStreamEvent {
  kind: 'text' | 'tool' | 'error' | 'done';
  text?: {
    content: string;
    messageId?: string;
    blockId?: string;
    sequence?: number;
  };
  tool?: ToolCallEventPayload;
  error?: Error;
}

export interface Config {
  apiUrl: string;
  apiKey: string;
  theme: 'light' | 'dark';
}
