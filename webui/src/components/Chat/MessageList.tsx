import { useChatStore } from '../../stores/chatStore';
import { Message } from './Message';

export function MessageList() {
  const { getCurrentSession } = useChatStore();
  const session = getCurrentSession();

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
    <div className="flex-1 overflow-y-auto p-4 space-y-4">
      {session.messages.map((msg) => (
        <Message key={msg.id} message={msg} />
      ))}
    </div>
  );
}
