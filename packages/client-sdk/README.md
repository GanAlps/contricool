# `@contricool/client-sdk`

A typed, schema-anchored client for the ContriCool API.

## What it is

- A workspace package generated from `packages/openapi/openapi.yaml`
  (which itself is emitted from FastAPI's `apps/api`).
- A thin runtime over [`openapi-fetch`](https://openapi-ts.dev/openapi-fetch/)
  with a small auth-aware middleware: bearer-attach on non-`/auth/*`
  routes, envelope parsing → `ApiErrorException`, and the web
  401-refresh-retry-once flow.
- ~5 KB gz combined, no third-party runtime deps beyond `openapi-fetch`.

## Public API

```ts
import { createClient, ApiErrorException, type ContricoolClient } from '@contricool/client-sdk';

const client = createClient({
  baseUrl: '/v1',
  getAccessToken: () => store.getState().accessToken,
  onUnauthenticated: () => store.getState().clear(),
  onTokenRefreshed: ({ access_token, id_token }) => store.setTokens(access_token, id_token),
});

try {
  const r = await client.POST('/auth/login', { body: { email, password } });
  console.log(r.data!.user.name);
} catch (e) {
  if (e instanceof ApiErrorException) {
    console.error(e.error.code);
  }
}
```

`createClient` returns the `openapi-fetch` client typed against the
schema, plus the auth-aware middleware. Methods are `GET`, `POST`,
`PUT`, `PATCH`, `DELETE`. Path keys come from the schema and are
fully autocompleted.

The middleware **throws** `ApiErrorException` on non-2xx so screen
code can `try/catch`. Refresh tokens never reach JS — the HttpOnly
`rt` cookie set by the backend handles persistence.

## Friendly type aliases

For screen code readability, the SDK re-exports renamed shapes:

```ts
import type {
  AuthUser,
  Currency,
  SignInResponse,
  SignupResponse,
  RefreshResponse,
  // ...
} from '@contricool/client-sdk';
```

See `src/index.ts` for the full list.

## Regeneration

When the FastAPI app changes, regenerate the schema + types:

```bash
make openapi
```

Lefthook auto-runs this on commits that touch `apps/api/app/`.

CI runs `make openapi-check` to fail any drift.

## Local commands

```bash
pnpm --filter @contricool/client-sdk build         # regenerate + clean
pnpm --filter @contricool/client-sdk test          # vitest
pnpm --filter @contricool/client-sdk test:coverage # 99/95 thresholds
pnpm --filter @contricool/client-sdk lint          # biome
pnpm --filter @contricool/client-sdk typecheck     # tsc --noEmit
```

## Limitations

- Web only at MVP — the middleware uses cookies for refresh, which
  is the web pattern. Native phase will keep the same SDK but the
  driver will manage tokens via Keychain / EncryptedSharedPreferences
  and handle refresh out-of-band.
- No streaming / Server-Sent Events at MVP.
- No pagination helpers — `openapi-fetch` returns raw responses; we
  add helpers if/when the API exposes paginated endpoints.
