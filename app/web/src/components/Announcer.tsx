import { createContext, useCallback, useContext, useMemo, useRef, useState, type ReactNode } from 'react';

type Politeness = 'polite' | 'assertive';
type Announce = (message: string, politeness?: Politeness) => void;

const AnnouncerContext = createContext<Announce>(() => {});

/**
 * App-wide live regions. Status messages (saved, loaded, switched) go to the polite region;
 * the assertive region is for errors that have no visible inline alert.
 */
export function AnnouncerProvider({ children }: { children: ReactNode }) {
  const [messages, setMessages] = useState<Record<Politeness, string>>({ polite: '', assertive: '' });
  const timers = useRef<Partial<Record<Politeness, number>>>({});

  const announce = useCallback<Announce>((message, politeness = 'polite') => {
    // Clear first so repeating the same message is announced again.
    setMessages((current) => ({ ...current, [politeness]: '' }));
    window.clearTimeout(timers.current[politeness]);
    timers.current[politeness] = window.setTimeout(() => {
      setMessages((current) => ({ ...current, [politeness]: message }));
    }, 60);
  }, []);

  const value = useMemo(() => announce, [announce]);

  return (
    <AnnouncerContext.Provider value={value}>
      {children}
      <div className="sr-only" role="status" aria-live="polite" aria-atomic="true" data-testid="live-polite">
        {messages.polite}
      </div>
      <div className="sr-only" aria-live="assertive" aria-atomic="true" data-testid="live-assertive">
        {messages.assertive}
      </div>
    </AnnouncerContext.Provider>
  );
}

export function useAnnounce(): Announce {
  return useContext(AnnouncerContext);
}
