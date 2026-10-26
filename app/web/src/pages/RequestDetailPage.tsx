import { useCallback, useEffect, useState } from 'react';
import { Link, useLocation, useNavigate, useParams } from 'react-router-dom';
import { api, isAbortError, toApiError, type ApiError } from '../api/client';
import type { AuditEvent, RequestDetail } from '../api/types';
import { PriorityBadge, StatusBadge } from '../components/Badges';
import { DateTime } from '../components/DateTime';
import { ErrorAlert, LoadingBlock, Notice } from '../components/Feedback';
import { PageHeading } from '../components/PageHeading';
import { AttachmentsSection } from '../features/detail/AttachmentsSection';
import { CommentsSection } from '../features/detail/CommentsSection';
import { DecisionPanel } from '../features/detail/DecisionPanel';
import { HistorySection } from '../features/detail/HistorySection';
import { RoutingPanel } from '../features/detail/RoutingPanel';
import { TriagePanel } from '../features/detail/TriagePanel';
import { useI18n } from '../i18n/I18nProvider';
import { findById, useDocumentTitle } from '../lib/labels';
import { useReadySession } from '../session/SessionProvider';

interface DetailLocationState {
  queueSearch?: string;
  created?: boolean;
}

/** Remounts the page when the id changes so state from another request never leaks in. */
export function RequestDetailRoute() {
  const { id = '' } = useParams();
  return <RequestDetailPage key={id} />;
}

export function RequestDetailPage() {
  const { id = '' } = useParams();
  const location = useLocation();
  const navigate = useNavigate();
  const navState = (location.state ?? null) as DetailLocationState | null;
  const { t } = useI18n();

  const [detail, setDetail] = useState<RequestDetail | null>(null);
  const [loadError, setLoadError] = useState<ApiError | null>(null);
  const [refreshError, setRefreshError] = useState<ApiError | null>(null);
  const [history, setHistory] = useState<AuditEvent[] | null>(null);
  const [historyError, setHistoryError] = useState<ApiError | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [showCreated, setShowCreated] = useState(Boolean(navState?.created));

  useDocumentTitle(detail ? `${detail.id} · ${detail.title}` : id);

  // Show the "submitted" confirmation once; a reload of this entry should not repeat it.
  useEffect(() => {
    if (navState?.created) {
      navigate(location.pathname + location.search, { replace: true, state: { ...navState, created: false } });
    }
    // Runs once on mount.
  }, []);

  const loadHistory = useCallback(
    async (signal?: AbortSignal) => {
      try {
        const events = await api.history(id, signal);
        setHistory(events);
        setHistoryError(null);
      } catch (error) {
        if (!isAbortError(error)) setHistoryError(toApiError(error));
      }
    },
    [id],
  );

  useEffect(() => {
    const controller = new AbortController();
    setLoadError(null);
    api
      .getRequest(id, controller.signal)
      .then(setDetail)
      .catch((error: unknown) => {
        if (!isAbortError(error)) setLoadError(toApiError(error));
      });
    void loadHistory(controller.signal);
    return () => controller.abort();
  }, [id, attempt, loadHistory]);

  /** Re-reads the request after a change (decision, comment, routing...) without unmounting the page. */
  const refresh = useCallback(async () => {
    try {
      setDetail(await api.getRequest(id));
      setRefreshError(null);
    } catch (error) {
      setRefreshError(toApiError(error));
    }
    await loadHistory();
  }, [id, loadHistory]);

  const backTo = `/${navState?.queueSearch ?? ''}`;

  if (!detail) {
    return (
      <div className="page page-detail">
        <Link to={backTo} className="back-link">
          <span aria-hidden="true">←</span> {t('detail.back')}
        </Link>
        {loadError ? (
          <div className="page-state">
            <h1 className="page-title">{id}</h1>
            <ErrorAlert
              title={t('detail.error')}
              error={loadError}
              onRetry={loadError.isNetworkError || loadError.status >= 500 ? () => setAttempt((n) => n + 1) : undefined}
            />
          </div>
        ) : (
          <div className="page-state" aria-busy="true">
            <LoadingBlock label={t('detail.loading')} />
          </div>
        )}
      </div>
    );
  }

  return (
    <div className="page page-detail">
      <Link to={backTo} className="back-link">
        <span aria-hidden="true">←</span> {t('detail.back')}
      </Link>

      {showCreated ? (
        <Notice tone="success" onDismiss={() => setShowCreated(false)}>
          <p>{t('new.created', { id: detail.id })}</p>
        </Notice>
      ) : null}
      {refreshError ? <ErrorAlert error={refreshError} onRetry={() => void refresh()} /> : null}

      <RequestHeader detail={detail} />

      <div className="detail-layout">
        <section className="card area-description" aria-labelledby="description-heading">
          <h2 id="description-heading" className="section-title">
            {t('detail.description')}
          </h2>
          <p className="prewrap description-text">{detail.description}</p>
        </section>

        <div className="detail-side area-side">
          <TriagePanel detail={detail} onChanged={refresh} />
          {detail.permissions.canRoute ? <RoutingPanel detail={detail} onChanged={refresh} /> : null}
          <DecisionPanel detail={detail} onChanged={refresh} />
        </div>

        <CommentsSection detail={detail} onChanged={refresh} className="area-comments" />
        <AttachmentsSection detail={detail} onChanged={refresh} className="area-attachments" />
        <HistorySection history={history} error={historyError} onRetry={() => void loadHistory()} className="area-history" />
      </div>
    </div>
  );
}

function RequestHeader({ detail }: { detail: RequestDetail }) {
  const { t, localName } = useI18n();
  const { departments, categories } = useReadySession();
  return (
    <section className="card request-header" aria-labelledby="request-title">
      <div className="request-header-top">
        <span className="request-id mono">{detail.id}</span>
        <StatusBadge status={detail.status} label={t('detail.status')} />
        <PriorityBadge priority={detail.priority} label={t('detail.priority')} />
      </div>
      <PageHeading id="request-title" className="request-title">
        {detail.title}
      </PageHeading>
      <dl className="meta-grid">
        <div>
          <dt>{t('detail.department')}</dt>
          <dd>{localName(findById(departments, detail.departmentId), detail.departmentId)}</dd>
        </div>
        <div>
          <dt>{t('detail.category')}</dt>
          <dd>{localName(findById(categories, detail.category), detail.category)}</dd>
        </div>
        <div>
          <dt>{t('detail.requester')}</dt>
          <dd>{detail.requester.displayName}</dd>
        </div>
        <div>
          <dt>{t('detail.created')}</dt>
          <dd>
            <DateTime iso={detail.createdAt} />
          </dd>
        </div>
        <div>
          <dt>{t('detail.updated')}</dt>
          <dd>
            <DateTime iso={detail.updatedAt} />
          </dd>
        </div>
      </dl>
    </section>
  );
}
