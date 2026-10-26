import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import {
  ApiError,
  api,
  configureApi,
  isAbortError,
  readPersonaCookie,
  setPersonaCookie,
  toApiError,
} from '../api/client';
import type { AuthMode, Me, Meta, NamedItem, Persona, Policy } from '../api/types';
import { useI18n } from '../i18n/I18nProvider';

export const DEFAULT_PERSONA = 'u-ava';
export const PERSONA_STORAGE_KEY = 'rh.persona';

export interface ReadySession {
  status: 'ready';
  meta: Meta;
  authMode: AuthMode;
  personas: Persona[];
  personaId: string | null;
  me: Me;
  departments: NamedItem[];
  categories: NamedItem[];
  policies: Policy[];
  /** Changes whenever the acting user changes, so routed pages remount and refetch. */
  sessionKey: string;
}

export type SessionState =
  | { status: 'loading' }
  | { status: 'error'; error: ApiError }
  | { status: 'signed-out'; meta: Meta }
  | ReadySession;

interface SessionContextValue {
  state: SessionState;
  switching: boolean;
  switchPersona(personaId: string): Promise<void>;
  retry(): void;
}

const SessionContext = createContext<SessionContextValue | null>(null);

function storedPersona(): string | null {
  try {
    return window.localStorage.getItem(PERSONA_STORAGE_KEY);
  } catch {
    return null;
  }
}

function rememberPersona(personaId: string) {
  setPersonaCookie(personaId);
  try {
    window.localStorage.setItem(PERSONA_STORAGE_KEY, personaId);
  } catch {
    // The cookie alone is enough for this session.
  }
  configureApi({ personaId });
}

function pickPersona(personas: Persona[], preferred: (string | null)[]): string {
  for (const id of preferred) {
    if (id && personas.some((p) => p.id === id)) return id;
  }
  return personas.find((p) => p.id === DEFAULT_PERSONA)?.id ?? personas[0]?.id ?? DEFAULT_PERSONA;
}

async function loadSession(signal: AbortSignal): Promise<Exclude<SessionState, { status: 'loading' } | { status: 'error' }>> {
  // Personas only exist in Development auth mode (404 otherwise); fetch them alongside meta to save a round trip.
  const [meta, personasResult] = await Promise.all([
    api.meta(signal),
    api.personas(signal).catch((error: unknown) => error),
  ]);
  const authMode: AuthMode = meta.authMode === 'EasyAuth' ? 'EasyAuth' : 'Development';
  configureApi({ authMode, personaId: null });

  let personas: Persona[] = [];
  let personaId: string | null = null;
  if (authMode === 'Development') {
    if (!Array.isArray(personasResult)) throw personasResult;
    personas = personasResult;
    personaId = pickPersona(personas, [storedPersona(), readPersonaCookie()]);
    rememberPersona(personaId);
  }

  try {
    const [me, departments, categories, policies] = await Promise.all([
      api.me(signal),
      api.departments(signal),
      api.categories(signal),
      api.policies(signal),
    ]);
    return { status: 'ready', meta, authMode, personas, personaId, me, departments, categories, policies, sessionKey: me.id };
  } catch (error) {
    if (error instanceof ApiError && error.status === 401 && authMode === 'EasyAuth') {
      return { status: 'signed-out', meta };
    }
    throw error;
  }
}

export function SessionProvider({ children }: { children: ReactNode }) {
  const { applyDefaultLocale } = useI18n();
  const [state, setState] = useState<SessionState>({ status: 'loading' });
  const [switching, setSwitching] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const switchSeq = useRef(0);

  useEffect(() => {
    const controller = new AbortController();
    setState({ status: 'loading' });
    loadSession(controller.signal)
      .then((next) => {
        applyDefaultLocale(next.meta.defaultLocale);
        setState(next);
      })
      .catch((error: unknown) => {
        if (!isAbortError(error)) setState({ status: 'error', error: toApiError(error) });
      });
    return () => controller.abort();
  }, [attempt, applyDefaultLocale]);

  const switchPersona = useCallback(async (personaId: string) => {
    const seq = ++switchSeq.current;
    setSwitching(true);
    rememberPersona(personaId);
    try {
      const me = await api.me();
      if (seq !== switchSeq.current) return;
      setState((current) =>
        current.status === 'ready' ? { ...current, personaId, me, sessionKey: `${me.id}:${seq}` } : current,
      );
    } catch (error) {
      if (seq === switchSeq.current) setState({ status: 'error', error: toApiError(error) });
    } finally {
      if (seq === switchSeq.current) setSwitching(false);
    }
  }, []);

  const retry = useCallback(() => setAttempt((n) => n + 1), []);

  const value = useMemo(() => ({ state, switching, switchPersona, retry }), [state, switching, switchPersona, retry]);
  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): SessionContextValue {
  const context = useContext(SessionContext);
  if (!context) throw new Error('useSession must be used inside <SessionProvider>.');
  return context;
}

/** For components rendered only once the session is ready (routed pages). */
export function useReadySession(): ReadySession {
  const { state } = useSession();
  if (state.status !== 'ready') throw new Error('Session is not ready.');
  return state;
}

export function hasRole(me: Me, role: string): boolean {
  return me.roles.includes(role);
}

export function isAdmin(me: Me): boolean {
  return hasRole(me, 'Admin');
}

/** Reviewers, approvers, and admins work a department queue. */
export function isStaff(me: Me): boolean {
  return hasRole(me, 'Reviewer') || hasRole(me, 'Approver') || isAdmin(me);
}

export function canAccessDepartment(me: Me, departmentId: string): boolean {
  return isAdmin(me) || me.departments.includes(departmentId);
}
