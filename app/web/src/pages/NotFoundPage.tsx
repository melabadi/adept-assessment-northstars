import { Link } from 'react-router-dom';
import { PageHeading } from '../components/PageHeading';
import { useI18n } from '../i18n/I18nProvider';
import { useDocumentTitle } from '../lib/labels';

export function NotFoundPage() {
  const { t } = useI18n();
  useDocumentTitle(t('notFound.title'));
  return (
    <div className="page page-state">
      <PageHeading>{t('notFound.title')}</PageHeading>
      <p className="page-intro">{t('notFound.body')}</p>
      <Link className="button button--primary" to="/">
        {t('notFound.home')}
      </Link>
    </div>
  );
}
