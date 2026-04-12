import { beforeEach, describe, expect, it } from 'vitest';
import { useChatStore } from './chatStore';

describe('chatStore', () => {
  beforeEach(() => {
    useChatStore.setState({
      sessions: [],
      currentSessionId: null,
      streaming: false,
    });
  });

  it('adopts server message ids and preserves block ordering', () => {
    const sessionId = useChatStore.getState().createSession('agent-1');
    const messageId = useChatStore.getState().addMessage(sessionId, {
      role: 'assistant',
      blocks: [],
    });

    useChatStore.getState().adoptMessageId(sessionId, messageId, 'server-m1');
    useChatStore.getState().appendMarkdownDelta(sessionId, 'server-m1', {
      content: 'before',
      blockId: 'text-1',
      sequence: 1,
    });
    useChatStore.getState().applyToolCallEvent(sessionId, 'server-m1', {
      event: 'tool_call_started',
      message_id: 'server-m1',
      block_id: 'tool-1',
      tool_call_id: 'tc1',
      tool_name: 'read_file',
      sequence: 2,
    });
    useChatStore.getState().appendMarkdownDelta(sessionId, 'server-m1', {
      content: 'after',
      blockId: 'text-2',
      sequence: 3,
    });

    const session = useChatStore.getState().getCurrentSession();
    expect(session?.messages[0]?.id).toBe('server-m1');
    expect(session?.messages[0]?.blocks.map((block) => block.type)).toEqual([
      'markdown',
      'tool_call',
      'markdown',
    ]);
  });
});
