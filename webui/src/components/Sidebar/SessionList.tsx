import { MessageSquare, Pencil, Plus, Trash2 } from 'lucide-react';
import { useChatStore } from '../../stores/chatStore';
import { useAgentStore } from '../../stores/agentStore';

export function SessionList() {
  const {
    sessions,
    currentSession,
    sessionsLoading,
    loadSession,
    deleteSession,
    renameSession,
    startBlankDraft,
  } = useChatStore();
  const { selectedAgent } = useAgentStore();

  const handleNewSession = () => {
    if (selectedAgent) {
      startBlankDraft(selectedAgent.id);
    }
  };

  const handleRenameSession = (sessionId: string, currentTitle: string) => {
    if (!selectedAgent) {
      return;
    }

    const nextTitle = window.prompt('重命名会话', currentTitle)?.trim();
    if (!nextTitle || nextTitle === currentTitle) {
      return;
    }

    void renameSession(selectedAgent.id, sessionId, nextTitle);
  };

  const handleDeleteSession = (sessionId: string) => {
    if (!selectedAgent) {
      return;
    }

    void deleteSession(selectedAgent.id, sessionId);
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
        {sessionsLoading && (
          <div className="px-3 py-2 text-sm text-gray-500">加载会话中...</div>
        )}
        {!sessionsLoading && sessions.length === 0 && selectedAgent && (
          <div className="px-3 py-2 text-sm text-gray-500">暂无历史会话</div>
        )}
        {sessions.map((session) => (
          <div
            key={session.id}
            className={`group flex items-center gap-2 px-3 py-2 rounded-lg cursor-pointer transition-colors ${
              session.id === currentSession?.id
                ? 'bg-indigo-100 dark:bg-indigo-900'
                : 'hover:bg-gray-100 dark:hover:bg-gray-800'
            }`}
            onClick={() => selectedAgent && void loadSession(selectedAgent.id, session.id)}
          >
            <MessageSquare size={16} className="flex-shrink-0" />
            <span className="flex-1 truncate text-sm">{session.title}</span>
            <button
              onClick={(e) => {
                e.stopPropagation();
                handleRenameSession(session.id, session.title);
              }}
              className="opacity-0 group-hover:opacity-100 p-1 hover:text-indigo-500"
              aria-label={`重命名 ${session.title}`}
            >
              <Pencil size={14} />
            </button>
            <button
              onClick={(e) => {
                e.stopPropagation();
                handleDeleteSession(session.id);
              }}
              className="opacity-0 group-hover:opacity-100 p-1 hover:text-red-500"
              aria-label={`删除 ${session.title}`}
            >
              <Trash2 size={14} />
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}
