import type { ReactNode, Ref } from 'react';
import { getAuthMode, type ApiError } from '../api/client';
import { useI18n } from '../i18n/I18nProvider';
import { SIGN_IN_URL } from '../lib/auth';
import { describeError } from '../lib/errors';
import { Icon, type IconName } from './Icon';

export function Spinner() {
  return <span className="spinner" aria-hidden="true" />;
}

/** Inline loading message. Pair with aria-busy on the region being loaded. */
export function LoadingBlock({ label, compact = false }: { label: string; compact?: boolean }) {
  return (
    <div className={compact ? 'loading-block loading-block--compact' : 'loading-block'}>
      <Spinner />
      <span>{label}</span>
    </div>
  );
}

interface ErrorAlertProps {
  error: ApiError;
  /** Context, e.g. "We couldn't load the requests." */
  title?: string;
  onRetry?: () => void;
  ref?: Ref<HTMLDivElement>;
}

/**
 * Visible error with role="alert" (announced assertively). Shows a translated message for known
 * error codes plus the server's problem `detail`.
 */
export function ErrorAlert({ error, title, onRetry, ref }: ErrorAlertProps) {
  const { t } = useI18n();
  const { message, detail } = describeError(t, error);
  return (
    <div className="alert alert--error" role="alert" tabIndex={-1} ref={ref}>
      <Icon name="alert" className="alert-icon" />
      <div className="alert-body">
        {title ? <p className="alert-title">{title}</p> : null}
        <p className={title ? undefined : 'alert-title'}>{message}</p>
        {detail ? <p className="alert-detail">{t('common.errorDetail', { detail })}</p> : null}
        {error.status === 401 && getAuthMode() === 'EasyAuth' ? (
          <a className="button button--secondary button--small alert-action" href={SIGN_IN_URL}>
            {t('header.signIn')}
          </a>
        ) : null}
        {onRetry ? (
          <button type="button" className="button button--secondary button--small alert-action" onClick={onRetry}>
            <Icon name="refresh" size={16} />
            {t('common.retry')}
          </button>
        ) : null}
      </div>
    </div>
  );
}

type Tone = 'info' | 'success' | 'warning';
const toneIcon: Record<Tone, IconName> = { info: 'info', success: 'check', warning: 'alert' };

/** Static callout (no live role). Announce changes separately with useAnnounce when needed. */
export function Notice({
  tone,
  title,
  children,
  onDismiss,
  icon,
}: {
  tone: Tone;
  title?: string;
  children?: ReactNode;
  onDismiss?: () => void;
  icon?: IconName;
}) {
  const { t } = useI18n();
  return (
    <div className={`alert alert--${tone}`}>
      <Icon name={icon ?? toneIcon[tone]} className="alert-icon" />
      <div className="alert-body">
        {title ? <p className="alert-title">{title}</p> : null}
        {children}
      </div>
      {onDismiss ? (
        <button type="button" className="icon-button alert-dismiss" onClick={onDismiss}>
          <Icon name="x" size={16} />
          <span className="sr-only">{t('common.dismiss')}</span>
        </button>
      ) : null}
    </div>
  );
}
