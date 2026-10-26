import { useCallback, useEffect, useMemo, useRef, useState, type KeyboardEvent, type MouseEvent } from 'react';
import { Link, useLocation, useNavigate, useSearchParams } from 'react-router-dom';
import { api, isAbortError, toApiError, type ApiError } from '../api/client';
import { PRIORITIES, STATUSES, type PagedResult, type RequestSummary, type Scope } from '../api/types';
import { useAnnounce } from '../components/Announcer';
import { PriorityBadge, StatusBadge } from '../components/Badges';
import { DateTime } from '../components/DateTime';
import { ErrorAlert, LoadingBlock } from '../components/Feedback';
import { Icon } from '../components/Icon';
import { PageHeading } from '../components/PageHeading';
import { useI18n } from '../i18n/I18nProvider';
import { findById, priorityLabel, statusLabel, useDocumentTitle } from '../lib/labels';
import { hasRole, isAdmin, isStaff, useReadySession } from '../session/SessionProvider';

export const PAGE_SIZE = 20;
const SEARCH_DEBOUNCE_MS = 350;

function oneOf<T extends string>(value: string | null, allowed: readonly T[]): T | '' {
  return value && (allowed as readonly string[]).includes(value) ? (value as T) : '';
}

function parsePage(value: string | null): number {
  const page = Number.parseInt(value ?? '', 10);
  return Number.isFinite(page) && page > 1 ? page : 1;
}

export function QueuePage() {
  const { t, tCount, localName } = useI18n();
  const { me, departments } = useReadySession();
  const announce = useAnnounce();
  const navigate = useNavigate();
  const location = useLocation();
  const [params, setParams] = useSearchParams();
  useDocumentTitle(t('queue.title'));

  const scopes = useMemo<Scope[]>(() => {
    const list: Scope[] = ['mine'];
    if (isStaff(me)) list.push('queue');
    if (isAdmin(me)) list.push('all');
    return list;
  }, [me]);
  const defaultScope: Scope = isStaff(me) ? 'queue' : 'mine';
  const scope = oneOf(params.get('scope'), scopes) || defaultScope;
  const status = oneOf(params.get('status'), STATUSES);
  const priority = oneOf(params.get('priority'), PRIORITIES);
  const department = oneOf(params.get('department'), departments.map((d) => d.id));
  const q = params.get('q') ?? '';
  const query = q.trim();
  const page = parsePage(params.get('page'));
  const filtersActive = Boolean(status || priority || department || query);

  const update = useCallback(
    (changes: Record<string, string | null>) => {
      setParams(
        (previous) => {
          const next = new URLSearchParams(previous);
          for (const [key, value] of Object.entries(changes)) {
            if (value) next.set(key, value);
            else next.delete(key);
          }
          return next;
        },
        { replace: true },
      );
    },
    [setParams],
  );

  // Debounced search: the input updates immediately; the URL (and the fetch) follow after a pause.
  const [searchText, setSearchText] = useState(q);
  const pushedQuery = useRef(q);
  useEffect(() => {
    if (q !== pushedQuery.current) {
      pushedQuery.current = q;
      setSearchText(q);
    }
  }, [q]);
  useEffect(() => {
    if (searchText === pushedQuery.current) return;
    const timer = window.setTimeout(() => {
      pushedQuery.current = searchText;
      update({ q: searchText || null, page: null });
    }, SEARCH_DEBOUNCE_MS);
    return () => window.clearTimeout(timer);
  }, [searchText, update]);

  const [result, setResult] = useState<PagedResult<RequestSummary> | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);
  const [reloadToken, setReloadToken] = useState(0);
  const hasLoaded = useRef(false);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    api
      .listRequests({ scope, status, department, priority, q: query, page, pageSize: PAGE_SIZE }, controller.signal)
      .then((data) => {
        setResult(data);
        setLoading(false);
        if (data.totalPages > 0 && page > data.totalPages) {
          update({ page: data.totalPages > 1 ? String(data.totalPages) : null });
        }
        if (hasLoaded.current) {
          const pages = Math.max(1, data.totalPages);
          announce(`${tCount('queue.total', data.totalCount)}. ${t('queue.pageOf', { page: data.page, pages })}`);
        }
        hasLoaded.current = true;
      })
      .catch((err: unknown) => {
        if (isAbortError(err)) return;
        setError(toApiError(err));
        setLoading(false);
        hasLoaded.current = true;
      });
    return () => controller.abort();
    // t/tCount are read when the response arrives; switching language must not refetch.
  }, [scope, status, department, priority, query, page, reloadToken, update, announce]);

  const clearFilters = () => {
    pushedQuery.current = '';
    setSearchText('');
    update({ status: null, department: null, priority: null, q: null, page: null });
  };

  const selectScope = (next: Scope) => {
    if (next === scope) return;
    update({ scope: next === defaultScope ? null : next, page: null });
  };

  const goToPage = (next: number) => {
    if (!result || next < 1 || next > Math.max(1, result.totalPages) || next === page) return;
    update({ page: next > 1 ? String(next) : null });
  };

  const openRow = (event: MouseEvent<HTMLTableRowElement>, id: string) => {
    const target = event.target as HTMLElement;
    if (target.closest('a, button, input, select, textarea')) return;
    if (window.getSelection()?.toString()) return;
    navigate(`/requests/${encodeURIComponent(id)}`, { state: { queueSearch: location.search } });
  };

  const scopeLabel = t(`queue.scope.${scope}`);
  const totalPages = Math.max(1, result?.totalPages ?? 1);
  const items = result?.items ?? [];

  return (
    <div className="page page-queue">
      <div className="page-header">
        <div>
          <PageHeading>{t('queue.title')}</PageHeading>
          <p className="page-intro">{t('queue.intro')}</p>
        </div>
        {hasRole(me, 'Requester') ? (
          <Link to="/new" className="button button--primary">
            <Icon name="plus" />
            {t('nav.newRequest')}
          </Link>
        ) : null}
      </div>

      <ScopeTabs scopes={scopes} active={scope} onSelect={selectScope} />

      <div id="queue-panel" role="tabpanel" aria-labelledby={`scope-tab-${scope}`} className="card queue-card">
        <form className="filters" role="search" aria-label={t('queue.filters')} onSubmit={(event) => event.preventDefault()}>
          <div className="field field--search">
            <label className="field-label" htmlFor="queue-search">
              {t('queue.search')}
            </label>
            <div className="input-with-icon">
              <Icon name="search" />
              <input
                id="queue-search"
                className="input"
                type="search"
                value={searchText}
                placeholder={t('queue.searchHint')}
                autoComplete="off"
                onChange={(event) => setSearchText(event.target.value)}
              />
            </div>
          </div>
          <div className="field">
            <label className="field-label" htmlFor="filter-status">
              {t('queue.filter.status')}
            </label>
            <select id="filter-status" className="select" value={status} onChange={(e) => update({ status: e.target.value || null, page: null })}>
              <option value="">{t('queue.filter.anyStatus')}</option>
              {STATUSES.map((s) => (
                <option key={s} value={s}>
                  {statusLabel(t, s)}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label className="field-label" htmlFor="filter-department">
              {t('queue.filter.department')}
            </label>
            <select
              id="filter-department"
              className="select"
              value={department}
              onChange={(e) => update({ department: e.target.value || null, page: null })}
            >
              <option value="">{t('queue.filter.anyDepartment')}</option>
              {departments.map((d) => (
                <option key={d.id} value={d.id}>
                  {localName(d, d.id)}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label className="field-label" htmlFor="filter-priority">
              {t('queue.filter.priority')}
            </label>
            <select id="filter-priority" className="select" value={priority} onChange={(e) => update({ priority: e.target.value || null, page: null })}>
              <option value="">{t('queue.filter.anyPriority')}</option>
              {PRIORITIES.map((p) => (
                <option key={p} value={p}>
                  {priorityLabel(t, p)}
                </option>
              ))}
            </select>
          </div>
          {filtersActive ? (
            <button type="button" className="button button--ghost filters-clear" onClick={clearFilters}>
              <Icon name="x" size={16} />
              {t('queue.clearFilters')}
            </button>
          ) : null}
        </form>

        <div className={['results', loading && result ? 'is-refreshing' : null, !result && !error ? 'results--initial' : null].filter(Boolean).join(' ')} aria-busy={loading}>
          {loading ? <LoadingBlock label={t('queue.loading')} compact={Boolean(result)} /> : null}

          {error ? <ErrorAlert title={t('queue.error')} error={error} onRetry={() => setReloadToken((n) => n + 1)} /> : null}

          {!error && result && items.length === 0 && !loading ? (
            <div className="empty-state">
              <Icon name="inbox" size={40} />
              <p>{filtersActive ? t('queue.empty.filtered') : scope === 'mine' ? t('queue.empty.mine') : t('queue.empty.other')}</p>
              {filtersActive ? (
                <button type="button" className="button button--secondary" onClick={clearFilters}>
                  {t('queue.clearFilters')}
                </button>
              ) : scope === 'mine' && hasRole(me, 'Requester') ? (
                <Link to="/new" className="button button--secondary">
                  <Icon name="plus" />
                  {t('nav.newRequest')}
                </Link>
              ) : null}
            </div>
          ) : null}

          {!error && items.length > 0 ? (
            <div className="table-wrap">
              {/* Explicit roles keep table semantics when narrow screens restyle rows as cards. */}
              <table className="data-table queue-table" role="table">
                <caption>
                  <span className="caption-view">{scopeLabel}</span>
                  <span className="sr-only">, </span>
                  <span className="caption-count">{tCount('queue.total', result?.totalCount ?? 0)}</span>
                  <span className="sr-only">, {t('queue.pageOf', { page, pages: totalPages })}</span>
                </caption>
                <thead role="rowgroup">
                  <tr role="row">
                    <th scope="col" role="columnheader">{t('queue.col.id')}</th>
                    <th scope="col" role="columnheader">{t('queue.col.title')}</th>
                    <th scope="col" role="columnheader">{t('queue.col.department')}</th>
                    <th scope="col" role="columnheader">{t('queue.col.priority')}</th>
                    <th scope="col" role="columnheader">{t('queue.col.status')}</th>
                    <th scope="col" role="columnheader">{t('queue.col.requester')}</th>
                    <th scope="col" role="columnheader">{t('queue.col.created')}</th>
                  </tr>
                </thead>
                <tbody role="rowgroup">
                  {items.map((request) => (
                    <tr key={request.id} role="row" className="is-clickable" onClick={(event) => openRow(event, request.id)}>
                      <td role="cell" data-label={t('queue.col.id')} className="cell-id">
                        <Link to={`/requests/${encodeURIComponent(request.id)}`} state={{ queueSearch: location.search }} className="id-link">
                          {request.id}
                        </Link>
                      </td>
                      <td role="cell" data-label={t('queue.col.title')} className="cell-title">
                        <div className="cell-stack">
                          <span className="title-text">{request.title}</span>
                          {request.hasRecommendation ? (
                            <span className="chip chip--assistant">
                              <Icon name="sparkle" size={14} />
                              {t('queue.assistantSuggestion')}
                            </span>
                          ) : null}
                        </div>
                      </td>
                      <td role="cell" data-label={t('queue.col.department')}>
                        {localName(findById(departments, request.departmentId), request.departmentId)}
                      </td>
                      <td role="cell" data-label={t('queue.col.priority')}>
                        <PriorityBadge priority={request.priority} />
                      </td>
                      <td role="cell" data-label={t('queue.col.status')}>
                        <StatusBadge status={request.status} />
                      </td>
                      <td role="cell" data-label={t('queue.col.requester')}>
                        {request.requester.displayName}
                      </td>
                      <td role="cell" data-label={t('queue.col.created')} className="cell-date">
                        <div className="cell-stack">
                          <DateTime iso={request.createdAt} variant="date" />
                          <span className="cell-sub">
                            <DateTime iso={request.createdAt} variant="relative" />
                          </span>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}

          {!error && result && result.totalCount > 0 ? (
            <nav className="pagination" aria-label={t('queue.pagination')}>
              <p className="pagination-total">{tCount('queue.total', result.totalCount)}</p>
              <div className="pagination-controls">
                <button
                  type="button"
                  className="button button--secondary"
                  aria-disabled={page <= 1 || undefined}
                  onClick={() => goToPage(page - 1)}
                >
                  <Icon name="arrowLeft" size={16} />
                  {t('queue.previous')}
                </button>
                <span className="pagination-page">{t('queue.pageOf', { page, pages: totalPages })}</span>
                <button
                  type="button"
                  className="button button--secondary"
                  aria-disabled={page >= totalPages || undefined}
                  onClick={() => goToPage(page + 1)}
                >
                  {t('queue.next')}
                  <Icon name="arrowLeft" size={16} className="icon--flip" />
                </button>
              </div>
            </nav>
          ) : null}
        </div>
      </div>
    </div>
  );
}

function ScopeTabs({ scopes, active, onSelect }: { scopes: Scope[]; active: Scope; onSelect: (scope: Scope) => void }) {
  const { t } = useI18n();
  const tabs = useRef<Partial<Record<Scope, HTMLButtonElement | null>>>({});

  const onKeyDown = (event: KeyboardEvent<HTMLButtonElement>, index: number) => {
    const last = scopes.length - 1;
    const next =
      event.key === 'ArrowRight' ? (index === last ? 0 : index + 1)
      : event.key === 'ArrowLeft' ? (index === 0 ? last : index - 1)
      : event.key === 'Home' ? 0
      : event.key === 'End' ? last
      : -1;
    if (next < 0) return;
    event.preventDefault();
    const scope = scopes[next];
    tabs.current[scope]?.focus();
    onSelect(scope);
  };

  return (
    <div className="tabs" role="tablist" aria-label={t('queue.views')}>
      {scopes.map((scope, index) => (
        <button
          key={scope}
          ref={(element) => {
            tabs.current[scope] = element;
          }}
          id={`scope-tab-${scope}`}
          type="button"
          role="tab"
          className="tab"
          aria-selected={scope === active}
          aria-controls="queue-panel"
          tabIndex={scope === active ? 0 : -1}
          onClick={() => onSelect(scope)}
          onKeyDown={(event) => onKeyDown(event, index)}
        >
          {t(`queue.scope.${scope}`)}
        </button>
      ))}
    </div>
  );
}
