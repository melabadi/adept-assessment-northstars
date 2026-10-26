import type {
  Attachment,
  AuditEvent,
  AuthMode,
  Comment,
  CreateRequestInput,
  Decision,
  DecisionOutcome,
  ListQuery,
  Me,
  Meta,
  NamedItem,
  PagedResult,
  Persona,
  Policy,
  Recommendation,
  RequestDetail,
  RequestSummary,
} from './types';

export const PERSONA_HEADER = 'X-RequestHub-User';
export const CLIENT_HEADER = 'X-RequestHub-Client';
export const IDEMPOTENCY_HEADER = 'Idempotency-Key';
export const PERSONA_COOKIE = 'rh_user';

/** An HTTP or network failure. `code` is the RFC 7807 `code` extension (for example `decision.self_approval`). */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string | null;
  readonly detail: string;
  readonly body: Record<string, unknown> | null;

  constructor(status: number, code: string | null, detail: string, body: Record<string, unknown> | null = null) {
    super(detail);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.detail = detail;
    this.body = body;
  }

  get isNetworkError(): boolean {
    return this.status === 0;
  }
}

export function isAbortError(error: unknown): boolean {
  return typeof error === 'object' && error !== null && (error as { name?: unknown }).name === 'AbortError';
}

export function toApiError(error: unknown): ApiError {
  if (error instanceof ApiError) return error;
  const message = error instanceof Error ? error.message : String(error);
  return new ApiError(0, 'network.error', message);
}

interface ClientConfig {
  authMode: AuthMode;
  personaId: string | null;
}

const config: ClientConfig = { authMode: 'Development', personaId: null };

export function configureApi(next: Partial<ClientConfig>): void {
  Object.assign(config, next);
}

export function getAuthMode(): AuthMode {
  return config.authMode;
}

/**
 * Development auth mode only: the API also reads the persona from this cookie, so plain
 * `<a href>` attachment downloads are authorized without custom headers.
 */
export function setPersonaCookie(personaId: string): void {
  document.cookie = `${PERSONA_COOKIE}=${encodeURIComponent(personaId)}; path=/; SameSite=Strict`;
}

export function readPersonaCookie(): string | null {
  const match = document.cookie.split(';').map((c) => c.trim()).find((c) => c.startsWith(`${PERSONA_COOKIE}=`));
  return match ? decodeURIComponent(match.slice(PERSONA_COOKIE.length + 1)) : null;
}

/** A random v4 UUID. Falls back to getRandomValues where randomUUID is unavailable (non-secure contexts). */
export function newIdempotencyKey(): string {
  const c = globalThis.crypto;
  if (typeof c?.randomUUID === 'function') return c.randomUUID();
  const bytes = new Uint8Array(16);
  if (typeof c?.getRandomValues === 'function') {
    c.getRandomValues(bytes);
  } else {
    for (let i = 0; i < bytes.length; i++) bytes[i] = Math.floor(Math.random() * 256);
  }
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

interface RequestOptions {
  method?: 'GET' | 'POST' | 'PUT';
  json?: unknown;
  form?: FormData;
  idempotencyKey?: string;
  signal?: AbortSignal;
}

async function readBody(response: Response): Promise<unknown> {
  if (response.status === 204) return null;
  const text = await response.text();
  if (!text) return null;
  const type = response.headers.get('content-type') ?? '';
  if (type.includes('json')) {
    try {
      return JSON.parse(text);
    } catch {
      return text;
    }
  }
  return text;
}

function errorFrom(response: Response, body: unknown): ApiError {
  const problem = body && typeof body === 'object' ? (body as Record<string, unknown>) : null;
  const code = typeof problem?.code === 'string' ? problem.code : null;
  const detail =
    (typeof problem?.detail === 'string' && problem.detail) ||
    (typeof problem?.title === 'string' && problem.title) ||
    (typeof body === 'string' && body.length < 300 && body) ||
    response.statusText ||
    `HTTP ${response.status}`;
  return new ApiError(response.status, code, detail, problem);
}

export async function apiRequest<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const method = options.method ?? 'GET';
  const headers = new Headers({ Accept: 'application/json, application/problem+json' });
  if (config.authMode === 'Development' && config.personaId) {
    headers.set(PERSONA_HEADER, config.personaId);
  }
  if (method !== 'GET') {
    // CSRF guard: state-changing calls must carry a custom header a cross-site form cannot send.
    headers.set(CLIENT_HEADER, 'web');
  }
  if (options.idempotencyKey) {
    headers.set(IDEMPOTENCY_HEADER, options.idempotencyKey);
  }

  let body: BodyInit | undefined;
  if (options.form) {
    body = options.form;
  } else if (options.json !== undefined) {
    headers.set('Content-Type', 'application/json');
    body = JSON.stringify(options.json);
  }

  let response: Response;
  try {
    response = await fetch(path, { method, headers, body, signal: options.signal, credentials: 'same-origin' });
  } catch (error) {
    if (isAbortError(error)) throw error;
    throw new ApiError(0, 'network.error', error instanceof Error ? error.message : 'Network error');
  }

  const data = await readBody(response);
  if (!response.ok) {
    throw errorFrom(response, data);
  }
  return data as T;
}

const enc = encodeURIComponent;

function queryString(query: ListQuery): string {
  const params = new URLSearchParams();
  params.set('scope', query.scope);
  if (query.status) params.set('status', query.status);
  if (query.department) params.set('department', query.department);
  if (query.priority) params.set('priority', query.priority);
  if (query.q) params.set('q', query.q);
  params.set('page', String(query.page ?? 1));
  params.set('pageSize', String(query.pageSize ?? 20));
  return params.toString();
}

export const api = {
  meta: (signal?: AbortSignal) => apiRequest<Meta>('/api/meta', { signal }),
  personas: (signal?: AbortSignal) => apiRequest<Persona[]>('/api/personas', { signal }),
  me: (signal?: AbortSignal) => apiRequest<Me>('/api/me', { signal }),
  departments: (signal?: AbortSignal) => apiRequest<NamedItem[]>('/api/departments', { signal }),
  categories: (signal?: AbortSignal) => apiRequest<NamedItem[]>('/api/categories', { signal }),
  policies: (signal?: AbortSignal) => apiRequest<Policy[]>('/api/policies', { signal }),

  listRequests: (query: ListQuery, signal?: AbortSignal) =>
    apiRequest<PagedResult<RequestSummary>>(`/api/requests?${queryString(query)}`, { signal }),
  getRequest: (id: string, signal?: AbortSignal) => apiRequest<RequestDetail>(`/api/requests/${enc(id)}`, { signal }),
  history: (id: string, signal?: AbortSignal) => apiRequest<AuditEvent[]>(`/api/requests/${enc(id)}/history`, { signal }),

  createRequest: (input: CreateRequestInput, idempotencyKey: string) =>
    apiRequest<RequestDetail>('/api/requests', { method: 'POST', json: input, idempotencyKey }),
  decide: (id: string, outcome: DecisionOutcome, comment: string | null, idempotencyKey: string) =>
    apiRequest<Decision>(`/api/requests/${enc(id)}/decisions`, { method: 'POST', json: { outcome, comment }, idempotencyKey }),
  addComment: (id: string, body: string) =>
    apiRequest<Comment>(`/api/requests/${enc(id)}/comments`, { method: 'POST', json: { body } }),
  reroute: (id: string, departmentId: string, reason: string | null) =>
    apiRequest<RequestDetail>(`/api/requests/${enc(id)}/routing`, { method: 'PUT', json: { departmentId, reason } }),
  recommend: (id: string) =>
    apiRequest<Recommendation>(`/api/requests/${enc(id)}/triage-recommendations`, { method: 'POST' }),
  confirmRecommendation: (id: string, recommendationId: string) =>
    apiRequest<RequestDetail>(`/api/requests/${enc(id)}/triage-recommendations/${enc(recommendationId)}/confirm`, { method: 'POST' }),
  uploadAttachment: (id: string, file: File) => {
    const form = new FormData();
    form.append('file', file, file.name);
    return apiRequest<Attachment>(`/api/requests/${enc(id)}/attachments`, { method: 'POST', form });
  },
};
