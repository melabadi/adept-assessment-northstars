import { request, type FullConfig } from '@playwright/test';

/**
 * Waits for the API, checks it runs in Development auth mode, and reseeds the demo database
 * (POST /api/admin/reset as the admin persona) so the suite is re-runnable on the same database.
 */
export default async function globalSetup(config: FullConfig) {
  const baseURL = config.projects[0]?.use.baseURL ?? process.env.BASE_URL ?? 'http://localhost:5080';
  const api = await request.newContext({ baseURL });
  try {
    const deadline = Date.now() + 90_000;
    for (;;) {
      const ready = await api.get('/health/ready').catch(() => null);
      if (ready?.ok()) break;
      if (Date.now() > deadline) {
        throw new Error(`RequestHub API at ${baseURL} is not ready (GET /health/ready). Start it before running e2e tests.`);
      }
      await new Promise((resolve) => setTimeout(resolve, 1000));
    }

    const meta = await (await api.get('/api/meta')).json();
    if (meta.authMode !== 'Development') {
      throw new Error(`The e2e suite needs Auth:Mode=Development (persona switcher); ${baseURL} reports ${meta.authMode}.`);
    }

    const reset = await api.post('/api/admin/reset', { headers: { 'X-RequestHub-User': 'u-dan' } });
    if (!reset.ok()) {
      throw new Error(`Demo reset failed (${reset.status()}): ${await reset.text()}. Demo:AllowReset must be true.`);
    }
  } finally {
    await api.dispose();
  }
}
