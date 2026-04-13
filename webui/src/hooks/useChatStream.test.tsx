import { useEffect } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { act } from 'react-dom/test-utils';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { ChatRequest } from '../types';

const mockCreateSession = vi.fn();
const mockSendChatMessage = vi.fn();
const mockCreateChatStream = vi.fn();

vi.mock('../api/sessions', () => ({
  createSession: mockCreateSession,
  deleteSession: vi.fn(),
  getSessionDetail: vi.fn(),
  listSessions: vi.fn(),
  renameSession: vi.fn(),
}));

vi.mock('../api/chat', () => ({
  createChatStream: mockCreateChatStream,
  sendChatMessage: mockSendChatMessage,
}));

import { useChatStream } from './useChatStream';
import { useChatStore } from '../stores/chatStore';

type SendMessage = (
  content: string,
  request: Omit<ChatRequest, 'messages' | 'sessionId'>
) => Promise<void>;

function Harness({ onReady }: { onReady: (sendMessage: SendMessage) => void }) {
  const { sendMessage } = useChatStream();

  useEffect(() => {
    onReady(sendMessage);
  }, [onReady, sendMessage]);

  return null;
}

describe('useChatStream', () => {
  let container: HTMLDivElement;
  let root: Root;
  let sendMessage: SendMessage = async () => {};

  beforeEach(async () => {
    mockCreateSession.mockReset();
    mockSendChatMessage.mockReset();
    mockCreateChatStream.mockReset();
    useChatStore.setState({
      activeAgentId: null,
      sessions: [],
      currentSession: null,
      sessionsLoading: false,
      sessionLoading: false,
      streaming: false,
      error: null,
    });

    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);

    await act(async () => {
      root.render(
        <Harness
          onReady={(nextSendMessage) => {
            sendMessage = nextSendMessage;
          }}
        />
      );
    });
  });

  afterEach(async () => {
    await act(async () => {
      root.unmount();
    });
    container.remove();
  });

  it('creates a backend session before the first blank-draft send', async () => {
    mockCreateSession.mockResolvedValue({
      id: 'session-1',
      agentId: 'agent-1',
      title: '新对话',
      createdAt: 1,
      updatedAt: 1,
    });
    mockSendChatMessage.mockResolvedValue({
      id: 'chat-1',
      choices: [
        {
          message: { role: 'assistant', content: 'reply:hello' },
          finish_reason: 'stop',
        },
      ],
      message: {
        id: 'asst-server',
        role: 'assistant',
        blocks: [
          {
            id: 'assistant-markdown',
            type: 'markdown',
            content: 'reply:hello',
            sequence: 0,
          },
        ],
      },
    });

    useChatStore.getState().startBlankDraft('agent-1');

    await act(async () => {
      await sendMessage('hello', {
        agent: 'agent-1',
        model: 'test-model',
        stream: false,
      });
    });

    expect(mockCreateSession).toHaveBeenCalledWith('agent-1');
    expect(
      mockCreateSession.mock.invocationCallOrder[0]
    ).toBeLessThan(mockSendChatMessage.mock.invocationCallOrder[0]);
    expect(mockSendChatMessage).toHaveBeenCalledWith({
      agent: 'agent-1',
      model: 'test-model',
      sessionId: 'session-1',
      stream: false,
      messages: [{ role: 'user', content: 'hello' }],
    });

    const state = useChatStore.getState();
    expect(state.currentSession?.id).toBe('session-1');
    expect(state.currentSession?.messages.map((message) => message.role)).toEqual([
      'user',
      'assistant',
    ]);
    expect(state.currentSession?.messages[1]?.blocks).toEqual([
      {
        id: 'assistant-markdown',
        type: 'markdown',
        content: 'reply:hello',
        sequence: 0,
      },
    ]);
  });
});
