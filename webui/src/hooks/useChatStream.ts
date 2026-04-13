import { useCallback } from 'react';
import { createChatStream, sendChatMessage } from '../api/chat';
import { useChatStore } from '../stores/chatStore';
import type { ChatRequest, MessageBlock, SessionDetailDTO } from '../types';

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
    createSession,
    discardSession,
  } = useChatStore();

  const sendMessage = useCallback(
    async (content: string, request: Omit<ChatRequest, 'messages' | 'sessionId'>) => {
      if (!request.agent) {
        throw new Error('Agent is required');
      }

      let session: SessionDetailDTO | null = getCurrentSession();
      const isBlankDraft = !session || session.agentId !== request.agent;

      if (isBlankDraft) {
        session = await createSession(request.agent);
      }

      const sessionId = session.id;

      const rollbackBlankDraft = () => {
        if (isBlankDraft) {
          discardSession(sessionId);
        }
      };

      addMessage(sessionId, { role: 'user', blocks: [createMarkdownBlock(content)] });
      const assistantMsgId = addMessage(sessionId, { role: 'assistant', blocks: [] });
      let activeAssistantMsgId = assistantMsgId;

      setStreaming(true);

      const payload: ChatRequest = {
        ...request,
        sessionId,
        cleanupEmptySessionOnError: isBlankDraft,
        messages: [{ role: 'user', content }],
      };

      const shouldStream = request.stream !== false;

      if (!shouldStream) {
        try {
          const response = await sendChatMessage(payload);
          if (response.message?.id && response.message.id !== activeAssistantMsgId) {
            adoptMessageId(sessionId, activeAssistantMsgId, response.message.id);
            activeAssistantMsgId = response.message.id;
          }
          replaceAssistantBlocks(
            sessionId,
            activeAssistantMsgId,
            response.message?.blocks || [createMarkdownBlock(response.choices[0]?.message.content || '')]
          );
        } catch (err) {
          if (isBlankDraft) {
            rollbackBlankDraft();
            throw err instanceof Error ? err : new Error('Unknown error');
          }

          const message = err instanceof Error ? err.message : 'Unknown error';
          replaceAssistantBlocks(sessionId, activeAssistantMsgId, [
            createMarkdownBlock(`错误: ${message}`),
          ]);
        } finally {
          setStreaming(false);
        }
        return;
      }

      await new Promise<void>((resolve, reject) => {
        const fail = (error: Error) => {
          if (isBlankDraft) {
            rollbackBlankDraft();
          } else {
            replaceAssistantBlocks(sessionId, activeAssistantMsgId, [
              createMarkdownBlock(`错误: ${error.message}`),
            ]);
          }
          setStreaming(false);
          reject(error);
        };

        createChatStream(
          payload,
          (event) => {
            if (event.kind === 'text' && event.text) {
              if (event.text.messageId && event.text.messageId !== activeAssistantMsgId) {
                adoptMessageId(sessionId, activeAssistantMsgId, event.text.messageId);
                activeAssistantMsgId = event.text.messageId;
              }
              appendMarkdownDelta(sessionId, activeAssistantMsgId, event.text);
              return;
            }
            if (event.kind === 'tool' && event.tool) {
              if (event.tool.message_id && event.tool.message_id !== activeAssistantMsgId) {
                adoptMessageId(sessionId, activeAssistantMsgId, event.tool.message_id);
                activeAssistantMsgId = event.tool.message_id;
              }
              applyToolCallEvent(sessionId, activeAssistantMsgId, event.tool);
              return;
            }
            if (event.kind === 'error' && event.error) {
              fail(event.error);
            }
          },
          () => {
            setStreaming(false);
            resolve();
          },
          (err) => {
            console.error('Chat error:', err);
            fail(err);
          }
        );
      });
    },
    [
      addMessage,
      appendMarkdownDelta,
      applyToolCallEvent,
      replaceAssistantBlocks,
      adoptMessageId,
      setStreaming,
      getCurrentSession,
      createSession,
      discardSession,
    ]
  );

  return { sendMessage };
}
