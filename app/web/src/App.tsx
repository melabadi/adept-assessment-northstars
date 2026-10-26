import { Route, Routes } from 'react-router-dom';
import { AnnouncerProvider } from './components/Announcer';
import { AppShell } from './components/AppShell';
import { ErrorAlert, LoadingBlock } from './components/Feedback';
import { Icon } from './components/Icon';
import { I18nProvider, useI18n, type Locale } from './i18n/I18nProvider';
import { SIGN_IN_URL } from './lib/auth';
import { useDocumentTitle } from './lib/labels';
import { NewRequestPage } from './pages/NewRequestPage';
import { NotFoundPage } from './pages/NotFoundPage';
import { QueuePage } from './pages/QueuePage';
import { RequestDetailRoute } from './pages/RequestDetailPage';
import { SessionProvider, useSession } from './session/SessionProvider';

/** The whole app without a router, so tests can wrap it in a MemoryRouter. */
export function App({ initialLocale }: { initialLocale?: Locale }) {
  return (
    <I18nProvider initialLocale={initialLocale}>
      <AnnouncerProvider>
        <SessionProvider>
          <AppShell>
            <SessionGate />
          </AppShell>
        </SessionProvider>
      </AnnouncerProvider>
    </I18nProvider>
  );
}

function SessionGate() {
  const { t } = useI18n();
  const { state, retry } = useSession();

  switch (state.status) {
    case 'loading':
      return (
        <div className="page-state" aria-busy="true">
          <LoadingBlock label={t('app.loading')} />
        </div>
      );
    case 'error':
      return (
        <div className="page-state">
          <h1 className="page-title">{t('app.loadError.title')}</h1>
          <p className="page-intro">{t('app.loadError.body')}</p>
          <ErrorAlert error={state.error} onRetry={retry} />
        </div>
      );
    case 'signed-out':
      return <SignedOut />;
    default:
      return <AppRoutes key={state.sessionKey} />;
  }
}

function SignedOut() {
  const { t } = useI18n();
  useDocumentTitle(t('app.signedOut.title'));
  return (
    <div className="page-state card signed-out">
      <Icon name="lock" size={32} />
      <h1 className="page-title">{t('app.signedOut.title')}</h1>
      <p className="page-intro">{t('app.signedOut.body')}</p>
      <a className="button button--primary" href={SIGN_IN_URL}>
        {t('header.signIn')}
      </a>
    </div>
  );
}

function AppRoutes() {
  return (
    <Routes>
      <Route path="/" element={<QueuePage />} />
      <Route path="/new" element={<NewRequestPage />} />
      <Route path="/requests/:id" element={<RequestDetailRoute />} />
      <Route path="*" element={<NotFoundPage />} />
    </Routes>
  );
}
