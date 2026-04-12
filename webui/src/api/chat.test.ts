import { describe, expect, it } from 'vitest';
import { parseChatStreamData } from './chat';

describe('parseChatStreamData', () => {
  it('parses assistant text delta with correlation fields', () => {
    const result = parseChatStreamData(
      JSON.stringify({
        event: 'assistant_text_delta',
        message_id: 'm1',
        block_id: 'b1',
        sequence: 3,
        content: 'hello',
      })
    );

    expect(result).toEqual({
      kind: 'text',
      text: {
        content: 'hello',
        messageId: 'm1',
        blockId: 'b1',
        sequence: 3,
      },
    });
  });

  it('parses tool call events', () => {
    const result = parseChatStreamData(
      JSON.stringify({
        event: 'tool_call_started',
        message_id: 'm1',
        block_id: 'b2',
        tool_call_id: 't1',
        tool_name: 'read_file',
        sequence: 4,
      })
    );

    expect(result?.kind).toBe('tool');
    expect(result?.tool?.tool_call_id).toBe('t1');
  });
});
