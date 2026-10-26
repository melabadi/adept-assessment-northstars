import { useRef, useState } from 'react';
import { api, toApiError, type ApiError } from '../../api/client';
import type { Policy } from '../../api/types';
import { useAnnounce } from '../../components/Announcer';
import { PriorityBadge } from '../../components/Badges';
import { DateTime } from '../../components/DateTime';
import { ErrorAlert, Notice, Spinner } from '../../components/Feedback';
import { Icon } from '../../components/Icon';
import { useI18n } from '../../i18n/I18nProvider';
import { findById } from '../../lib/labels';
import { useFocusReturn } from '../../lib/useFocusReturn';
import { useReadySession } from '../../session/SessionProvider';
import type { DetailPanelProps } from './types';

/**
 * Advisory triage recommendation. Deliberately has no "apply" action: routing changes stay a
 * human decision (see the Routing panel), and only approvers can approve or reject.
 */
export function TriagePanel({ detail, onChanged }: DetailPanelProps) {
  const { t, localName, formatPercent } = useI18n();
  const { departments, policies } = useReadySession();
  const announce = useAnnounce();
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const pendingRef = useRef(false);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const returnFocusTo = useFocusReturn(pending);

  const recommendation = detail.latestRecommendation;
  const policyById = new Map<string, Policy>(policies.map((p) => [p.id, p]));

  const getRecommendation = async () => {
    if (pendingRef.current) return;
    pendingRef.current = true;
    returnFocusTo(buttonRef.current);
    setPending(true);
    setError(null);
    try {
      await api.recommend(detail.id);
      await onChanged();
      announce(t('triage.ready'));
    } catch (err) {
      setError(toApiError(err));
    } finally {
      pendingRef.current = false;
      setPending(false);
    }
  };

  const stale = recommendation !== null && recommendation.departmentAtRecommendation !== detail.departmentId;
  const confidence = recommendation ? Math.min(1, Math.max(0, recommendation.confidence)) : 0;
  const confidenceLevel = confidence >= 0.7 ? 'high' : confidence >= 0.5 ? 'medium' : 'low';

  return (
    <section className="card panel panel--triage" aria-labelledby="triage-heading" aria-busy={pending}>
      <div className="panel-header">
        <h2 id="triage-heading" className="section-title">
          <Icon name="sparkle" />
          {t('triage.title')}
        </h2>
      </div>

      {recommendation ? (
        <div className="recommendation">
          <div className="recommendation-source">
            {recommendation.isSample ? (
              <span className="chip chip--sample">
                <Icon name="flask" size={14} />
                {t('triage.sample')}
              </span>
            ) : (
              <span className="chip chip--ai">
                <Icon name="sparkle" size={14} />
                {t('triage.ai', { provider: recommendation.provider })}
              </span>
            )}
            {!recommendation.isSample && recommendation.providerTraceId ? (
              <p className="trace-id mono">{t('triage.trace', { id: recommendation.providerTraceId })}</p>
            ) : null}
          </div>

          {stale ? (
            <Notice tone="warning" icon="route">
              <p>{t('triage.stale')}</p>
            </Notice>
          ) : null}
          {recommendation.needsHumanReview ? (
            <Notice tone="warning" title={t('triage.needsReview')}>
              <p>{t('triage.needsReviewBody')}</p>
            </Notice>
          ) : null}

          <dl className="recommendation-grid">
            <div>
              <dt>{t('triage.suggestedDepartment')}</dt>
              <dd className="strong">
                {localName(findById(departments, recommendation.suggestedDepartmentId), recommendation.suggestedDepartmentId)}
              </dd>
            </div>
            <div>
              <dt>{t('triage.suggestedPriority')}</dt>
              <dd>
                <PriorityBadge priority={recommendation.suggestedPriority} />
              </dd>
            </div>
            <div className="recommendation-confidence">
              <dt>{t('triage.confidence')}</dt>
              <dd>
                <span className="strong">{formatPercent(confidence)}</span>
                <span className={`confidence-bar confidence-bar--${confidenceLevel}`} aria-hidden="true">
                  <span style={{ width: `${Math.round(confidence * 100)}%` }} />
                </span>
              </dd>
            </div>
          </dl>

          <div className="recommendation-rationale">
            <h3 className="subsection-title">{t('triage.rationale')}</h3>
            <p className="prewrap">{recommendation.rationale}</p>
          </div>

          {recommendation.policyRefs.length > 0 ? (
            <div className="recommendation-policies">
              <h3 className="subsection-title" id="triage-citations-heading">
                {t('triage.citations')}
              </h3>
              <ul className="chip-list" aria-labelledby="triage-citations-heading">
                {recommendation.policyRefs.map((ref) => {
                  const policy = policyById.get(ref.policyId);
                  return (
                    <li key={`${ref.policyId}@${ref.version}`}>
                      <span className="chip chip--policy" title={policy ? `${policy.title}: ${policy.text}` : undefined}>
                        <Icon name="tag" size={14} />
                        {ref.policyId} v{ref.version}
                      </span>
                    </li>
                  );
                })}
              </ul>
              <details className="policy-details">
                <summary>{t('triage.readPolicies')}</summary>
                <ul className="policy-list">
                  {recommendation.policyRefs.map((ref) => {
                    const policy = policyById.get(ref.policyId);
                    return (
                      <li key={`${ref.policyId}@${ref.version}`} className="policy-item">
                        <p className="policy-name">
                          <span className="mono">
                            {ref.policyId} v{ref.version}
                          </span>
                          {policy ? <span> · {policy.title}</span> : null}
                        </p>
                        <p className="policy-text">{policy ? policy.text : t('triage.policyMissing')}</p>
                        {policy && policy.version !== ref.version ? (
                          <p className="policy-version-note">{t('triage.policyCurrent', { version: policy.version })}</p>
                        ) : null}
                      </li>
                    );
                  })}
                </ul>
              </details>
            </div>
          ) : null}

          <p className="panel-meta">
            {t('triage.requestedBy', { name: recommendation.createdBy.displayName })}
            {' · '}
            <DateTime iso={recommendation.createdAt} variant="relative" />
          </p>
        </div>
      ) : (
        <div className="empty-inline">
          <p className="strong">{t('triage.none')}</p>
          {detail.permissions.canTriage ? <p className="muted">{t('triage.noneHint')}</p> : null}
        </div>
      )}

      {error ? <ErrorAlert title={t('triage.failed')} error={error} /> : null}

      {detail.permissions.canTriage ? (
        <button
          ref={buttonRef}
          type="button"
          className="button button--secondary button--block"
          onClick={() => void getRecommendation()}
          disabled={pending}
        >
          {pending ? <Spinner /> : <Icon name="sparkle" />}
          {pending ? t('triage.getting') : t('triage.get')}
        </button>
      ) : null}

      <p className="advisory-note">
        <Icon name="info" size={16} />
        <span>{t('triage.advisory')}</span>
      </p>
    </section>
  );
}
