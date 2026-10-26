import { useRef, useState, type FormEvent } from 'react';
import { api, toApiError, type ApiError } from '../../api/client';
import { useAnnounce } from '../../components/Announcer';
import { DateTime } from '../../components/DateTime';
import { ErrorAlert, Spinner } from '../../components/Feedback';
import { FormField } from '../../components/FormField';
import { Icon } from '../../components/Icon';
import { useI18n } from '../../i18n/I18nProvider';
import { useFocusReturn } from '../../lib/useFocusReturn';
import type { DetailPanelProps } from './types';

/** Mirrors the API allow-list (AttachmentPolicy) and size limit; the API re-checks content signatures. */
export const ALLOWED_EXTENSIONS = ['.pdf', '.png', '.jpg', '.jpeg', '.txt', '.csv', '.docx', '.xlsx'] as const;
export const MAX_ATTACHMENT_BYTES = 5 * 1024 * 1024;
const ALLOWED_LABEL = ALLOWED_EXTENSIONS.map((ext) => ext.slice(1).toUpperCase()).join(', ');

function extensionOf(name: string): string {
  const dot = name.lastIndexOf('.');
  return dot >= 0 ? name.slice(dot).toLowerCase() : '';
}

export function AttachmentsSection({ detail, onChanged, className }: DetailPanelProps) {
  const { t, formatFileSize } = useI18n();
  const announce = useAnnounce();
  const [file, setFile] = useState<File | null>(null);
  const [fileError, setFileError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const pendingRef = useRef(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const returnFocusTo = useFocusReturn(pending);

  const check = (candidate: File | null): string | null => {
    if (!candidate) return t('attachments.chooseFile');
    if (!(ALLOWED_EXTENSIONS as readonly string[]).includes(extensionOf(candidate.name))) {
      return t('attachments.badType', { types: ALLOWED_LABEL });
    }
    if (candidate.size === 0) return t('attachments.emptyFile');
    if (candidate.size > MAX_ATTACHMENT_BYTES) return t('attachments.tooLarge');
    return null;
  };

  const onSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (pendingRef.current) return;
    const problem = check(file);
    if (problem || !file) {
      setFileError(problem);
      inputRef.current?.focus();
      return;
    }
    pendingRef.current = true;
    returnFocusTo(inputRef.current);
    setPending(true);
    setError(null);
    try {
      const uploaded = await api.uploadAttachment(detail.id, file);
      setFile(null);
      if (inputRef.current) inputRef.current.value = '';
      await onChanged();
      announce(t('attachments.uploaded', { name: uploaded.fileName }));
    } catch (err) {
      setError(toApiError(err));
    } finally {
      pendingRef.current = false;
      setPending(false);
    }
  };

  return (
    <section className={`card ${className ?? ''}`} aria-labelledby="attachments-heading">
      <h2 id="attachments-heading" className="section-title">
        <Icon name="file" />
        {t('attachments.title')}
        <span className="count-pill">{detail.attachments.length}</span>
      </h2>

      {detail.attachments.length === 0 ? (
        <p className="muted">{t('attachments.empty')}</p>
      ) : (
        <ul className="attachment-list">
          {detail.attachments.map((attachment) => (
            <li key={attachment.id} className="attachment">
              <Icon name="file" size={22} className="attachment-icon" />
              <div className="attachment-main">
                <a className="attachment-name" href={attachment.downloadUrl} download={attachment.fileName}>
                  {attachment.fileName}
                  <Icon name="download" size={16} />
                </a>
                <p className="attachment-meta">
                  <span>{formatFileSize(attachment.sizeBytes)}</span>
                  <span aria-hidden="true"> · </span>
                  <span>{t('attachments.uploadedBy', { name: attachment.uploadedBy.displayName })}</span>
                  <span aria-hidden="true"> · </span>
                  <DateTime iso={attachment.uploadedAt} variant="relative" />
                </p>
                <p className="attachment-hash mono" title={attachment.sha256}>
                  SHA-256 {attachment.sha256.slice(0, 16)}…
                </p>
              </div>
            </li>
          ))}
        </ul>
      )}

      {detail.permissions.canUpload ? (
        <form className="upload-form stack" noValidate onSubmit={onSubmit}>
          <FormField id="attachment-file" label={t('attachments.file')} hint={t('attachments.hint', { types: ALLOWED_LABEL })} error={fileError}>
            {(describedBy, invalid) => (
              <div className="file-picker">
                {/* The native input sits invisibly over a translated button: the browser's own
                    "Choose File" label can't be localized. */}
                <input
                  id="attachment-file"
                  ref={inputRef}
                  className="file-picker-input"
                  type="file"
                  accept={ALLOWED_EXTENSIONS.join(',')}
                  aria-invalid={invalid}
                  aria-describedby={[describedBy, 'attachment-file-name'].filter(Boolean).join(' ')}
                  onChange={(e) => {
                    const selected = e.target.files?.[0] ?? null;
                    setFile(selected);
                    setFileError(selected ? check(selected) : null);
                  }}
                />
                <span className="button button--secondary file-picker-button" aria-hidden="true">
                  <Icon name="file" size={16} />
                  {t('attachments.chooseButton')}
                </span>
                <span id="attachment-file-name" className="file-picker-name">
                  {file ? `${file.name} (${formatFileSize(file.size)})` : t('attachments.noFile')}
                </span>
              </div>
            )}
          </FormField>
          {error ? <ErrorAlert title={t('attachments.failed')} error={error} /> : null}
          <div>
            <button type="submit" className="button button--secondary" disabled={pending}>
              {pending ? <Spinner /> : <Icon name="upload" />}
              {pending ? t('attachments.uploading') : t('attachments.upload')}
            </button>
          </div>
        </form>
      ) : null}
    </section>
  );
}
