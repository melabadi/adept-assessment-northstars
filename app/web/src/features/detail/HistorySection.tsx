import type { ApiError } from '../../api/client';
import type { AuditEvent } from '../../api/types';
import { DateTime } from '../../components/DateTime';
import { ErrorAlert, LoadingBlock } from '../../components/Feedback';
import { Icon, type IconName } from '../../components/Icon';
import { useI18n, type I18n } from '../../i18n/I18nProvider';
import { findById, statusLabel } from '../../lib/labels';
import { useReadySession } from '../../session/SessionProvider';

interface HistorySectionProps {
  history: AuditEvent[] | null;
  error: ApiError | null;
  onRetry: () => void;
  className?: string;
}

const actionIcon: Record<string, IconName> = {
  'request.created': 'send',
  'comment.added': 'message',
  'decision.recorded': 'scale',
  'routing.changed': 'route',
  'triage.recommended': 'sparkle',
  'triage.confirmed': 'route',
  'triage.failed': 'alert',
  'triage.tool_call': 'search',
  'attachment.added': 'file',
};

function text(value: unknown): string {
  return typeof value === 'string' || typeof value === 'number' ? String(value) : '';
}

export function HistorySection({ history, error, onRetry, className }: HistorySectionProps) {
  const i18n = useI18n();
  const { t } = i18n;
  const { departments } = useReadySession();
  const departmentName = (id: unknown) => i18n.localName(findById(departments, text(id)), text(id));

  return (
    <section className={`card ${className ?? ''}`} aria-labelledby="history-heading" aria-busy={history === null && !error}>
      <h2 id="history-heading" className="section-title">
        <Icon name="history" />
        {t('history.title')}
      </h2>
      {error ? <ErrorAlert title={t('history.error')} error={error} onRetry={onRetry} /> : null}
      {history === null && !error ? <LoadingBlock label={t('history.title')} compact /> : null}
      {history && history.length === 0 ? <p className="muted">{t('history.empty')}</p> : null}
      {history && history.length > 0 ? (
        <ol className="timeline">
          {history.map((event) => {
            const { title, extra } = describe(event, t, departmentName);
            const outcome = event.action === 'decision.recorded' ? text(event.details?.outcome).toLowerCase() : '';
            return (
              <li key={event.id} className={`timeline-item${outcome ? ` timeline-item--${outcome}` : ''}`}>
                <span className="timeline-marker" aria-hidden="true">
                  <Icon name={actionIcon[event.action] ?? 'info'} size={16} />
                </span>
                <div className="timeline-content">
                  <p className="timeline-title">{title}</p>
                  {extra ? <p className="timeline-extra prewrap">{extra}</p> : null}
                  <p className="timeline-meta">
                    <span>{t('history.by', { name: event.actor.displayName })}</span>
                    <span aria-hidden="true"> · </span>
                    <DateTime iso={event.occurredAt} />
                  </p>
                  {event.correlationId ? (
                    <p className="timeline-correlation mono" title={event.correlationId}>
                      {t('history.correlation', { id: event.correlationId })}
                    </p>
                  ) : null}
                </div>
              </li>
            );
          })}
        </ol>
      ) : null}
    </section>
  );
}

function describe(event: AuditEvent, t: I18n['t'], departmentName: (id: unknown) => string): { title: string; extra: string | null } {
  const details = event.details ?? {};
  switch (event.action) {
    case 'request.created':
      return { title: t('history.request.created'), extra: null };
    case 'comment.added':
      return { title: t('history.comment.added'), extra: null };
    case 'decision.recorded':
      return { title: t('history.decision.recorded', { outcome: statusLabel(t, text(details.outcome)) }), extra: null };
    case 'routing.changed': {
      const reason = text(details.reason).trim();
      return {
        title: t('history.routing.changed', { from: departmentName(details.from), to: departmentName(details.to) }),
        extra: reason ? t('history.routing.reason', { reason }) : null,
      };
    }
    case 'triage.recommended':
      return {
        title: details.suggestedDepartment
          ? t('history.triage.recommended', { department: departmentName(details.suggestedDepartment) })
          : t('history.triage.recommendedGeneric'),
        extra: null,
      };
    case 'triage.confirmed':
      return {
        title: t('history.triage.confirmed', { from: departmentName(details.from), to: departmentName(details.to) }),
        extra: null,
      };
    case 'triage.failed':
      return { title: t('history.triage.failed', { code: text(details.code) }), extra: null };
    case 'triage.tool_call':
      return { title: t('history.triage.tool_call', { tool: text(details.tool) }), extra: null };
    case 'attachment.added':
      return { title: t('history.attachment.added', { file: text(details.file) }), extra: null };
    default:
      return { title: t('history.unknown', { action: event.action }), extra: null };
  }
}
