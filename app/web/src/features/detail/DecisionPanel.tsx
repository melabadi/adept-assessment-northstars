import { useEffect, useRef, useState } from 'react';
import { api, newIdempotencyKey, toApiError, type ApiError } from '../../api/client';
import type { Decision, DecisionOutcome } from '../../api/types';
import { useAnnounce } from '../../components/Announcer';
import { OutcomeBadge } from '../../components/Badges';
import { DateTime } from '../../components/DateTime';
import { ErrorAlert, Notice, Spinner } from '../../components/Feedback';
import { FormField } from '../../components/FormField';
import { Icon } from '../../components/Icon';
import { useI18n } from '../../i18n/I18nProvider';
import { useFocusReturn } from '../../lib/useFocusReturn';
import type { DetailPanelProps } from './types';

const COMMENT_MAX = 2000;

interface Attempt {
  outcome: DecisionOutcome;
  comment: string;
  key: string;
}

export function DecisionPanel({ detail, onChanged }: DetailPanelProps) {
  const { t } = useI18n();
  const announce = useAnnounce();
  const { decision, permissions } = detail;
  const [comment, setComment] = useState('');
  const [commentError, setCommentError] = useState(false);
  const [pending, setPending] = useState<DecisionOutcome | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [conflictNotice, setConflictNotice] = useState<string | null>(null);
  // Guards double clicks before React re-renders the disabled buttons.
  const pendingRef = useRef(false);
  // The idempotency key belongs to one decision attempt; a retry of the same attempt reuses it.
  const attemptRef = useRef<Attempt | null>(null);
  const commentRef = useRef<HTMLTextAreaElement>(null);
  const resultRef = useRef<HTMLDivElement>(null);
  const focusResult = useRef(false);
  const returnFocusTo = useFocusReturn(pending !== null);

  useEffect(() => {
    if (decision && focusResult.current) {
      focusResult.current = false;
      resultRef.current?.focus();
    }
  }, [decision]);

  const decide = async (outcome: DecisionOutcome, button: HTMLButtonElement) => {
    if (pendingRef.current) return;
    const trimmed = comment.trim();
    if (outcome === 'Rejected' && !trimmed) {
      setCommentError(true);
      commentRef.current?.focus();
      return;
    }
    setCommentError(false);

    const previous = attemptRef.current;
    const key = previous && previous.outcome === outcome && previous.comment === trimmed ? previous.key : newIdempotencyKey();
    attemptRef.current = { outcome, comment: trimmed, key };

    pendingRef.current = true;
    returnFocusTo(button);
    setPending(outcome);
    setError(null);
    setConflictNotice(null);
    try {
      await api.decide(detail.id, outcome, trimmed || null, key);
      attemptRef.current = null;
      focusResult.current = true;
      await onChanged();
      announce(t(outcome === 'Approved' ? 'decision.approved' : 'decision.rejected'));
    } catch (err) {
      const apiError = toApiError(err);
      if (apiError.code === 'decision.already_decided') {
        // Someone else decided first: show their decision instead of an error.
        const existing = apiError.body?.decision as Decision | undefined;
        const message = t('decision.alreadyDecided', { name: existing?.decidedBy.displayName ?? '—' });
        setConflictNotice(message);
        announce(message);
        focusResult.current = true;
        await onChanged();
      } else {
        setError(apiError);
      }
    } finally {
      pendingRef.current = false;
      setPending(null);
    }
  };

  let body;
  if (decision) {
    body = (
      <>
        {conflictNotice ? (
          <Notice tone="info">
            <p>{conflictNotice}</p>
          </Notice>
        ) : null}
        <div ref={resultRef} tabIndex={-1} className={`decision-result decision-result--${decision.outcome.toLowerCase()}`}>
          <OutcomeBadge outcome={decision.outcome} />
          <p className="decision-by">{t('decision.decidedBy', { name: decision.decidedBy.displayName })}</p>
          <p className="decision-date">
            <DateTime iso={decision.decidedAt} />
          </p>
          {decision.comment ? <blockquote className="decision-comment prewrap">{decision.comment}</blockquote> : null}
        </div>
      </>
    );
  } else if (permissions.canDecide) {
    body = (
      <div className="stack">
        <FormField
          id="decision-comment"
          label={t('decision.comment')}
          hint={t('decision.commentHint')}
          error={commentError ? t('decision.commentRequired') : null}
          count={{ value: comment.length, max: COMMENT_MAX }}
        >
          {(describedBy, invalid) => (
            <textarea
              id="decision-comment"
              ref={commentRef}
              className="textarea"
              rows={3}
              maxLength={COMMENT_MAX}
              value={comment}
              aria-invalid={invalid}
              aria-describedby={describedBy}
              onChange={(e) => {
                setComment(e.target.value);
                if (e.target.value.trim()) setCommentError(false);
              }}
            />
          )}
        </FormField>
        {error ? <ErrorAlert title={t('decision.failed')} error={error} /> : null}
        <div className="button-row">
          <button
            type="button"
            className="button button--approve"
            disabled={pending !== null}
            onClick={(e) => void decide('Approved', e.currentTarget)}
          >
            {pending === 'Approved' ? <Spinner /> : <Icon name="check" />}
            {pending === 'Approved' ? t('decision.approving') : t('decision.approve')}
          </button>
          <button
            type="button"
            className="button button--reject"
            disabled={pending !== null}
            onClick={(e) => void decide('Rejected', e.currentTarget)}
          >
            {pending === 'Rejected' ? <Spinner /> : <Icon name="x" />}
            {pending === 'Rejected' ? t('decision.rejecting') : t('decision.reject')}
          </button>
        </div>
      </div>
    );
  } else {
    const reason = permissions.decideBlockedReason ?? 'not_approver';
    body = (
      <div className="blocked-reason">
        <Icon name="lock" />
        <div>
          <p className="strong">{t('decision.awaiting')}</p>
          <p data-testid="decide-blocked-reason">{t(`decision.blocked.${reason}`)}</p>
        </div>
      </div>
    );
  }

  return (
    <section className="card panel panel--decision" aria-labelledby="decision-heading">
      <h2 id="decision-heading" className="section-title">
        <Icon name="scale" />
        {t('decision.title')}
      </h2>
      {body}
    </section>
  );
}
