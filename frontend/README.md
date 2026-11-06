# React + TypeScript + Vite

## Local API requests

The frontend uses `VITE_API_BASE_URL`, defaulting to `http://localhost:8000`.
Start the backend with its own `backend/.venv` interpreter; see the
[backend instructions](../backend/README.md). Restart Vite after editing frontend
environment variables.

Video processing has a 180-second timeout covering extraction, saving, and local
vector indexing. Chat has a 90-second timeout; health checks use 15 seconds.
A stalled backend produces a visible error and releases the Process/Send button.
Reset/unmount cancellation still silently discards the cancelled request.

With `APP_ENV=development` and `TRANSCRIPT_SOURCE=auto` on the local backend, the
Process button fetches and saves uncached captions and indexes them for RAG
automatically. Chat responses use `mode: "real"` with actual source excerpts and
timestamps. Vercel and
production are cache-only; uncached URLs there return "This video has not been
prepared yet." Both backends must use the same Supabase project.

For deployment, set `VITE_API_BASE_URL` to the deployed FastAPI origin in the
frontend build environment. For localhost, use `http://localhost:8000` as in
`.env.example`. Never put backend Supabase keys in frontend variables.

Run the mocked request/timeout tests with Node.js 24 (no backend or keys needed):

```sh
npm test
npm run build
```

This template provides a minimal setup to get React working in Vite with HMR and some Oxlint rules.

Currently, two official plugins are available:

- [@vitejs/plugin-react](https://github.com/vitejs/vite-plugin-react/blob/main/packages/plugin-react) uses [Oxc](https://oxc.rs)
- [@vitejs/plugin-react-swc](https://github.com/vitejs/vite-plugin-react/blob/main/packages/plugin-react-swc) uses [SWC](https://swc.rs/)

## React Compiler

The React Compiler is not enabled on this template because of its impact on dev & build performances. To add it, see [this documentation](https://react.dev/learn/react-compiler/installation).

## Expanding the Oxlint configuration

If you are developing a production application, we recommend enabling type-aware lint rules by installing `oxlint-tsgolint` and editing `.oxlintrc.json`:

```json
{
  "$schema": "./node_modules/oxlint/configuration_schema.json",
  "plugins": ["react", "typescript", "oxc"],
  "options": {
    "typeAware": true
  },
  "rules": {
    "react/rules-of-hooks": "error",
    "react/only-export-components": ["warn", { "allowConstantExport": true }]
  }
}
```

See the [Oxlint rules documentation](https://oxc.rs/docs/guide/usage/linter/rules) for the full list of rules and categories.
