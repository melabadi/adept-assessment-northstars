import { useEffect, useRef, useState, type FormEvent } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { api, newIdempotencyKey, toApiError, type ApiError } from '../api/client';
import { PRIORITIES, type Priority } from '../api/types';
import { useAnnounce } from '../components/Announcer';
import { ErrorAlert, Notice, Spinner } from '../components/Feedback';
import { FormField } from '../components/FormField';
import { PageHeading } from '../components/PageHeading';
import { useI18n } from '../i18n/I18nProvider';
import type { MessageKey } from '../i18n/messages';
import { priorityLabel, useDocumentTitle } from '../lib/labels';
import { hasRole, useReadySession } from '../session/SessionProvider';

export const TITLE_LIMITS = { min: 5, max: 120 } as const;
export const DESCRIPTION_LIMITS = { min: 10, max: 4000 } as const;

interface Values {
  title: string;
  description: string;
  category: string;
  departmentId: string;
  priority: Priority;
}

type FieldName = 'title' | 'description' | 'category' | 'departmentId';
const FIELD_ORDER: FieldName[] = ['title', 'description', 'category', 'departmentId'];

function validate(values: Values): Partial<Record<FieldName, MessageKey>> {
  const errors: Partial<Record<FieldName, MessageKey>> = {};
  const title = values.title.trim().length;
  if (title < TITLE_LIMITS.min || title > TITLE_LIMITS.max) errors.title = 'new.error.title';
  const description = values.description.trim().length;
  if (description < DESCRIPTION_LIMITS.min || description > DESCRIPTION_LIMITS.max) errors.description = 'new.error.description';
  if (!values.category) errors.category = 'new.error.category';
  if (!values.departmentId) errors.departmentId = 'new.error.department';
  return errors;
}

export function NewRequestPage() {
  const { t, localName } = useI18n();
  const { me, categories, departments } = useReadySession();
  const announce = useAnnounce();
  const navigate = useNavigate();
  useDocumentTitle(t('new.title'));

  const [values, setValues] = useState<Values>({ title: '', description: '', category: '', departmentId: '', priority: 'Normal' });
  const [touched, setTouched] = useState<Partial<Record<FieldName, boolean>>>({});
  const [attempted, setAttempted] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [serverError, setServerError] = useState<ApiError | null>(null);
  // A ref (not state) guards against a second submit before React re-renders the disabled button.
  const submittingRef = useRef(false);
  // One key per submission: retries after a failure reuse it, so the API never creates a duplicate.
  const idempotencyKey = useRef<string | null>(null);
  const errorRef = useRef<HTMLDivElement>(null);
  const controls = useRef<Partial<Record<FieldName, HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement | null>>>({});

  useEffect(() => {
    if (serverError) errorRef.current?.focus();
  }, [serverError]);

  if (!hasRole(me, 'Requester')) {
    return (
      <div className="page page-narrow">
        <PageHeading>{t('new.title')}</PageHeading>
        <Notice tone="info" icon="lock">
          <p>{t('new.notRequester')}</p>
        </Notice>
      </div>
    );
  }

  const errors = validate(values);
  const errorFor = (name: FieldName) => (touched[name] || attempted ? errors[name] : undefined);
  const set = <K extends keyof Values>(name: K, value: Values[K]) => setValues((current) => ({ ...current, [name]: value }));
  const blur = (name: FieldName) => setTouched((current) => ({ ...current, [name]: true }));
  const register = (name: FieldName) => (element: HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement | null) => {
    controls.current[name] = element;
  };

  const onSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (submittingRef.current) return;
    setAttempted(true);
    const firstInvalid = FIELD_ORDER.find((name) => errors[name]);
    if (firstInvalid) {
      controls.current[firstInvalid]?.focus();
      return;
    }

    submittingRef.current = true;
    setSubmitting(true);
    setServerError(null);
    idempotencyKey.current ??= newIdempotencyKey();
    try {
      const created = await api.createRequest(
        {
          title: values.title.trim(),
          description: values.description.trim(),
          category: values.category,
          departmentId: values.departmentId,
          priority: values.priority,
        },
        idempotencyKey.current,
      );
      announce(t('new.created', { id: created.id }));
      navigate(`/requests/${encodeURIComponent(created.id)}`, { state: { created: true } });
    } catch (error) {
      submittingRef.current = false;
      setSubmitting(false);
      setServerError(toApiError(error));
    }
  };

  return (
    <div className="page page-narrow">
      <Link to="/" className="back-link">
        <span aria-hidden="true">←</span> {t('detail.back')}
      </Link>
      <PageHeading>{t('new.title')}</PageHeading>
      <p className="page-intro">{t('new.intro')}</p>

      <form className="card form-card" noValidate onSubmit={onSubmit} aria-describedby="new-request-required">
        <p id="new-request-required" className="form-note">
          {t('new.allRequired')}
        </p>

        {serverError ? <ErrorAlert ref={errorRef} title={t('new.failed')} error={serverError} /> : null}

        <FormField
          id="request-title"
          label={t('new.field.title')}
          hint={t('new.field.titleHint')}
          error={errorFor('title') ? t(errorFor('title')!) : null}
          count={{ value: values.title.length, max: TITLE_LIMITS.max }}
        >
          {(describedBy, invalid) => (
            <input
              id="request-title"
              ref={register('title')}
              className="input"
              type="text"
              value={values.title}
              maxLength={TITLE_LIMITS.max}
              required
              autoComplete="off"
              aria-invalid={invalid}
              aria-describedby={describedBy}
              onChange={(e) => set('title', e.target.value)}
              onBlur={() => blur('title')}
            />
          )}
        </FormField>

        <FormField
          id="request-description"
          label={t('new.field.description')}
          hint={t('new.field.descriptionHint')}
          error={errorFor('description') ? t(errorFor('description')!) : null}
          count={{ value: values.description.length, max: DESCRIPTION_LIMITS.max }}
        >
          {(describedBy, invalid) => (
            <textarea
              id="request-description"
              ref={register('description')}
              className="textarea"
              rows={6}
              value={values.description}
              maxLength={DESCRIPTION_LIMITS.max}
              required
              aria-invalid={invalid}
              aria-describedby={describedBy}
              onChange={(e) => set('description', e.target.value)}
              onBlur={() => blur('description')}
            />
          )}
        </FormField>

        <div className="form-grid">
          <FormField id="request-category" label={t('new.field.category')} error={errorFor('category') ? t(errorFor('category')!) : null}>
            {(describedBy, invalid) => (
              <select
                id="request-category"
                ref={register('category')}
                className="select"
                value={values.category}
                required
                aria-invalid={invalid}
                aria-describedby={describedBy}
                onChange={(e) => set('category', e.target.value)}
                onBlur={() => blur('category')}
              >
                <option value="">{t('new.chooseCategory')}</option>
                {categories.map((c) => (
                  <option key={c.id} value={c.id}>
                    {localName(c, c.id)}
                  </option>
                ))}
              </select>
            )}
          </FormField>

          <FormField id="request-department" label={t('new.field.department')} error={errorFor('departmentId') ? t(errorFor('departmentId')!) : null}>
            {(describedBy, invalid) => (
              <select
                id="request-department"
                ref={register('departmentId')}
                className="select"
                value={values.departmentId}
                required
                aria-invalid={invalid}
                aria-describedby={describedBy}
                onChange={(e) => set('departmentId', e.target.value)}
                onBlur={() => blur('departmentId')}
              >
                <option value="">{t('new.chooseDepartment')}</option>
                {departments.map((d) => (
                  <option key={d.id} value={d.id}>
                    {localName(d, d.id)}
                  </option>
                ))}
              </select>
            )}
          </FormField>

          <FormField id="request-priority" label={t('new.field.priority')}>
            {(describedBy) => (
              <select
                id="request-priority"
                className="select"
                value={values.priority}
                required
                aria-describedby={describedBy}
                onChange={(e) => set('priority', e.target.value as Priority)}
              >
                {PRIORITIES.map((p) => (
                  <option key={p} value={p}>
                    {priorityLabel(t, p)}
                  </option>
                ))}
              </select>
            )}
          </FormField>
        </div>

        {attempted && Object.keys(errors).length > 0 ? (
          <p className="form-error-summary" role="alert">
            {t('new.errors')}
          </p>
        ) : null}

        <div className="form-actions">
          <button type="submit" className="button button--primary" disabled={submitting}>
            {submitting ? <Spinner /> : null}
            {submitting ? t('new.submitting') : t('new.submit')}
          </button>
          <Link to="/" className="button button--ghost">
            {t('common.cancel')}
          </Link>
        </div>
      </form>
    </div>
  );
}
