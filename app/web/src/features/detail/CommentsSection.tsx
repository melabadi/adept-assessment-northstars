import { useRef, useState, type FormEvent } from 'react';
import { api, toApiError, type ApiError } from '../../api/client';
import { useAnnounce } from '../../components/Announcer';
import { Avatar, DateTime } from '../../components/DateTime';
import { ErrorAlert, Spinner } from '../../components/Feedback';
import { FormField } from '../../components/FormField';
import { Icon } from '../../components/Icon';
import { useI18n } from '../../i18n/I18nProvider';
import { useFocusReturn } from '../../lib/useFocusReturn';
import type { DetailPanelProps } from './types';

const COMMENT_MAX = 2000;

export function CommentsSection({ detail, onChanged, className }: DetailPanelProps) {
  const { t } = useI18n();
  const announce = useAnnounce();
  const [body, setBody] = useState('');
  const [bodyError, setBodyError] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const pendingRef = useRef(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const returnFocusTo = useFocusReturn(pending);

  const onSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (pendingRef.current) return;
    const text = body.trim();
    if (text.length === 0 || text.length > COMMENT_MAX) {
      setBodyError(true);
      textareaRef.current?.focus();
      return;
    }
    pendingRef.current = true;
    returnFocusTo(textareaRef.current);
    setPending(true);
    setError(null);
    try {
      await api.addComment(detail.id, text);
      setBody('');
      setBodyError(false);
      await onChanged();
      announce(t('comments.posted'));
    } catch (err) {
      setError(toApiError(err));
    } finally {
      pendingRef.current = false;
      setPending(false);
    }
  };

  return (
    <section className={`card ${className ?? ''}`} aria-labelledby="comments-heading">
      <h2 id="comments-heading" className="section-title">
        <Icon name="message" />
        {t('comments.title')}
        <span className="count-pill">{detail.comments.length}</span>
      </h2>

      {detail.comments.length === 0 ? (
        <p className="muted">{t('comments.empty')}</p>
      ) : (
        <ol className="comment-list">
          {detail.comments.map((comment) => (
            <li key={comment.id} className="comment">
              <Avatar name={comment.author.displayName} />
              <div className="comment-main">
                <p className="comment-meta">
                  <span className="strong">{comment.author.displayName}</span>
                  <span className="muted">
                    <DateTime iso={comment.createdAt} variant="relative" />
                  </span>
                </p>
                <p className="comment-body prewrap">{comment.body}</p>
              </div>
            </li>
          ))}
        </ol>
      )}

      {detail.permissions.canComment ? (
        <form className="comment-form stack" noValidate onSubmit={onSubmit}>
          <FormField
            id="comment-body"
            label={t('comments.add')}
            error={bodyError ? t('comments.error') : null}
            count={{ value: body.length, max: COMMENT_MAX }}
          >
            {(describedBy, invalid) => (
              <textarea
                id="comment-body"
                ref={textareaRef}
                className="textarea"
                rows={3}
                maxLength={COMMENT_MAX}
                value={body}
                required
                aria-invalid={invalid}
                aria-describedby={describedBy}
                onChange={(e) => {
                  setBody(e.target.value);
                  if (e.target.value.trim()) setBodyError(false);
                }}
              />
            )}
          </FormField>
          {error ? <ErrorAlert title={t('comments.failed')} error={error} /> : null}
          <div>
            <button type="submit" className="button button--secondary" disabled={pending}>
              {pending ? <Spinner /> : <Icon name="message" />}
              {pending ? t('comments.posting') : t('comments.post')}
            </button>
          </div>
        </form>
      ) : null}
    </section>
  );
}
