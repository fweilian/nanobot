import { useState, useRef, useEffect } from 'react';
import { Send } from 'lucide-react';
import { useAgentStore } from '../../stores/agentStore';
import { useChatStore } from '../../stores/chatStore';
import { useChatStream } from '../../hooks/useChatStream';

export function ChatInput() {
  const [input, setInput] = useState('');
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const { selectedAgent } = useAgentStore();
  const { streaming } = useChatStore();
  const { sendMessage } = useChatStream();

  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
      textareaRef.current.style.height = `${textareaRef.current.scrollHeight}px`;
    }
  }, [input]);

  const handleSubmit = async () => {
    if (!input.trim() || !selectedAgent || streaming) return;

    const content = input.trim();
    setInput('');

    await sendMessage(content, {
      agent: selectedAgent.id,
      model: selectedAgent.model,
    });
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  if (!selectedAgent) {
    return (
      <div className="p-4 border-t border-gray-200 dark:border-gray-700">
        <div className="bg-gray-100 dark:bg-gray-800 rounded-lg p-4 text-center text-gray-500">
          请先在左侧选择一个 Agent
        </div>
      </div>
    );
  }

  return (
    <div className="p-4 border-t border-gray-200 dark:border-gray-700">
      <div className="flex items-end gap-2">
        <textarea
          ref={textareaRef}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="输入消息... (Shift+Enter 换行)"
          className="flex-1 resize-none rounded-lg border border-gray-300 dark:border-gray-600 px-4 py-2 focus:outline-none focus:ring-2 focus:ring-indigo-500 dark:bg-gray-800 dark:text-white"
          rows={1}
          disabled={streaming}
        />
        <button
          onClick={handleSubmit}
          disabled={!input.trim() || streaming}
          className="p-2 rounded-lg bg-indigo-600 text-white hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          <Send size={20} />
        </button>
      </div>
    </div>
  );
}
