import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { en, fr } from './messages';
import { meta, mockApi, paged, renderApp, summary } from '../test/utils';

describe('i18n', () => {
  it('renders French chrome strings when French is selected', async () => {
    window.localStorage.setItem('rh.locale', 'fr');
    mockApi({ 'GET /api/requests': () => paged([summary({ hasRecommendation: true })]) });

    renderApp('/');

    expect(await screen.findByRole('heading', { level: 1, name: 'Demandes' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Passer au contenu principal' })).toBeInTheDocument();
    expect(screen.getByRole('navigation', { name: 'Navigation principale' })).toBeInTheDocument();
    expect(within(screen.getByRole('main')).getByRole('link', { name: 'Nouvelle demande' })).toBeInTheDocument();
    expect(screen.getByRole('combobox', { name: 'Persona de démonstration' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Français' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByRole('tab', { name: 'Mes demandes' })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByRole('searchbox', { name: 'Rechercher' })).toBeInTheDocument();
    expect(screen.getByRole('combobox', { name: 'Statut' })).toBeInTheDocument();
    expect(screen.getByText('Application de démonstration. Toutes les personnes et données sont fictives.')).toBeInTheDocument();
    expect(document.documentElement.lang).toBe('fr');

    // Data labels: localized department name from the API, translated status, assistant indicator.
    const row = await screen.findByRole('row', { name: /REQ-1001/ });
    expect(within(row).getByText('Services TI')).toBeInTheDocument();
    expect(within(row).getByText('Soumise')).toBeInTheDocument();
    expect(within(row).getByText('Normale')).toBeInTheDocument();
    expect(within(row).getByText("Suggestion de l'assistant")).toBeInTheDocument();
    expect(screen.getAllByText('1 demande').length).toBeGreaterThan(0);
  });

  it('uses the server default locale until the user picks a language, then remembers the choice', async () => {
    mockApi({ 'GET /api/meta': () => ({ ...meta, defaultLocale: 'fr' }) });
    const user = userEvent.setup();

    renderApp('/');

    expect(await screen.findByRole('heading', { level: 1, name: 'Demandes' })).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'English' }));
    expect(screen.getByRole('heading', { level: 1, name: 'Requests' })).toBeInTheDocument();
    expect(window.localStorage.getItem('rh.locale')).toBe('en');
    expect(document.documentElement.lang).toBe('en');
  });

  it('has a French string with the same placeholders for every English string', () => {
    const placeholders = (text: string) => [...text.matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort();
    for (const key of Object.keys(en) as (keyof typeof en)[]) {
      expect(fr[key], key).toBeTruthy();
      expect(placeholders(fr[key]), key).toEqual(placeholders(en[key]));
    }
  });
});
