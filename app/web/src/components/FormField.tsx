import type { ReactNode } from 'react';
import { useI18n } from '../i18n/I18nProvider';
import { Icon } from './Icon';

interface FormFieldProps {
  id: string;
  label: string;
  hint?: string;
  /** Translated error text; shown inline and referenced by aria-describedby. */
  error?: string | null;
  count?: { value: number; max: number };
  optional?: boolean;
  className?: string;
  /** Renders the control. Spread the ids into aria-describedby and the flag into aria-invalid. */
  children: (describedBy: string | undefined, invalid: boolean) => ReactNode;
}

export function FormField({ id, label, hint, error, count, optional, className, children }: FormFieldProps) {
  const { t, intlLocale } = useI18n();
  const describedBy =
    [hint ? `${id}-hint` : null, error ? `${id}-error` : null, count ? `${id}-count` : null].filter(Boolean).join(' ') ||
    undefined;
  const classes = ['field', error ? 'field--invalid' : null, className].filter(Boolean).join(' ');

  return (
    <div className={classes}>
      <label htmlFor={id} className="field-label">
        {label}
        {optional ? <span className="field-optional"> ({t('common.optional')})</span> : null}
      </label>
      {hint ? (
        <p id={`${id}-hint`} className="field-hint">
          {hint}
        </p>
      ) : null}
      {children(describedBy, Boolean(error))}
      {error || count ? (
        <div className="field-footer">
          {error ? (
            <p id={`${id}-error`} className="field-error">
              <Icon name="alert" size={16} />
              {error}
            </p>
          ) : (
            <span />
          )}
          {count ? (
            <p
              id={`${id}-count`}
              className={count.value > count.max * 0.9 ? 'char-count char-count--near' : 'char-count'}
            >
              {t('common.charCount', {
                count: count.value.toLocaleString(intlLocale),
                max: count.max.toLocaleString(intlLocale),
              })}
            </p>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
