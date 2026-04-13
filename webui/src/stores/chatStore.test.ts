import { beforeEach, describe, expect, it, vi } from 'vitest';

const mockCreateSession = vi.fn();
const mockListSessions = vi.fn();

vi.mock('../api/sessions', () => ({
  createSession: mockCreateSession,
  deleteSession: vi.fn(),
  getSessionDetail: vi.fn(),
  listSessions: mockListSessions,
  renameSession: vi.fn(),
}));

import { useChatStore } from './chatStore';

describe('chatStore', () => {
  beforeEach(() => {
    mockCreateSession.mockReset();
    mockListSessions.mockReset();
    useChatStore.setState({
      activeAgentId: null,
      sessions: [],
      currentSession: null,
      sessionsLoading: false,
      sessionLoading: false,
      streaming: false,
      error: null,
    });
  });

  it('keeps blank draft mode separate from durable backend sessions', async () => {
    mockListSessions.mockResolvedValue([
      {
        id: 'session-1',
        agentId: 'agent-1',
        title: '历史会话',
        createdAt: 1,
        updatedAt: 2,
      },
    ]);

    await useChatStore.getState().loadSessionsForAgent('agent-1');
    useChatStore.getState().startBlankDraft('agent-1');

    const state = useChatStore.getState();
    expect(state.activeAgentId).toBe('agent-1');
    expect(state.currentSession).toBeNull();
    expect(state.sessions).toHaveLength(1);
    expect(mockCreateSession).not.toHaveBeenCalled();
  });

  it('adopts server message ids and preserves block ordering for the active session', async () => {
    mockCreateSession.mockResolvedValue({
      id: 'session-1',
      agentId: 'agent-1',
      title: '新对话',
      createdAt: 1,
      updatedAt: 1,
    });

    const session = await useChatStore.getState().createSession('agent-1');
    const messageId = useChatStore.getState().addMessage(session.id, {
      role: 'assistant',
      blocks: [],
    });

    useChatStore.getState().adoptMessageId(session.id, messageId, 'server-m1');
    useChatStore.getState().appendMarkdownDelta(session.id, 'server-m1', {
      content: 'before',
      blockId: 'text-1',
      sequence: 1,
    });
    useChatStore.getState().applyToolCallEvent(session.id, 'server-m1', {
      event: 'tool_call_started',
      message_id: 'server-m1',
      block_id: 'tool-1',
      tool_call_id: 'tc1',
      tool_name: 'read_file',
      sequence: 2,
    });
    useChatStore.getState().appendMarkdownDelta(session.id, 'server-m1', {
      content: 'after',
      blockId: 'text-2',
      sequence: 3,
    });

    const currentSession = useChatStore.getState().getCurrentSession();
    expect(currentSession?.messages[0]?.id).toBe('server-m1');
    expect(currentSession?.messages[0]?.blocks.map((block) => block.type)).toEqual([
      'markdown',
      'tool_call',
      'markdown',
    ]);
  });
});
