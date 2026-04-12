import { apiRequest } from './client';

interface Model {
  id: string;
  name?: string;
  object?: string;
}

interface ModelsResponse {
  data: Model[];
  object: string;
}

export async function fetchModels(): Promise<Model[]> {
  const response = await apiRequest<ModelsResponse>('/v1/models');
  return response.data;
}
