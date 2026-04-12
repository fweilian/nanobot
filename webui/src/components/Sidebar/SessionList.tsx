import { MessageSquare, Plus, Trash2 } from 'lucide-react';
import { useChatStore } from '../../stores/chatStore';
import { useAgentStore } from '../../stores/agentStore';

export function SessionList() {
  const { sessions, currentSessionId, selectSession, deleteSession, createSession } =
    useChatStore();
  const { selectedAgent } = useAgentStore();

  const handleNewSession = () => {
    if (selectedAgent) {
      createSession(selectedAgent.id);
    }
  };

  return (
    <div className="flex-1 overflow-y-auto">
      <div className="p-4">
        <button
          onClick={handleNewSession}
          disabled={!selectedAgent}
          className="w-full flex items-center gap-2 px-3 py-2 rounded-lg bg-indigo-600 text-white hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          <Plus size={18} />
          新建会话
        </button>
      </div>
      <div className="space-y-1 px-2">
        {sessions.map((session) => (
          <div
            key={session.id}
            className={`group flex items-center gap-2 px-3 py-2 rounded-lg cursor-pointer transition-colors ${
              session.id === currentSessionId
                ? 'bg-indigo-100 dark:bg-indigo-900'
                : 'hover:bg-gray-100 dark:hover:bg-gray-800'
            }`}
            onClick={() => selectSession(session.id)}
          >
            <MessageSquare size={16} className="flex-shrink-0" />
            <span className="flex-1 truncate text-sm">{session.title}</span>
            <button
              onClick={(e) => {
                e.stopPropagation();
                deleteSession(session.id);
              }}
              className="opacity-0 group-hover:opacity-100 p-1 hover:text-red-500"
            >
              <Trash2 size={14} />
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}
