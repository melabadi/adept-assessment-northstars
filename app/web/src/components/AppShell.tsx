import { useEffect, useState, type ReactNode } from 'react';
import { Link, useLocation } from 'react-router-dom';
import type { Meta } from '../api/types';
import { useI18n, type Locale } from '../i18n/I18nProvider';
import { SIGN_IN_URL, SIGN_OUT_URL } from '../lib/auth';
import { displayVersion, industryLabel, roleLabel, shortSha } from '../lib/labels';
import { hasRole, useSession, type ReadySession } from '../session/SessionProvider';
import { useAnnounce } from './Announcer';
import { Icon, LogoMark } from './Icon';

export function AppShell({ children }: { children: ReactNode }) {
  const { t } = useI18n();
  const { state } = useSession();
  const meta = state.status === 'ready' || state.status === 'signed-out' ? state.meta : null;

  return (
    <div className="app">
      <a className="skip-link" href="#main-content">
        {t('app.skipToContent')}
      </a>
      <Header />
      <main id="main-content" className="app-main" tabIndex={-1}>
        <div className="container">{children}</div>
      </main>
      <Footer meta={meta} />
    </div>
  );
}

function Header() {
  const { t } = useI18n();
  const { state } = useSession();
  const meta = state.status === 'ready' || state.status === 'signed-out' ? state.meta : null;

  return (
    <header className="app-header">
      <div className="container header-bar">
        <Link to="/" className="brand">
          <LogoMark />
          <span className="brand-name">RequestHub</span>
        </Link>
        <div className="header-controls">
          {state.status === 'ready' && state.authMode === 'Development' ? <PersonaSwitcher session={state} /> : null}
          {state.status === 'ready' && state.authMode === 'EasyAuth' ? <SignedInUser session={state} /> : null}
          {state.status === 'signed-out' ? (
            <a className="button button--secondary" href={SIGN_IN_URL}>
              {t('header.signIn')}
            </a>
          ) : null}
          <LanguageToggle />
        </div>
      </div>
      {/* The second row is always rendered so the page doesn't shift when the session finishes loading. */}
      <div className="header-row">
        <div className="container header-row-inner">
          {state.status === 'ready' ? <MainNav session={state} /> : <span />}
          {meta ? <MetaChips meta={meta} /> : null}
        </div>
      </div>
    </header>
  );
}

function MetaChips({ meta }: { meta: Meta }) {
  const { t } = useI18n();
  const sha = shortSha(meta.buildSha);
  return (
    <div className="header-chips">
      <span className="chip chip--industry">
        <Icon name="tag" size={14} />
        <span className="sr-only">{t('header.industry')}: </span>
        {industryLabel(t, meta.industry)}
      </span>
      <span className="chip chip--env">
        <span className="env-dot" aria-hidden="true" />
        <span className="sr-only">{t('header.environment', { environment: meta.environment, sha })}</span>
        <span aria-hidden="true">
          {meta.environment} · <span className="mono">{sha}</span>
        </span>
      </span>
    </div>
  );
}

function MainNav({ session }: { session: ReadySession }) {
  const { t } = useI18n();
  const { pathname } = useLocation();
  const onQueue = pathname === '/';
  const inRequests = onQueue || pathname.startsWith('/requests/');
  const onNew = pathname === '/new';

  return (
    <nav className="main-nav" aria-label={t('nav.label')}>
      <ul className="main-nav-list">
        <li>
          <Link to="/" className={inRequests ? 'main-nav-link is-active' : 'main-nav-link'} aria-current={onQueue ? 'page' : undefined}>
            {t('nav.requests')}
          </Link>
        </li>
        {hasRole(session.me, 'Requester') ? (
          <li>
            <Link to="/new" className={onNew ? 'main-nav-link is-active' : 'main-nav-link'} aria-current={onNew ? 'page' : undefined}>
              {t('nav.newRequest')}
            </Link>
          </li>
        ) : null}
      </ul>
    </nav>
  );
}

function PersonaSwitcher({ session }: { session: ReadySession }) {
  const { t } = useI18n();
  const { switchPersona, switching } = useSession();
  const announce = useAnnounce();
  const [selected, setSelected] = useState(session.personaId ?? '');

  useEffect(() => {
    setSelected(session.personaId ?? '');
  }, [session.personaId]);

  const onChange = async (personaId: string) => {
    setSelected(personaId);
    await switchPersona(personaId);
    const persona = session.personas.find((p) => p.id === personaId);
    announce(t('header.personaSwitched', { name: persona?.displayName ?? personaId }));
  };

  return (
    <div className="persona-switcher">
      <label htmlFor="persona-select" className="control-label">
        <Icon name="user" size={16} />
        {t('header.persona')}
      </label>
      <div className="select-wrap">
        <select
          id="persona-select"
          className="select"
          value={selected}
          aria-busy={switching || undefined}
          onChange={(event) => void onChange(event.target.value)}
        >
          {session.personas.map((persona) => (
            <option key={persona.id} value={persona.id}>
              {persona.displayName} — {persona.roles.map((role) => roleLabel(t, role)).join(', ')}
            </option>
          ))}
        </select>
      </div>
    </div>
  );
}

function SignedInUser({ session }: { session: ReadySession }) {
  const { t } = useI18n();
  const { me } = session;
  return (
    <div className="signed-in">
      <Icon name="user" size={18} />
      <div className="signed-in-text">
        <span className="signed-in-label">{t('header.signedInAs')}</span>
        <span className="signed-in-name">{me.displayName}</span>
        {me.roles.length > 0 ? <span className="signed-in-roles">{me.roles.map((role) => roleLabel(t, role)).join(', ')}</span> : null}
      </div>
      <a className="button button--ghost button--small" href={SIGN_OUT_URL}>
        <Icon name="logout" size={16} />
        {t('header.signOut')}
      </a>
    </div>
  );
}

const languages: { locale: Locale; label: string }[] = [
  { locale: 'en', label: 'English' },
  { locale: 'fr', label: 'Français' },
];

function LanguageToggle() {
  const { t, locale, setLocale } = useI18n();
  return (
    <div className="lang-toggle" role="group" aria-label={t('header.language')}>
      {languages.map((language) => (
        <button
          key={language.locale}
          type="button"
          lang={language.locale}
          className="lang-option"
          aria-pressed={locale === language.locale}
          onClick={() => setLocale(language.locale)}
        >
          {language.label}
        </button>
      ))}
    </div>
  );
}

function Footer({ meta }: { meta: Meta | null }) {
  const { t } = useI18n();
  return (
    <footer className="app-footer">
      <div className="container footer-inner">
        <p className="footer-note">{t('footer.synthetic')}</p>
        {meta ? (
          <div className="footer-meta-wrap">
            <h2 className="sr-only">{t('footer.details')}</h2>
            <dl className="footer-meta">
              <div>
                <dt>{t('footer.version')}</dt>
                <dd>{displayVersion(meta.appVersion)}</dd>
              </div>
              <div>
                <dt>{t('footer.contract')}</dt>
                <dd className="mono">{meta.contractVersion}</dd>
              </div>
              <div>
                <dt>{t('footer.triage')}</dt>
                <dd className="mono">{meta.triageProvider}</dd>
              </div>
              <div>
                <dt>{t('footer.build')}</dt>
                <dd className="mono" title={meta.buildSha}>
                  {shortSha(meta.buildSha)}
                </dd>
              </div>
            </dl>
          </div>
        ) : null}
      </div>
    </footer>
  );
}
