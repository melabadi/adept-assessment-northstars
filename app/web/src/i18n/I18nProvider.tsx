import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import type { NamedItem } from '../api/types';
import { en, fr, type MessageKey, type Messages } from './messages';

export type Locale = 'en' | 'fr';
export type Vars = Record<string, string | number>;
/** Message keys that have `_one` / `_other` plural forms, without the suffix. */
export type PluralKey = MessageKey extends infer K ? (K extends `${infer Base}_one` ? Base : never) : never;

export const LOCALE_STORAGE_KEY = 'rh.locale';

const dictionaries: Record<Locale, Messages> = { en, fr };
const intlLocales: Record<Locale, string> = { en: 'en-CA', fr: 'fr-CA' };

export function normalizeLocale(value: string | null | undefined): Locale | null {
  const v = value?.trim().toLowerCase();
  if (!v) return null;
  if (v.startsWith('fr')) return 'fr';
  if (v.startsWith('en')) return 'en';
  return null;
}

export function readStoredLocale(): Locale | null {
  try {
    return normalizeLocale(window.localStorage.getItem(LOCALE_STORAGE_KEY));
  } catch {
    return null;
  }
}

function interpolate(template: string, vars?: Vars): string {
  if (!vars) return template;
  return template.replace(/\{(\w+)\}/g, (match, name: string) => (name in vars ? String(vars[name]) : match));
}

export interface I18n {
  locale: Locale;
  /** BCP 47 tag used for Intl formatting. */
  intlLocale: string;
  setLocale(locale: Locale): void;
  /** Uses the server default (meta.defaultLocale) unless the user already picked a language. */
  applyDefaultLocale(value: string | null | undefined): void;
  t(key: MessageKey, vars?: Vars): string;
  tCount(key: PluralKey, count: number, vars?: Vars): string;
  formatDate(iso: string): string;
  formatDateTime(iso: string): string;
  formatRelative(iso: string): string;
  formatPercent(value: number): string;
  formatFileSize(bytes: number): string;
  /** Localized department or category name, falling back to the id. */
  localName(item: NamedItem | undefined, fallback: string): string;
}

const I18nContext = createContext<I18n | null>(null);

const RELATIVE_STEPS: [Intl.RelativeTimeFormatUnit, number][] = [
  ['minute', 60],
  ['hour', 3600],
  ['day', 86_400],
  ['week', 604_800],
  ['month', 2_629_800],
  ['year', 31_557_600],
];

export function I18nProvider({ children, initialLocale }: { children: ReactNode; initialLocale?: Locale }) {
  const [state, setState] = useState<{ locale: Locale; chosen: boolean }>(() => {
    const stored = initialLocale ?? readStoredLocale();
    return { locale: stored ?? 'en', chosen: stored !== null };
  });
  const { locale } = state;

  useEffect(() => {
    document.documentElement.lang = locale;
  }, [locale]);

  const setLocale = useCallback((next: Locale) => {
    setState({ locale: next, chosen: true });
    try {
      window.localStorage.setItem(LOCALE_STORAGE_KEY, next);
    } catch {
      // Storage can be unavailable (private mode); the choice still applies to this session.
    }
  }, []);

  const applyDefaultLocale = useCallback((value: string | null | undefined) => {
    const fallback = normalizeLocale(value);
    if (!fallback) return;
    setState((current) => (current.chosen ? current : { locale: fallback, chosen: false }));
  }, []);

  const value = useMemo<I18n>(() => {
    const messages = dictionaries[locale];
    const tag = intlLocales[locale];
    const dateFormat = new Intl.DateTimeFormat(tag, { dateStyle: 'medium' });
    const dateTimeFormat = new Intl.DateTimeFormat(tag, { dateStyle: 'medium', timeStyle: 'short' });
    const relativeFormat = new Intl.RelativeTimeFormat(tag, { numeric: 'auto' });
    const percentFormat = new Intl.NumberFormat(tag, { style: 'percent', maximumFractionDigits: 0 });
    const plural = new Intl.PluralRules(tag);
    const t = (key: MessageKey, vars?: Vars) => interpolate(messages[key] ?? en[key] ?? key, vars);

    const unit = (bytes: number, name: 'byte' | 'kilobyte' | 'megabyte') =>
      new Intl.NumberFormat(tag, { style: 'unit', unit: name, unitDisplay: 'short', maximumFractionDigits: 1 }).format(bytes);

    return {
      locale,
      intlLocale: tag,
      setLocale,
      applyDefaultLocale,
      t,
      tCount: (key, count, vars) => {
        const form = plural.select(count) === 'one' ? 'one' : 'other';
        return t(`${key}_${form}` as MessageKey, { count: count.toLocaleString(tag), ...vars });
      },
      formatDate: (iso) => dateFormat.format(new Date(iso)),
      formatDateTime: (iso) => dateTimeFormat.format(new Date(iso)),
      formatRelative: (iso) => {
        const seconds = (new Date(iso).getTime() - Date.now()) / 1000;
        const abs = Math.abs(seconds);
        if (abs < 45) return t('common.justNow');
        let chosen: [Intl.RelativeTimeFormatUnit, number] = RELATIVE_STEPS[0];
        for (const step of RELATIVE_STEPS) {
          if (abs >= step[1] * 0.9) chosen = step;
        }
        return relativeFormat.format(Math.round(seconds / chosen[1]), chosen[0]);
      },
      formatPercent: (v) => percentFormat.format(v),
      formatFileSize: (bytes) => {
        if (bytes < 1024) return unit(bytes, 'byte');
        if (bytes < 1024 * 1024) return unit(bytes / 1024, 'kilobyte');
        return unit(bytes / (1024 * 1024), 'megabyte');
      },
      localName: (item, fallback) => (item ? (locale === 'fr' ? item.nameFr : item.nameEn) : fallback),
    };
  }, [locale, setLocale, applyDefaultLocale]);

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n(): I18n {
  const context = useContext(I18nContext);
  if (!context) throw new Error('useI18n must be used inside <I18nProvider>.');
  return context;
}
