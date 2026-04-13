import { useChatStore } from '../../stores/chatStore';
import { useAgentStore } from '../../stores/agentStore';
import { Message } from './Message';

export function MessageList() {
  const session = useChatStore((state) => state.currentSession);
  const sessionLoading = useChatStore((state) => state.sessionLoading);
  const { selectedAgent } = useAgentStore();

  if (!selectedAgent) {
    return (
      <div className="flex items-center justify-center h-full text-gray-500">
        选择 Agent 并开始对话
      </div>
    );
  }

  if (sessionLoading) {
    return (
      <div className="flex items-center justify-center h-full text-gray-500">
        加载会话中...
      </div>
    );
  }

  if (!session || session.messages.length === 0) {
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
