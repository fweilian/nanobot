import { apiRequest } from './client';
import type { Agent } from '../types';

interface AgentsResponse {
  object: string;
  data: Array<{
    id: string;
    name?: string;
    description?: string;
    model?: string;
    skills?: string[];
  }>;
}

export async function fetchAgents(): Promise<Agent[]> {
  const response = await apiRequest<AgentsResponse>('/v1/agents');
  return response.data.map((item) => ({
    id: item.id,
    name: item.name || item.id,
    description: item.description,
    model: item.model,
  }));
}
