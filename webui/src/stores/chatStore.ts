import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import type { Message, MessageBlock, Session, ToolCallEventPayload } from '../types';

function generateId(): string {
  return crypto.randomUUID();
}

function getMessagePlainText(message: Pick<Message, 'blocks'>): string {
  return message.blocks
    .filter((block): block is Extract<MessageBlock, { type: 'markdown' }> => block.type === 'markdown')
    .map((block) => block.content)
    .join('\n')
    .trim();
}

interface ChatState {
  sessions: Session[];
  currentSessionId: string | null;
  streaming: boolean;
  createSession: (agentId: string) => string;
  deleteSession: (id: string) => void;
  selectSession: (id: string) => void;
  addMessage: (
    sessionId: string,
    message: Omit<Message, 'id' | 'createdAt'>
  ) => string;
  appendMarkdownDelta: (
    sessionId: string,
    messageId: string,
    payload: { content: string; blockId?: string; sequence?: number }
  ) => void;
  applyToolCallEvent: (sessionId: string, messageId: string, event: ToolCallEventPayload) => void;
  replaceAssistantBlocks: (sessionId: string, messageId: string, blocks: MessageBlock[]) => void;
  adoptMessageId: (sessionId: string, currentId: string, nextId: string) => void;
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
      addMessage: (sessionId, message) => {
        const newId = generateId();
        const plainText =
          message.role === 'user'
            ? getMessagePlainText({ blocks: message.blocks })
            : '';
        set((state) => ({
          sessions: state.sessions.map((s) =>
            s.id === sessionId
              ? {
                  ...s,
                  messages: [
                    ...s.messages,
                    {
                      ...message,
                      id: newId,
                      createdAt: Date.now(),
                    },
                  ],
                  updatedAt: Date.now(),
                  title:
                    s.messages.length === 0 && message.role === 'user'
                      ? plainText.slice(0, 20) + (plainText.length > 20 ? '...' : '')
                      : s.title,
                }
              : s
          ),
        }));
        return newId;
      },
      appendMarkdownDelta: (sessionId, messageId, payload) =>
        set((state) => ({
          sessions: state.sessions.map((s) =>
            s.id === sessionId
              ? {
                  ...s,
                  messages: s.messages.map((m) =>
                    m.id === messageId
                      ? {
                          ...m,
                          blocks: (() => {
                            const markdownId = payload.blockId || 'assistant-markdown';
                            const existing = m.blocks.find(
                              (block): block is Extract<MessageBlock, { type: 'markdown' }> =>
                                block.type === 'markdown' && block.id === markdownId
                            );
                            const nextBlock: MessageBlock = {
                              id: existing?.id || markdownId,
                              type: 'markdown',
                              content: (existing?.content || '') + payload.content,
                              sequence: existing?.sequence ?? payload.sequence ?? 0,
                            };
                            const remaining = m.blocks.filter(
                              (block) => !(block.type === 'markdown' && block.id === markdownId)
                            );
                            return [...remaining, nextBlock].sort((a, b) => a.sequence - b.sequence);
                          })(),
                        }
                      : m
                  ),
                }
              : s
          ),
        })),
      applyToolCallEvent: (sessionId, messageId, event) =>
        set((state) => ({
          sessions: state.sessions.map((s) =>
            s.id === sessionId
              ? {
                  ...s,
                  messages: s.messages.map((m) => {
                    if (m.id !== messageId) return m;
                    const existing = m.blocks.find(
                      (block): block is Extract<MessageBlock, { type: 'tool_call' }> =>
                        block.type === 'tool_call' && block.toolCallId === event.tool_call_id
                    );
                    const nextBlock: MessageBlock = {
                      id: existing?.id || event.block_id || generateId(),
                      type: 'tool_call',
                      toolCallId: event.tool_call_id,
                      toolName: event.tool_name,
                      status:
                        event.event === 'tool_call_started'
                          ? 'started'
                          : event.event === 'tool_call_updated'
                            ? 'streaming'
                            : event.event === 'tool_call_completed'
                              ? 'completed'
                              : 'failed',
                      argsText: event.args_text ?? existing?.argsText,
                      resultText: event.result_text ?? existing?.resultText,
                      sequence: event.sequence,
                    };
                    const remaining = m.blocks.filter(
                      (block) =>
                        !(block.type === 'tool_call' && block.toolCallId === event.tool_call_id)
                    );
                    return {
                      ...m,
                      blocks: [...remaining, nextBlock].sort(
                        (a, b) => a.sequence - b.sequence
                      ),
                    };
                  }),
                }
              : s
          ),
        })),
      replaceAssistantBlocks: (sessionId, messageId, blocks) =>
        set((state) => ({
          sessions: state.sessions.map((s) =>
            s.id === sessionId
              ? {
                  ...s,
                  messages: s.messages.map((m) =>
                    m.id === messageId ? { ...m, blocks } : m
                  ),
                }
              : s
          ),
        })),
      adoptMessageId: (sessionId, currentId, nextId) =>
        set((state) => ({
          sessions: state.sessions.map((s) =>
            s.id === sessionId
              ? {
                  ...s,
                  messages: s.messages.map((m) =>
                    m.id === currentId ? { ...m, id: nextId } : m
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
    { name: 'nanobot-sessions-v2' }
  )
);
