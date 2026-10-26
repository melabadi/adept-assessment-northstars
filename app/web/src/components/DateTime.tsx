import { useI18n } from '../i18n/I18nProvider';

/** Absolute date-time with the relative time alongside ("Oct 26, 2026, 8:57 a.m. · 3 hours ago"). */
export function DateTime({ iso, variant = 'both' }: { iso: string; variant?: 'both' | 'relative' | 'date' }) {
  const { formatDateTime, formatRelative, formatDate } = useI18n();
  const absolute = formatDateTime(iso);
  if (variant === 'relative') {
    return (
      <time dateTime={iso} title={absolute}>
        {formatRelative(iso)}
      </time>
    );
  }
  if (variant === 'date') {
    return (
      <time dateTime={iso} title={absolute}>
        {formatDate(iso)}
      </time>
    );
  }
  return (
    <span className="datetime">
      <time dateTime={iso}>{absolute}</time>
      <span className="datetime-sep" aria-hidden="true">
        {' · '}
      </span>
      <span className="datetime-relative"> {formatRelative(iso)}</span>
    </span>
  );
}

const avatarHues = [212, 262, 330, 24, 168, 140, 196, 290];

export function Avatar({ name }: { name: string }) {
  const initials = name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() ?? '')
    .join('');
  let hash = 0;
  for (const ch of name) hash = (hash * 31 + ch.charCodeAt(0)) >>> 0;
  const hue = avatarHues[hash % avatarHues.length];
  return (
    <span className="avatar" aria-hidden="true" style={{ backgroundColor: `hsl(${hue} 45% 34%)` }}>
      {initials || '?'}
    </span>
  );
}
