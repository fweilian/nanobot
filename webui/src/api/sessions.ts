import { apiRequest } from './client';
import type {
  CreateSessionResponse,
  Message,
  SessionDetailDTO,
  SessionSummaryDTO,
} from '../types';

type TimestampValue = number | string;

type SessionSummaryWire = Omit<SessionSummaryDTO, 'createdAt' | 'updatedAt'> & {
  createdAt: TimestampValue;
  updatedAt: TimestampValue;
};

type SessionDetailWire = Omit<SessionDetailDTO, 'createdAt' | 'updatedAt' | 'messages'> & {
  createdAt: TimestampValue;
  updatedAt: TimestampValue;
  messages: Array<Omit<Message, 'createdAt'> & { createdAt: TimestampValue }>;
};

type SessionListResponse = {
  object?: string;
  data: SessionSummaryWire[];
};

type SessionDetailResponse = SessionDetailWire | { data: SessionDetailWire };

function normalizeTimestamp(value: TimestampValue): number {
  if (typeof value === 'number') {
    return value;
  }

  const parsed = Date.parse(value);
  return Number.isNaN(parsed) ? Date.now() : parsed;
}

function normalizeMessage(message: Omit<Message, 'createdAt'> & { createdAt: TimestampValue }): Message {
  return {
    ...message,
    createdAt: normalizeTimestamp(message.createdAt),
  };
}

function normalizeSessionSummary(session: SessionSummaryWire): SessionSummaryDTO {
  return {
    ...session,
    createdAt: normalizeTimestamp(session.createdAt),
    updatedAt: normalizeTimestamp(session.updatedAt),
  };
}

function normalizeSessionDetail(session: SessionDetailWire): SessionDetailDTO {
  return {
    ...normalizeSessionSummary(session),
    messages: session.messages.map(normalizeMessage),
  };
}

export async function listSessions(agentId: string): Promise<SessionSummaryDTO[]> {
  const response = await apiRequest<SessionListResponse | SessionSummaryWire[]>(
    `/v1/agents/${encodeURIComponent(agentId)}/sessions`
  );

  const sessions = Array.isArray(response) ? response : response.data;
  return sessions.map(normalizeSessionSummary);
}

export async function createSession(agentId: string): Promise<CreateSessionResponse> {
  const response = await apiRequest<CreateSessionResponse | SessionSummaryWire>(
    `/v1/agents/${encodeURIComponent(agentId)}/sessions`,
    { method: 'POST' }
  );

  return normalizeSessionSummary(response as SessionSummaryWire);
}

export async function getSessionDetail(
  agentId: string,
  sessionId: string
): Promise<SessionDetailDTO> {
  const response = await apiRequest<SessionDetailResponse>(
    `/v1/agents/${encodeURIComponent(agentId)}/sessions/${encodeURIComponent(sessionId)}`
  );

  return normalizeSessionDetail('data' in response ? response.data : response);
}

export async function renameSession(
  agentId: string,
  sessionId: string,
  title: string
): Promise<SessionSummaryDTO> {
  const response = await apiRequest<SessionSummaryDTO | SessionSummaryWire>(
    `/v1/agents/${encodeURIComponent(agentId)}/sessions/${encodeURIComponent(sessionId)}`,
    {
      method: 'PATCH',
      body: JSON.stringify({ title }),
    }
  );

  return normalizeSessionSummary(response as SessionSummaryWire);
}

export async function deleteSession(agentId: string, sessionId: string): Promise<void> {
  await apiRequest(
    `/v1/agents/${encodeURIComponent(agentId)}/sessions/${encodeURIComponent(sessionId)}`,
    {
      method: 'DELETE',
    }
  );
}
