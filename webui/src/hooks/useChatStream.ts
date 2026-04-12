import { useCallback } from 'react';
import { createChatStream, sendChatMessage } from '../api/chat';
import { useChatStore } from '../stores/chatStore';
import type { ChatRequest, MessageBlock } from '../types';

function createMarkdownBlock(content: string): MessageBlock {
  return {
    id: crypto.randomUUID(),
    type: 'markdown',
    content,
    sequence: 0,
  };
}

export function useChatStream() {
  const {
    addMessage,
    appendMarkdownDelta,
    applyToolCallEvent,
    replaceAssistantBlocks,
    adoptMessageId,
    setStreaming,
    getCurrentSession,
  } =
    useChatStore();

  const sendMessage = useCallback(
    async (content: string, request: Omit<ChatRequest, 'messages'>) => {
      const session = getCurrentSession();
      if (!session) return;

      // Add user message
      addMessage(session.id, { role: 'user', blocks: [createMarkdownBlock(content)] });

      // Create placeholder for assistant and get the actual message id
      const assistantMsgId = addMessage(session.id, { role: 'assistant', blocks: [] });
      let activeAssistantMsgId = assistantMsgId;

      setStreaming(true);

      const shouldStream = request.stream !== false;

      if (!shouldStream) {
        try {
          const response = await sendChatMessage({
            ...request,
            messages: [
              ...session.messages.map((m) => ({
                role: m.role,
                content: m.blocks
                  .filter((block) => block.type === 'markdown')
                  .map((block) => block.content)
                  .join('\n'),
              })),
              { role: 'user', content },
            ],
          });
          if (response.message?.id && response.message.id !== activeAssistantMsgId) {
            adoptMessageId(session.id, activeAssistantMsgId, response.message.id);
            activeAssistantMsgId = response.message.id;
          }
          replaceAssistantBlocks(
            session.id,
            activeAssistantMsgId,
            response.message?.blocks || [createMarkdownBlock(response.choices[0]?.message.content || '')]
          );
        } catch (err) {
          const message = err instanceof Error ? err.message : 'Unknown error';
          replaceAssistantBlocks(session.id, activeAssistantMsgId, [
            createMarkdownBlock(`错误: ${message}`),
          ]);
        } finally {
          setStreaming(false);
        }
        return;
      }

      createChatStream(
        {
          ...request,
          messages: [
            ...session.messages.map((m) => ({
              role: m.role,
              content: m.blocks
                .filter((block) => block.type === 'markdown')
                .map((block) => block.content)
                .join('\n'),
            })),
            { role: 'user', content },
          ],
        },
        (event) => {
          if (event.kind === 'text' && event.text) {
            if (event.text.messageId && event.text.messageId !== activeAssistantMsgId) {
              adoptMessageId(session.id, activeAssistantMsgId, event.text.messageId);
              activeAssistantMsgId = event.text.messageId;
            }
            appendMarkdownDelta(session.id, activeAssistantMsgId, event.text);
            return;
          }
          if (event.kind === 'tool' && event.tool) {
            if (event.tool.message_id && event.tool.message_id !== activeAssistantMsgId) {
              adoptMessageId(session.id, activeAssistantMsgId, event.tool.message_id);
              activeAssistantMsgId = event.tool.message_id;
            }
            applyToolCallEvent(session.id, activeAssistantMsgId, event.tool);
            return;
          }
          if (event.kind === 'error' && event.error) {
            replaceAssistantBlocks(session.id, activeAssistantMsgId, [
              createMarkdownBlock(`错误: ${event.error.message}`),
            ]);
          }
        },
        () => {
          setStreaming(false);
        },
        (err) => {
          console.error('Chat error:', err);
          replaceAssistantBlocks(session.id, activeAssistantMsgId, [
            createMarkdownBlock(`错误: ${err.message}`),
          ]);
          setStreaming(false);
        }
      );
    },
    [
      addMessage,
      appendMarkdownDelta,
      applyToolCallEvent,
      replaceAssistantBlocks,
      adoptMessageId,
      setStreaming,
      getCurrentSession,
    ]
  );

  return { sendMessage };
}
