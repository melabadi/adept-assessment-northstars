import { useEffect, useRef } from 'react';

/**
 * Native `disabled` drops focus from a busy control. Call the returned function with the element
 * that should get focus back when `busy` ends; focus is only restored if it was lost meanwhile.
 */
export function useFocusReturn(busy: boolean): (element: HTMLElement | null) => void {
  const target = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (busy || !target.current) return;
    const element = target.current;
    target.current = null;
    const active = document.activeElement;
    if (!active || active === document.body) element.focus();
  }, [busy]);

  return (element) => {
    target.current = element;
  };
}
