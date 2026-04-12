import { apiRequest } from './client';
import type { Agent } from '../types';

export async function fetchAgents(): Promise<Agent[]> {
  return apiRequest<Agent[]>('/v1/agents');
}
