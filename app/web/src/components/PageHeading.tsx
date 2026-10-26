import { useEffect, useRef, type ReactNode } from 'react';
import { useLocation } from 'react-router-dom';

let lastHandledLocationKey: string | null = null;

/**
 * The page's h1. After an in-app navigation it receives focus, so keyboard and screen reader
 * users start at the new page's title. The first page load and same-location remounts (for
 * example after switching persona) leave focus where it is.
 */
export function PageHeading({ children, id, className }: { children: ReactNode; id?: string; className?: string }) {
  const ref = useRef<HTMLHeadingElement>(null);
  const { key } = useLocation();

  useEffect(() => {
    if (lastHandledLocationKey === null) {
      lastHandledLocationKey = key;
      return;
    }
    if (key === lastHandledLocationKey) return;
    lastHandledLocationKey = key;
    ref.current?.focus();
    // Runs only on mount: query-string updates (filters, paging) must not move focus.
  }, []);

  return (
    <h1 ref={ref} id={id} tabIndex={-1} className={className ? `page-title ${className}` : 'page-title'}>
      {children}
    </h1>
  );
}
