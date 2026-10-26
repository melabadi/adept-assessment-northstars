import { useRef, useState, type FormEvent } from 'react';
import { api, toApiError, type ApiError } from '../../api/client';
import { useAnnounce } from '../../components/Announcer';
import { ErrorAlert, Spinner } from '../../components/Feedback';
import { FormField } from '../../components/FormField';
import { Icon } from '../../components/Icon';
import { useI18n } from '../../i18n/I18nProvider';
import { findById } from '../../lib/labels';
import { useFocusReturn } from '../../lib/useFocusReturn';
import { canAccessDepartment, useReadySession } from '../../session/SessionProvider';
import type { DetailPanelProps } from './types';

const REASON_MAX = 500;

/** Manual reroute by a reviewer (shown only when permissions.canRoute). The API audits every change. */
export function RoutingPanel({ detail, onChanged }: DetailPanelProps) {
  const { t, localName } = useI18n();
  const { me, departments } = useReadySession();
  const announce = useAnnounce();
  const [target, setTarget] = useState('');
  const [reason, setReason] = useState('');
  const [targetError, setTargetError] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const pendingRef = useRef(false);
  const selectRef = useRef<HTMLSelectElement>(null);
  const returnFocusTo = useFocusReturn(pending);

  const current = localName(findById(departments, detail.departmentId), detail.departmentId);
  const targets = departments.filter((d) => d.id !== detail.departmentId && canAccessDepartment(me, d.id));

  const onSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (pendingRef.current) return;
    if (!target) {
      setTargetError(true);
      selectRef.current?.focus();
      return;
    }
    const destination = localName(findById(departments, target), target);
    pendingRef.current = true;
    returnFocusTo(selectRef.current);
    setPending(true);
    setError(null);
    try {
      await api.reroute(detail.id, target, reason.trim() || null);
      setTarget('');
      setReason('');
      await onChanged();
      announce(t('routing.done', { department: destination }));
    } catch (err) {
      setError(toApiError(err));
    } finally {
      pendingRef.current = false;
      setPending(false);
    }
  };

  return (
    <section className="card panel panel--routing" aria-labelledby="routing-heading">
      <h2 id="routing-heading" className="section-title">
        <Icon name="route" />
        {t('routing.title')}
      </h2>
      <p className="panel-lead">{t('routing.current', { department: current })}</p>

      {targets.length === 0 ? (
        <p className="muted">{t('routing.noTargets')}</p>
      ) : (
        <form className="stack" noValidate onSubmit={onSubmit}>
          <FormField id="routing-department" label={t('routing.department')} error={targetError ? t('routing.chooseError') : null}>
            {(describedBy, invalid) => (
              <select
                id="routing-department"
                ref={selectRef}
                className="select"
                value={target}
                required
                aria-invalid={invalid}
                aria-describedby={describedBy}
                onChange={(e) => {
                  setTarget(e.target.value);
                  setTargetError(false);
                }}
              >
                <option value="">{t('routing.choose')}</option>
                {targets.map((d) => (
                  <option key={d.id} value={d.id}>
                    {localName(d, d.id)}
                  </option>
                ))}
              </select>
            )}
          </FormField>
          <FormField
            id="routing-reason"
            label={t('routing.reason')}
            hint={t('routing.reasonHint')}
            optional
            count={{ value: reason.length, max: REASON_MAX }}
          >
            {(describedBy) => (
              <textarea
                id="routing-reason"
                className="textarea"
                rows={2}
                maxLength={REASON_MAX}
                value={reason}
                aria-describedby={describedBy}
                onChange={(e) => setReason(e.target.value)}
              />
            )}
          </FormField>
          {error ? <ErrorAlert title={t('routing.failed')} error={error} /> : null}
          <button type="submit" className="button button--secondary button--block" disabled={pending}>
            {pending ? <Spinner /> : <Icon name="route" />}
            {pending ? t('routing.submitting') : t('routing.submit')}
          </button>
        </form>
      )}
    </section>
  );
}
