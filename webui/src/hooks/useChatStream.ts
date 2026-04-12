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

      // Create placeholder for assistant and get the actual message id
      const assistantMsgId = addMessage(session.id, { role: 'assistant', content: '' });

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
