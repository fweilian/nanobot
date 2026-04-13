import { useConfigStore } from '../stores/configStore';

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
    this.name = 'ApiError';
  }
}

export async function apiRequest<T>(
  endpoint: string,
  options: RequestInit = {}
): Promise<T> {
  const { apiUrl, apiKey } = useConfigStore.getState();

  const headers = new Headers({
    'Content-Type': 'application/json',
  });

  if (options.headers) {
    const extraHeaders = new Headers(options.headers as HeadersInit);
    extraHeaders.forEach((value, key) => headers.set(key, value));
  }

  if (apiKey) {
    headers.set('Authorization', `Bearer ${apiKey}`);
  }

  const response = await fetch(`${apiUrl}${endpoint}`, {
    ...options,
    headers,
  });

  if (!response.ok) {
    throw new ApiError(response.status, await response.text());
  }

  if (response.status === 204) {
    return undefined as T;
  }

  const text = await response.text();
  if (!text.trim()) {
    return undefined as T;
  }

  return JSON.parse(text) as T;
}
