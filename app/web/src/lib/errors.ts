import type { ApiError } from '../api/client';
import type { I18n } from '../i18n/I18nProvider';
import { en, type MessageKey } from '../i18n/messages';

export interface ErrorDescription {
  /** Translated, user-friendly message for known error codes. */
  message: string;
  /** The server's `detail`, when it adds information beyond the friendly message. */
  detail: string | null;
}

export function describeError(t: I18n['t'], error: ApiError): ErrorDescription {
  if (error.isNetworkError) {
    return { message: t('error.network'), detail: null };
  }

  let key: MessageKey = 'error.generic';
  const codeKey = error.code ? `error.${error.code}` : null;
  if (codeKey && codeKey in en) {
    key = codeKey as MessageKey;
  } else if (error.status === 401) {
    key = 'error.unauthorized';
  }

  const message = t(key);
  const detail = error.detail && error.detail.trim() !== message ? error.detail.trim() : null;
  return { message, detail };
}
