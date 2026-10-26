import { useEffect } from 'react';
import type { NamedItem } from '../api/types';
import type { I18n } from '../i18n/I18nProvider';
import { en, type MessageKey } from '../i18n/messages';

export const APP_NAME = 'RequestHub';

export function useDocumentTitle(title: string | null | undefined) {
  useEffect(() => {
    document.title = title ? `${title} · ${APP_NAME}` : APP_NAME;
  }, [title]);
}

function translatedOr(t: I18n['t'], key: string, fallback: string): string {
  return key in en ? t(key as MessageKey) : fallback;
}

export function roleLabel(t: I18n['t'], role: string): string {
  return translatedOr(t, `role.${role}`, role);
}

export function industryLabel(t: I18n['t'], industry: string): string {
  const fallback = industry.replace(/[-_]+/g, ' ').replace(/^\w/, (c) => c.toUpperCase());
  return translatedOr(t, `industry.${industry}`, fallback);
}

export function statusLabel(t: I18n['t'], status: string): string {
  return translatedOr(t, `status.${status}`, status);
}

export function priorityLabel(t: I18n['t'], priority: string): string {
  return translatedOr(t, `priority.${priority}`, priority);
}

export function findById(items: readonly NamedItem[], id: string | null | undefined): NamedItem | undefined {
  return id ? items.find((item) => item.id === id) : undefined;
}

/** First seven characters of a commit SHA; non-SHA values such as "local" are shown as-is. */
export function shortSha(sha: string): string {
  return /^[0-9a-f]{8,}$/i.test(sha) ? sha.slice(0, 7) : sha;
}

/** Strips build metadata (for example "+a619cf0…") from an informational version. */
export function displayVersion(version: string): string {
  return version.split('+')[0];
}
