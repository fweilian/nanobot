import { useConfigStore } from '../stores/configStore';
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
