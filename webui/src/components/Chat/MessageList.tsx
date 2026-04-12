import { useChatStore } from '../../stores/chatStore';
import { Message } from './Message';

export function MessageList() {
  // Subscribe to sessions and currentSessionId to trigger re-renders
  const sessions = useChatStore((state) => state.sessions);
  const currentSessionId = useChatStore((state) => state.currentSessionId);
  const session = sessions.find((s) => s.id === currentSessionId) || null;

  if (!session) {
    return (
      <div className="flex items-center justify-center h-full text-gray-500">
        选择 Agent 并开始对话
      </div>
    );
  }

  if (session.messages.length === 0) {
    return (
      <div className="flex items-center justify-center h-full text-gray-500">
        开始发送消息吧
      </div>
    );
  }

  return (
    <div className="flex-1 overflow-y-auto bg-gray-50/70 p-6 dark:bg-gray-950">
      <div className="mx-auto flex max-w-5xl flex-col gap-4">
      {session.messages.map((msg) => (
        <Message key={msg.id} message={msg} />
      ))}
      </div>
    </div>
  );
}
