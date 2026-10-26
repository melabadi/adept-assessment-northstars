import type { DecisionOutcome, Priority, RequestStatus } from '../api/types';
import { useI18n } from '../i18n/I18nProvider';
import { priorityLabel, statusLabel } from '../lib/labels';
import { Icon, type IconName } from './Icon';

const statusIcon: Record<RequestStatus, IconName> = {
  Submitted: 'send',
  InReview: 'eye',
  Approved: 'check',
  Rejected: 'x',
};

const priorityIcon: Record<Priority, IconName> = {
  Low: 'arrowDown',
  Normal: 'minus',
  High: 'arrowUp',
  Urgent: 'alert',
};

/** Status pill: icon + text, so meaning never depends on color alone. */
export function StatusBadge({ status, label }: { status: RequestStatus; label?: string }) {
  const { t } = useI18n();
  return (
    <span className={`badge badge--status badge--${status.toLowerCase()}`}>
      <Icon name={statusIcon[status] ?? 'info'} size={14} />
      {label ? <span className="sr-only">{label}: </span> : null}
      {statusLabel(t, status)}
    </span>
  );
}

export function PriorityBadge({ priority, label }: { priority: Priority; label?: string }) {
  const { t } = useI18n();
  return (
    <span className={`badge badge--priority badge--priority-${priority.toLowerCase()}`}>
      <Icon name={priorityIcon[priority] ?? 'minus'} size={14} />
      {label ? <span className="sr-only">{label}: </span> : null}
      {priorityLabel(t, priority)}
    </span>
  );
}

export function OutcomeBadge({ outcome }: { outcome: DecisionOutcome }) {
  const { t } = useI18n();
  return (
    <span className={`badge badge--status badge--${outcome.toLowerCase()} badge--large`}>
      <Icon name={outcome === 'Approved' ? 'check' : 'x'} size={16} />
      {statusLabel(t, outcome)}
    </span>
  );
}
