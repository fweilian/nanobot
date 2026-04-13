import { useEffect } from 'react';
import { Bot } from 'lucide-react';
import { useAgentStore } from '../../stores/agentStore';
import { useChatStore } from '../../stores/chatStore';

export function AgentSelector() {
  const { agents, selectedAgent, loading, error, loadAgents, selectAgent } =
    useAgentStore();
  const { clearAgentSelection, loadSessionsForAgent } = useChatStore();

  useEffect(() => {
    loadAgents();
  }, [loadAgents]);

  const handleAgentChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    const agentId = e.target.value;
    if (agentId === '') {
      selectAgent(null);
      clearAgentSelection();
    } else {
      const agent = agents.find((a) => a.id === agentId);
      if (agent) {
        selectAgent(agent);
        void loadSessionsForAgent(agent.id);
      }
    }
  };

  return (
    <div className="p-4 border-b border-gray-200 dark:border-gray-700">
      <div className="flex items-center gap-2 mb-2">
        <Bot size={18} />
        <label className="text-sm font-medium">Agent</label>
      </div>
      <select
        value={selectedAgent?.id || ''}
        onChange={handleAgentChange}
        disabled={loading}
        className="w-full rounded-lg border border-gray-300 dark:border-gray-600 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 dark:bg-gray-800"
      >
        <option value="">选择 Agent...</option>
        {agents.map((agent) => (
          <option key={agent.id} value={agent.id}>
            {agent.name}
          </option>
        ))}
      </select>
      {error && <p className="mt-2 text-xs text-red-500">{error}</p>}
      {selectedAgent && (
        <p className="mt-2 text-xs text-gray-500">{selectedAgent.description}</p>
      )}
    </div>
  );
}
