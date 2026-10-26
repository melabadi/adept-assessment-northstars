# RequestHub web UI

React 19 + TypeScript single-page app for the RequestHub API (contract `requesthub.v1`), built with Vite.
`npm run build` writes the app to `../src/RequestHub.Api/wwwroot`, which the API serves (with an
`index.html` fallback for client-side routes). No UI or CSS framework: styles live in
`src/styles/index.css` (CSS variables, 8px spacing scale, one accent color).

## Prerequisites

- Node.js 22.12+ and npm.
- For `npm run dev` and the e2e tests, the API running on <http://localhost:5080> (PostgreSQL on `localhost:5432`).
  From the repository root (PowerShell):

  ```powershell
  $env:ASPNETCORE_ENVIRONMENT = 'Development'; $env:ASPNETCORE_URLS = 'http://localhost:5080'
  dotnet run --project app/src/RequestHub.Api --no-launch-profile
  ```

## Scripts

| Command | Purpose |
| --- | --- |
| `npm ci` | Install the exact versions in `package-lock.json`. |
| `npm run dev` | Vite dev server on <http://localhost:5173>. Proxies `/api`, `/health`, `/openapi`, and `/.auth` to <http://localhost:5080> (override with `REQUESTHUB_API_URL`). |
| `npm run build` | Type-check (`tsc -b`), then build into `../src/RequestHub.Api/wwwroot`. `postbuild` restores the tracked `.gitkeep`. |
| `npm run typecheck` | `tsc -b` for the app, tests, and tooling configs. |
| `npm test` | Vitest + Testing Library unit tests (jsdom, mocked `fetch`). |
| `npm run e2e` | Playwright tests (Chromium) in `e2e/` against `BASE_URL` (default <http://localhost:5080>). Run `npm run build` first so the API serves the current UI, and `npx playwright install chromium` once. Global setup resets the demo data with `POST /api/admin/reset` (as `u-dan`), so the suite can be re-run on the same database. |

## How it talks to the API

- `src/api/client.ts` is the only place that calls `fetch`. Every state-changing call sends
  `X-RequestHub-Client: web` (CSRF guard). Creating a request and recording a decision send an
  `Idempotency-Key` that is generated once per attempt and reused on retry.
- Errors are RFC 7807 problem details. Known `code` values map to translated messages; the server
  `detail` is shown underneath in an alert (`role="alert"`).
- **Development auth mode**: the header shows a persona switcher (default `u-ava`). The selected persona
  is sent as `X-RequestHub-User` and stored in the `rh_user` cookie so attachment download links work.
- **EasyAuth mode** (Azure Container Apps + Entra ID): the header shows the signed-in user from
  `GET /api/me` and a **Sign out** link (`/.auth/logout`). A 401 shows a **Sign in** link
  (`/.auth/login/aad?post_login_redirect_uri=/`).

## Layout

```text
src/
  api/                typed client and contract types
  i18n/               EN/FR dictionary (French is type-checked against English) and Intl formatting
  session/            meta, personas, current user, departments, categories, policies
  pages/              queue (/), new request (/new), request detail (/requests/:id)
  features/detail/    triage, routing, decision, comments, attachments, history panels
  components/         app shell, badges, alerts, form fields, icons, live regions
e2e/                  Playwright specs and global setup
```

The triage panel is advisory only and deliberately has no "apply recommendation" action.
User-entered text (descriptions, comments, rationales) is always rendered as plain text.
