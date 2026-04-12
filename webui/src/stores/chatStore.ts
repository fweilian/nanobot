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
  addMessage: (sessionId: string, message: Omit<Message, 'id' | 'createdAt'>) => string; // returns the generated message id
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
      addMessage: (sessionId, message) => {
        const newId = generateId();
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
                      ? message.content.slice(0, 20) + (message.content.length > 20 ? '...' : '')
                      : s.title,
                }
              : s
          ),
        }));
        return newId;
      },
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
