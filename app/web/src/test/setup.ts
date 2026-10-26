import '@testing-library/jest-dom/vitest';
import { cleanup } from '@testing-library/react';
import { afterEach } from 'vitest';

afterEach(() => {
  cleanup();
  window.localStorage.clear();
  document.cookie = 'rh_user=; path=/; expires=Thu, 01 Jan 1970 00:00:00 GMT';
  document.documentElement.lang = '';
});
