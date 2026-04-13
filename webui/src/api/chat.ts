import { useConfigStore } from '../stores/configStore';
import { apiRequest } from './client';
import type {
  AssistantTextDeltaPayload,
  ChatRequest,
  ChatResponse,
  ChatStreamEvent,
  ParsedChatStreamEvent,
  ToolCallEventPayload,
} from '../types';

type OpenAIChunkLike = {
  choices?: Array<{
    delta?: { content?: string };
    finish_reason?: string | null;
  }>;
};

function serializeChatRequest(request: ChatRequest) {
  const { sessionId, ...rest } = request;
  return {
    ...rest,
    ...(sessionId ? { session_id: sessionId } : {}),
  };
}

export function parseChatStreamData(data: string): ParsedChatStreamEvent | null {
  if (data === '[DONE]') {
    return { kind: 'done' };
  }

  const parsed = JSON.parse(data) as ChatStreamEvent & OpenAIChunkLike & Record<string, unknown>;
  if (
    'error' in parsed &&
    parsed.error &&
    typeof parsed.error === 'object' &&
    'message' in parsed.error &&
    typeof parsed.error.message === 'string'
  ) {
    return {
      kind: 'error',
      error: new Error(parsed.error.message),
    };
  }
  if ('event' in parsed && parsed.event === 'assistant_text_delta') {
    const event = parsed as AssistantTextDeltaPayload;
    return {
      kind: 'text',
      text: {
        content: event.content,
        messageId: event.message_id,
        blockId: event.block_id,
        sequence: event.sequence,
      },
    };
  }
  if (
    'event' in parsed &&
    typeof parsed.event === 'string' &&
    parsed.event.startsWith('tool_call_')
  ) {
    return { kind: 'tool', tool: parsed as ToolCallEventPayload };
  }
  const finishReason = parsed.choices?.[0]?.finish_reason;
  if (finishReason === 'stop') {
    return { kind: 'done' };
  }
  const content = parsed.choices?.[0]?.delta?.content;
  if (content) {
    return { kind: 'text', text: { content } };
  }
  return null;
}

export async function sendChatMessage(request: ChatRequest): Promise<ChatResponse> {
  return apiRequest<ChatResponse>('/v1/chat/completions', {
    method: 'POST',
    body: JSON.stringify(serializeChatRequest(request)),
  });
}

export function createChatStream(
  request: ChatRequest,
  onEvent: (event: ParsedChatStreamEvent) => void,
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

  console.log('[ChatStream] Starting fetch to', `${apiUrl}/v1/chat/completions`);

  fetch(`${apiUrl}/v1/chat/completions`, {
    method: 'POST',
    headers,
    body: JSON.stringify({ ...serializeChatRequest(request), stream: true }),
    signal: controller.signal,
  })
    .then(async (response) => {
      console.log('[ChatStream] Response status:', response.status);
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }
      const reader = response.body?.getReader();
      if (!reader) throw new Error('No response body');

      const decoder = new TextDecoder();
      let buffer = '';
      let chunkCount = 0;

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            const data = line.slice(6);
            try {
              const parsed = parseChatStreamData(data);
              if (!parsed) {
                continue;
              }
              if (parsed.kind === 'done') {
                onDone();
                return;
              }
              if (parsed.kind === 'text' && parsed.text?.content) {
                chunkCount++;
                console.log('[ChatStream] Chunk', chunkCount, ':', parsed.text.content.substring(0, 50));
              }
              onEvent(parsed);
            } catch (e) {
              console.log('[ChatStream] JSON parse error:', e);
            }
          }
        }
      }
      console.log('[ChatStream] Stream complete, chunks:', chunkCount);
      onDone();
    })
    .catch((err) => {
      console.error('[ChatStream] Fetch error:', err);
      if (err.name !== 'AbortError') {
        onError(err);
      }
    });

  return () => controller.abort();
}
