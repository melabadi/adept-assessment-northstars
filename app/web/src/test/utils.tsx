import { render } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { vi } from 'vitest';
import type {
  Me,
  Meta,
  NamedItem,
  PagedResult,
  Permissions,
  Persona,
  Policy,
  Recommendation,
  RequestDetail,
  RequestSummary,
} from '../api/types';
import { App } from '../App';
import type { Locale } from '../i18n/I18nProvider';

export const meta: Meta = {
  appName: 'RequestHub',
  appVersion: '1.0.0+a619cf0e',
  buildSha: 'a619cf0e8b5d4c3a2b1f',
  environment: 'Development',
  industry: 'general',
  contractVersion: 'requesthub.v1',
  triageProvider: 'sample-rules',
  authMode: 'Development',
  defaultLocale: 'en',
};

export const personas: Persona[] = [
  { id: 'u-ava', displayName: 'Ava Martin', roles: ['Requester'], departments: [] },
  { id: 'u-ben', displayName: 'Ben Okafor', roles: ['Requester', 'Reviewer'], departments: ['IT', 'FAC'] },
  { id: 'u-chloe', displayName: 'Chloé Dubois', roles: ['Requester', 'Approver'], departments: ['IT', 'FAC'] },
  { id: 'u-dan', displayName: 'Dan Rivera', roles: ['Requester', 'Reviewer', 'Approver', 'Admin'], departments: ['IT', 'FAC', 'FIN', 'HR', 'OPS'] },
  { id: 'u-hugo', displayName: 'Hugo Bernard', roles: ['Requester', 'Approver'], departments: ['IT'] },
];

export const departments: NamedItem[] = [
  { id: 'IT', nameEn: 'IT Services', nameFr: 'Services TI' },
  { id: 'FAC', nameEn: 'Facilities', nameFr: 'Installations' },
  { id: 'FIN', nameEn: 'Finance', nameFr: 'Finances' },
  { id: 'HR', nameEn: 'People', nameFr: 'Ressources humaines' },
  { id: 'OPS', nameEn: 'Operations', nameFr: 'Opérations' },
];

export const categories: NamedItem[] = [
  { id: 'equipment', nameEn: 'Equipment', nameFr: 'Équipement' },
  { id: 'access', nameEn: 'Building access', nameFr: 'Accès aux bâtiments' },
];

export const policies: Policy[] = [
  {
    id: 'POL-ROUTE-001',
    version: '1.2',
    kind: 'routing',
    title: 'Computing equipment',
    text: 'Laptops, monitors, docking stations and other computing peripherals route to IT Services (IT).',
    routeTo: 'IT',
    priority: 'Normal',
    threshold: null,
    ref: 'POL-ROUTE-001@1.2',
  },
  {
    id: 'POL-ROUTE-003',
    version: '2.1',
    kind: 'routing',
    title: 'Workplace and building services',
    text: 'Desks, chairs, projectors, meeting rooms and building access badges route to Facilities (FAC).',
    routeTo: 'FAC',
    priority: 'Normal',
    threshold: null,
    ref: 'POL-ROUTE-003@2.1',
  },
];

export function meFor(personaId: string): Me {
  const persona = personas.find((p) => p.id === personaId) ?? personas[0];
  return { ...persona, homeDepartmentId: 'OPS' };
}

const person = (id: string) => ({ id, displayName: personas.find((p) => p.id === id)?.displayName ?? id });

export function summary(overrides: Partial<RequestSummary> = {}): RequestSummary {
  return {
    id: 'REQ-1001',
    title: 'Replacement laptop for field coordinator',
    category: 'equipment',
    departmentId: 'IT',
    priority: 'Normal',
    status: 'Submitted',
    requester: person('u-ava'),
    createdAt: '2026-10-26T06:00:00Z',
    updatedAt: '2026-10-26T06:00:00Z',
    hasRecommendation: false,
    ...overrides,
  };
}

export function paged(items: RequestSummary[]): PagedResult<RequestSummary> {
  return { items, page: 1, pageSize: 20, totalCount: items.length, totalPages: items.length ? 1 : 0 };
}

export const noPermissions: Permissions = {
  canComment: true,
  canUpload: true,
  canTriage: false,
  canRoute: false,
  canDecide: false,
  decideBlockedReason: 'not_approver',
};

export function detail(overrides: Partial<RequestDetail> = {}): RequestDetail {
  return {
    id: 'REQ-1001',
    title: 'Replacement laptop for field coordinator',
    description: 'My laptop no longer holds a charge.',
    category: 'equipment',
    departmentId: 'IT',
    priority: 'Normal',
    status: 'Submitted',
    requester: person('u-ava'),
    createdAt: '2026-10-26T06:00:00Z',
    updatedAt: '2026-10-26T06:00:00Z',
    version: '1',
    decision: null,
    latestRecommendation: null,
    comments: [],
    attachments: [],
    permissions: noPermissions,
    ...overrides,
  };
}

export function recommendation(overrides: Partial<Recommendation> = {}): Recommendation {
  return {
    id: '7d2c1f00-0000-4000-8000-000000000001',
    provider: 'sample-rules',
    isSample: true,
    suggestedDepartmentId: 'FAC',
    suggestedPriority: 'Normal',
    rationale: 'Building access badges are workplace services (POL-ROUTE-003).',
    policyRefs: [{ policyId: 'POL-ROUTE-003', version: '2.1' }],
    confidence: 0.6,
    needsHumanReview: false,
    status: 'Proposed',
    departmentAtRecommendation: 'FAC',
    createdBy: person('u-ben'),
    createdAt: '2026-10-26T06:20:00Z',
    providerTraceId: null,
    confirmedBy: null,
    ...overrides,
  };
}

export function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
}

export function problem(status: number, code: string, detail: string): Response {
  return new Response(JSON.stringify({ title: code, status, detail, code }), {
    status,
    headers: { 'Content-Type': 'application/problem+json' },
  });
}

export interface MockRequest {
  method: string;
  url: URL;
  headers: Headers;
  body: unknown;
}

type Handler = (request: MockRequest) => unknown;

/**
 * Replaces global fetch with a router keyed by "METHOD /path". Handlers return a Response or a
 * JSON-serializable value. Session endpoints (meta, personas, me, lookups) have defaults.
 */
export function mockApi(routes: Record<string, Handler> = {}) {
  const defaults: Record<string, Handler> = {
    'GET /api/meta': () => meta,
    'GET /api/personas': () => personas,
    'GET /api/me': (req) => meFor(req.headers.get('X-RequestHub-User') ?? 'u-ava'),
    'GET /api/departments': () => departments,
    'GET /api/categories': () => categories,
    'GET /api/policies': () => policies,
    'GET /api/requests': () => paged([]),
  };

  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const raw = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url;
    const url = new URL(raw, 'http://localhost');
    const method = (init?.method ?? 'GET').toUpperCase();
    const key = `${method} ${url.pathname}`;
    const handler = routes[key] ?? defaults[key];
    if (!handler) {
      return problem(404, 'route.not_found', `No mock for ${key}`);
    }
    const body = typeof init?.body === 'string' ? JSON.parse(init.body) : init?.body;
    const result = await handler({ method, url, headers: new Headers(init?.headers), body });
    return result instanceof Response ? result : json(result);
  });

  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

/** Calls made to one route, with their request details. */
export function callsTo(fetchMock: ReturnType<typeof mockApi>, method: string, path: string): MockRequest[] {
  return fetchMock.mock.calls
    .map(([input, init]) => {
      const raw = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url;
      return {
        method: (init?.method ?? 'GET').toUpperCase(),
        url: new URL(raw, 'http://localhost'),
        headers: new Headers(init?.headers),
        body: typeof init?.body === 'string' ? JSON.parse(init.body) : init?.body,
      };
    })
    .filter((call) => call.method === method && call.url.pathname === path);
}

export function renderApp(path = '/', options: { locale?: Locale; persona?: string } = {}) {
  if (options.persona) window.localStorage.setItem('rh.persona', options.persona);
  return render(
    <MemoryRouter initialEntries={[path]}>
      <App initialLocale={options.locale} />
    </MemoryRouter>,
  );
}
