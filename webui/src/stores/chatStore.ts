import { create } from 'zustand';
import {
  createSession as createBackendSession,
  deleteSession as deleteBackendSession,
  getSessionDetail,
  listSessions,
  renameSession as renameBackendSession,
} from '../api/sessions';
import type {
  CreateSessionResponse,
  Message,
  MessageBlock,
  SessionDetailDTO,
  SessionSummaryDTO,
  ToolCallEventPayload,
} from '../types';

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

function getDraftTitle(content: string, fallback: string): string {
  if (!content) {
    return fallback;
  }

  return content.slice(0, 20) + (content.length > 20 ? '...' : '');
}

function toSessionDetail(session: CreateSessionResponse): SessionDetailDTO {
  return {
    ...session,
    messages: [],
  };
}

function upsertSessionSummary(
  sessions: SessionSummaryDTO[],
  summary: SessionSummaryDTO
): SessionSummaryDTO[] {
  return [summary, ...sessions.filter((session) => session.id !== summary.id)].sort(
    (left, right) => right.updatedAt - left.updatedAt
  );
}

interface ChatState {
  activeAgentId: string | null;
  sessions: SessionSummaryDTO[];
  currentSession: SessionDetailDTO | null;
  sessionsLoading: boolean;
  sessionLoading: boolean;
  streaming: boolean;
  error: string | null;
  loadSessionsForAgent: (agentId: string) => Promise<void>;
  clearAgentSelection: () => void;
  startBlankDraft: (agentId: string) => void;
  loadSession: (agentId: string, sessionId: string) => Promise<void>;
  createSession: (agentId: string) => Promise<SessionDetailDTO>;
  renameSession: (agentId: string, sessionId: string, title: string) => Promise<void>;
  deleteSession: (agentId: string, sessionId: string) => Promise<void>;
  discardSession: (sessionId: string) => void;
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
  getCurrentSession: () => SessionDetailDTO | null;
}

export const useChatStore = create<ChatState>()((set, get) => ({
  activeAgentId: null,
  sessions: [],
  currentSession: null,
  sessionsLoading: false,
  sessionLoading: false,
  streaming: false,
  error: null,
  loadSessionsForAgent: async (agentId) => {
    set({
      activeAgentId: agentId,
      sessions: [],
      currentSession: null,
      sessionsLoading: true,
      sessionLoading: false,
      error: null,
    });

    try {
      const sessions = await listSessions(agentId);
      if (get().activeAgentId !== agentId) {
        return;
      }

      set({
        sessions,
        sessionsLoading: false,
      });
    } catch (err) {
      if (get().activeAgentId !== agentId) {
        return;
      }

      set({
        sessionsLoading: false,
        error: err instanceof Error ? err.message : 'Failed to load sessions',
      });
    }
  },
  clearAgentSelection: () =>
    set({
      activeAgentId: null,
      sessions: [],
      currentSession: null,
      sessionsLoading: false,
      sessionLoading: false,
      streaming: false,
      error: null,
    }),
  startBlankDraft: (agentId) =>
    set({
      activeAgentId: agentId,
      currentSession: null,
      sessionLoading: false,
      error: null,
    }),
  loadSession: async (agentId, sessionId) => {
    set({
      activeAgentId: agentId,
      currentSession: null,
      sessionLoading: true,
      error: null,
    });

    try {
      const session = await getSessionDetail(agentId, sessionId);
      if (get().activeAgentId !== agentId) {
        return;
      }

      set((state) => ({
        currentSession: session,
        sessionLoading: false,
        sessions: upsertSessionSummary(state.sessions, {
          id: session.id,
          agentId: session.agentId,
          title: session.title,
          createdAt: session.createdAt,
          updatedAt: session.updatedAt,
        }),
      }));
    } catch (err) {
      if (get().activeAgentId !== agentId) {
        return;
      }

      set({
        sessionLoading: false,
        error: err instanceof Error ? err.message : 'Failed to load session',
      });
    }
  },
  createSession: async (agentId) => {
    const created = toSessionDetail(await createBackendSession(agentId));

    set((state) => ({
      activeAgentId: agentId,
      currentSession: created,
      error: null,
      sessions: upsertSessionSummary(state.sessions, {
        id: created.id,
        agentId: created.agentId,
        title: created.title,
        createdAt: created.createdAt,
        updatedAt: created.updatedAt,
      }),
    }));

    return created;
  },
  renameSession: async (agentId, sessionId, title) => {
    const nextTitle = title.trim();
    if (!nextTitle) {
      return;
    }

    const renamed = await renameBackendSession(agentId, sessionId, nextTitle);
    set((state) => ({
      currentSession:
        state.currentSession?.id === sessionId
          ? { ...state.currentSession, title: renamed.title, updatedAt: renamed.updatedAt }
          : state.currentSession,
      sessions: upsertSessionSummary(state.sessions, renamed),
      error: null,
    }));
  },
  deleteSession: async (agentId, sessionId) => {
    await deleteBackendSession(agentId, sessionId);
    set((state) => ({
      currentSession: state.currentSession?.id === sessionId ? null : state.currentSession,
      sessions: state.sessions.filter((session) => session.id !== sessionId),
      error: null,
    }));
  },
  discardSession: (sessionId) =>
    set((state) => ({
      currentSession: state.currentSession?.id === sessionId ? null : state.currentSession,
      sessions: state.sessions.filter((session) => session.id !== sessionId),
    })),
  addMessage: (sessionId, message) => {
    const session = get().currentSession;
    if (!session || session.id !== sessionId) {
      return '';
    }

    const newId = generateId();
    const plainText = message.role === 'user' ? getMessagePlainText({ blocks: message.blocks }) : '';
    const now = Date.now();
    const nextTitle =
      session.messages.length === 0 && message.role === 'user'
        ? getDraftTitle(plainText, session.title)
        : session.title;

    set((state) => {
      if (!state.currentSession || state.currentSession.id !== sessionId) {
        return state;
      }

      const nextSession: SessionDetailDTO = {
        ...state.currentSession,
        title: nextTitle,
        updatedAt: now,
        messages: [
          ...state.currentSession.messages,
          {
            ...message,
            id: newId,
            createdAt: now,
          },
        ],
      };

      return {
        currentSession: nextSession,
        sessions: upsertSessionSummary(state.sessions, {
          id: nextSession.id,
          agentId: nextSession.agentId,
          title: nextSession.title,
          createdAt: nextSession.createdAt,
          updatedAt: nextSession.updatedAt,
        }),
      };
    });

    return newId;
  },
  appendMarkdownDelta: (sessionId, messageId, payload) =>
    set((state) => {
      if (!state.currentSession || state.currentSession.id !== sessionId) {
        return state;
      }

      return {
        currentSession: {
          ...state.currentSession,
          messages: state.currentSession.messages.map((message) =>
            message.id === messageId
              ? {
                  ...message,
                  blocks: (() => {
                    const markdownId = payload.blockId || 'assistant-markdown';
                    const existing = message.blocks.find(
                      (block): block is Extract<MessageBlock, { type: 'markdown' }> =>
                        block.type === 'markdown' && block.id === markdownId
                    );
                    const nextBlock: MessageBlock = {
                      id: existing?.id || markdownId,
                      type: 'markdown',
                      content: (existing?.content || '') + payload.content,
                      sequence: existing?.sequence ?? payload.sequence ?? 0,
                    };
                    const remaining = message.blocks.filter(
                      (block) => !(block.type === 'markdown' && block.id === markdownId)
                    );
                    return [...remaining, nextBlock].sort((left, right) => left.sequence - right.sequence);
                  })(),
                }
              : message
          ),
        },
      };
    }),
  applyToolCallEvent: (sessionId, messageId, event) =>
    set((state) => {
      if (!state.currentSession || state.currentSession.id !== sessionId) {
        return state;
      }

      return {
        currentSession: {
          ...state.currentSession,
          messages: state.currentSession.messages.map((message) => {
            if (message.id !== messageId) return message;
            const existing = message.blocks.find(
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
            const remaining = message.blocks.filter(
              (block) => !(block.type === 'tool_call' && block.toolCallId === event.tool_call_id)
            );
            return {
              ...message,
              blocks: [...remaining, nextBlock].sort((left, right) => left.sequence - right.sequence),
            };
          }),
        },
      };
    }),
  replaceAssistantBlocks: (sessionId, messageId, blocks) =>
    set((state) => {
      if (!state.currentSession || state.currentSession.id !== sessionId) {
        return state;
      }

      return {
        currentSession: {
          ...state.currentSession,
          messages: state.currentSession.messages.map((message) =>
            message.id === messageId ? { ...message, blocks } : message
          ),
        },
      };
    }),
  adoptMessageId: (sessionId, currentId, nextId) =>
    set((state) => {
      if (!state.currentSession || state.currentSession.id !== sessionId) {
        return state;
      }

      return {
        currentSession: {
          ...state.currentSession,
          messages: state.currentSession.messages.map((message) =>
            message.id === currentId ? { ...message, id: nextId } : message
          ),
        },
      };
    }),
  setStreaming: (streaming) => set({ streaming }),
  getCurrentSession: () => get().currentSession,
}));
