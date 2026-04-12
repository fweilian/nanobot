import { create } from 'zustand';
import type { Agent } from '../types';
import { fetchAgents } from '../api/agents';

interface AgentState {
  agents: Agent[];
  selectedAgent: Agent | null;
  loading: boolean;
  error: string | null;
  loadAgents: () => Promise<void>;
  selectAgent: (agent: Agent | null) => void;
}

export const useAgentStore = create<AgentState>((set) => ({
  agents: [],
  selectedAgent: null,
  loading: false,
  error: null,
  loadAgents: async () => {
    set({ loading: true, error: null });
    try {
      const agents = await fetchAgents();
      set({ agents, loading: false });
    } catch (err) {
      set({ error: err instanceof Error ? err.message : 'Failed to load agents', loading: false });
    }
  },
  selectAgent: (agent) => set({ selectedAgent: agent }),
}));
