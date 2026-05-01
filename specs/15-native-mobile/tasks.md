# ContriCool — Native Mobile Apps — Tasks

**Prerequisite gate:** Phase 7 must be merged to `main` before Phase 8a starts. Verify with `git log --oneline main` and confirm no Phase 7 PRs are open.

Tasks are grouped by phase. Each phase ends with a **green test run** and a **manual smoke** before the next phase starts. Tests are written within the phase that produces the code, per global guideline.

---

## Phase 8a — Native Foundation

Goal: Auth-correct, observable native dev build for Android and iOS that connects to dev backend. No platform polish, no store work.

### 8a.1 — Assets
- [ ] Generate `icon.png` (1024×1024, full bleed).
- [ ] Generate `splash.png` (1080×1920, centered logo, white background to match `app.json`).
- [ ] Generate `adaptive-icon-foreground.png` (108×108, logo within center 72×72 safe area, transparent background).
- [ ] Commit to `apps/client/assets/`.
- [ ] **Test:** `eas build --profile development --platform android --no-wait` does not fail asset resolution. (Local build fail surfaces the error; we don't need a remote build yet.)

### 8a.2 — EAS project bootstrap
- [ ] Run `eas init` from `apps/client/` (one-time).
- [ ] Add the resulting project ID to `apps/client/app.json` as `extra.eas.projectId` (this is non-secret; safe to commit).
- [ ] Create `apps/client/eas.json` with three profiles: `development` (internal, dev client), `preview` (internal, APK / simulator IPA), `production` (placeholder `{}` for future store builds).
- [ ] **Verify:** `eas whoami` succeeds locally.

### 8a.3 — Backend probe — does `/v1/auth/login` return refresh tokens in body for native?
- [ ] Read `apps/api/app/features/auth/router.py` and `dependencies.py` to confirm response shape across web / native callers.
- [ ] If it does — proceed.
- [ ] If it does not — open a small backend task: branch on `X-Client-Platform: native` header (or Cognito audience) and return `refresh_token` in the body when called from native. Add positive + negative tests for both branches. **This is the single permitted backend change at v1.**

### 8a.4 — Native auth driver
- [ ] Add `expo-secure-store` to `apps/client/package.json` and the `plugins` block in `app.json`.
- [ ] Create `apps/client/lib/auth-driver.native.ts` mirroring `auth-driver.web.ts` with `expo-secure-store` for refresh-token persistence.
- [ ] Verify `apps/client/lib/auth-store.ts` needs no changes (driver-agnostic by design).
- [ ] **Tests** (`apps/client/__tests__/lib/auth-driver-native.test.ts`):
  - login persists refresh token to mocked `expo-secure-store`.
  - refresh reads from store and returns new tokens.
  - missing token → `NO_REFRESH_TOKEN` thrown.
  - 401 from refresh endpoint → store cleared.
  - logout clears store even if API call fails.
  - parallel refresh calls deduped (single-flight).
- [ ] **Coverage:** `lib/**` ≥ 99%.

### 8a.5 — PII denylist module
- [ ] Create `apps/client/lib/pii-denylist.ts` with the regex from `CLAUDE.md` SECTION 4.
- [ ] Export both a regex matcher and a deep-clone-and-redact helper.
- [ ] **Tests:** every denylist key produces a redacted output for nested objects, arrays, and headers.

### 8a.6 — Sentry integration ✅
- [x] Add `@sentry/react-native ~6.5.0` to `package.json` (Expo SDK 52 compatible).
- [x] Add `"@sentry/react-native"` to `app.json` `plugins` (config plugin patches Android Gradle + iOS Podfile during EAS Build).
- [x] Create `apps/client/lib/sentry.web.ts` (no-op stub) and `apps/client/lib/sentry.native.ts` with `Sentry.init({ beforeSend: scrubEvent, sendDefaultPii: false })` reading DSN from `process.env.EXPO_PUBLIC_SENTRY_DSN`. Metro picks the right module per platform via suffix resolution; the split keeps `@sentry/react-native` out of the web bundle entirely.
- [x] Wire `initSentry()` at module scope in `apps/client/app/_layout.tsx` (before React mounts).
- [x] Configure `release` (`EXPO_PUBLIC_RELEASE`) and `dist` (`EXPO_PUBLIC_DIST`) tags via env vars injected by EAS Build at bundle time. Both default to undefined → Sentry uses its own release auto-detection.
- [ ] EAS post-build hook: source-map upload via Sentry CLI; build fails non-zero on upload failure. **Deferred to Phase 8b** — first `eas build` won't run until Android profile lands.
- [x] **Tests** (`apps/client/__tests__/lib/sentry.{web,native}.test.ts`, 24 tests):
  - `beforeSend` scrubs each PII denylist key across `extra`, `tags`, `contexts`, `request`, `breadcrumbs`, and strips `email`/`username` from `event.user`.
  - DSN absent → `initSentry()` is a no-op AND subsequent `captureError`/`captureMetric` calls short-circuit (no SDK calls when not initialized).
  - Idempotent — calling `initSentry()` twice initializes once.
  - Web stub never throws (compiles + runs in jsdom without native modules).

### 8a.7 — Telemetry split ✅
- [x] Renamed `apps/client/lib/telemetry.ts` → `telemetry.web.ts` (existing `/v1/telemetry/error` POST flow).
- [x] Created `apps/client/lib/telemetry.native.ts` that forwards to Sentry via `~/lib/sentry`. Same surface (`postTelemetry`, `reportError`, `reportMetric`, `_resetTelemetryForTests`) and same 200 ms dedup window so call sites (ErrorBoundary, web-vitals) work unchanged.
- [x] Metro suffix resolution: vitest config (`extensions: ['.web.ts', ...]`) + tsconfig `moduleSuffixes: [".web", ""]` mirror the runtime resolver. No fallback `lib/telemetry.ts` exists, so neither bundle can leak the wrong impl.
- [x] **Tests** (`apps/client/__tests__/lib/telemetry.native.test.ts`, 12 tests): Sentry module mocked at `~/lib/sentry`; covers error→`captureError` reconstruction, metric forwarding, dedup window, swallowed Sentry errors, `reportError` extraction (Error/string/non-Error).

### 8a.8 — Phase 8a verification
- [ ] `pnpm --filter @contricool/client lint && pnpm --filter @contricool/client typecheck && pnpm --filter @contricool/client test:coverage` all green at thresholds.
- [ ] `eas build --profile development --platform android` produces an APK.
- [ ] APK installs on Android emulator; login flow works against dev API; Sentry test event lands.
- [ ] Web bundle still builds (`pnpm --filter @contricool/client build:web`); bundle-size gate passes.
- [ ] PR opened, reviewed, merged.

---

## Phase 8b — Android Sideload

Goal: APK we `adb install` on a real Android device, full smoke pass against dev backend.

### 8b.1 — Android `app.json` polish
- [ ] Confirm `android.package: "com.contricool.app"`, `android.versionCode: 1` (increment per build).
- [ ] Confirm `android.adaptiveIcon` foreground + backgroundColor.
- [ ] Add `android.permissions: []` (we need none at v1; explicitly empty to avoid auto-bundled extras).

### 8b.2 — Preview profile in `eas.json`
- [ ] Set `preview.android.buildType: "apk"`, `gradleCommand: ":app:assembleRelease"`, `resourceClass: "large"`.
- [ ] Set `preview.distribution: "internal"`.
- [ ] Add `preview.env.EXPO_PUBLIC_API_BASE_URL` injection from `--env-file`.

### 8b.3 — First sideload
- [ ] `eas build --profile preview --platform android`.
- [ ] Download APK from EAS dashboard.
- [ ] `adb install -r app-release.apk` on a real device.
- [ ] Manual smoke checklist (record results in PR description):
  - signup → email verify → login → dashboard loads.
  - friends: list, detail, add by email, remove (if implemented).
  - transactions: create (single payer + multi-payer), edit, delete, restore, audit log.
  - settings: currency, sign out.
  - re-open after sign-out → login screen.
  - re-open after timeout → refresh-token flow → still signed in.
- [ ] Trigger deliberate JS error → confirm Sentry event with `dist:android` tag and source-mapped trace.
- [ ] Trigger deliberate API failure (airplane mode mid-request) → confirm Sentry event + UI shows error state.

### 8b.4 — Native Select implementation
- [ ] Add chosen Sheet library (recommend `@gorhom/bottom-sheet`) to `package.json`.
- [ ] Wrap app root in `GestureHandlerRootView` (in `app/_layout.tsx` if needed).
- [ ] Create `apps/client/components/ui/Select.native.tsx` matching the existing `Select.tsx` API (so call sites are unchanged).
- [ ] Verify Metro picks `.native.tsx` for android/ios builds.
- [ ] **Tests:** unit tests for `Select.native.tsx` covering open / select / close / dismiss-by-backdrop.

### 8b.5 — SafeArea + KeyboardAvoiding sweep
- [ ] Audit every screen under `apps/client/app/**`. Wrap in `SafeAreaView` (from `react-native-safe-area-context`) where missing.
- [ ] Wrap forms with text inputs in `KeyboardAvoidingView` (or NativeWind equivalent) with appropriate `behavior` per platform.
- [ ] Run smoke pass on emulator + real device; all CTAs visible above keyboard, no content under notch.

### 8b.6 — Negative tests (RED LINE 3)
- [ ] All negative test classes from `RED LINE 3` re-run on Android emulator: missing JWT, expired JWT, wrong-pool JWT, tampered JWT, wrong-user authz, non-creator edit, non-friend txn create, stale-edit conflict, rate-limit hit, idempotency replay, currency mismatch, self-add friend, already-friends, non-existent friend, cross-tenant data isolation, PII not in response, soft-deleted invisible, body-size limit, unsupported content-type.
- [ ] Document any gaps surfaced (carry to Phase 8d).

### 8b.7 — Phase 8b verification
- [ ] Coverage thresholds maintained.
- [ ] Web bundle unchanged in behavior; web e2e nightly still green.
- [ ] APK installable via `adb install -r`; full smoke + negative pass on real device.
- [ ] Sentry receiving events from real device.
- [ ] Runbook `specs/runbooks/sideload-android.md` written and validated by following it from scratch.
- [ ] PR opened, reviewed, merged.

---

## Phase 8c — iOS Sideload

Goal: app installed on user's iPhone via Xcode (free Apple-ID provisioning), full smoke pass.

### 8c.1 — iOS `app.json` polish
- [ ] Confirm `ios.bundleIdentifier: "com.contricool.app"`.
- [ ] `ios.supportsTablet: true` confirmed (matches current).
- [ ] `ios.buildNumber` defined (auto-increment via EAS or set manually).
- [ ] `ios.infoPlist` — none required at v1 (no permission usage strings since we use no native capabilities).

### 8c.2 — Build + sideload (pick one path; both are documented)
- [ ] **Path A:** `eas build --profile development --platform ios --local` on the Mac → drag `.app` into Xcode → Devices and Simulators → install on attached iPhone.
- [ ] **Path B:** `npx expo prebuild` → open `ios/ContriCool.xcworkspace` in Xcode → set Team to user's personal Apple ID → Run on iPhone.
- [ ] Document the chosen path's steps in `specs/runbooks/sideload-ios-personal-team.md`, including the 7-day re-install procedure.

### 8c.3 — iOS smoke pass
- [ ] Same smoke checklist as Phase 8b on the iPhone.
- [ ] Plus iOS-specific: notch / Dynamic Island layout, swipe-back gesture (no conflict with horizontal scroll regions in lists), status-bar style (light vs dark), keyboard dismiss-on-tap-outside.
- [ ] Sentry event tagged `dist:ios`.

### 8c.4 — Phase 8c verification
- [ ] Coverage thresholds maintained.
- [ ] Web bundle and Android APK unchanged in behavior.
- [ ] App installed on iPhone via documented path; full smoke + negative pass.
- [ ] Runbook `specs/runbooks/sideload-ios-personal-team.md` written and validated.
- [ ] PR opened, reviewed, merged.

---

## Phase 8d — Native Parity Fixes (rolling)

Goal: triage and burn down everything Phase 8b/8c surfaced. This phase is a parking lot for issues found during real-device smoke.

### 8d.1 — Triage
- [ ] Open issues for each P1/P2 finding from 8b and 8c.
- [ ] Tag P1 (broken on real device) for immediate fix; P2 (cosmetic) for batched PR.

### 8d.2 — Fix loop
- [ ] One PR per fix. Each touches the smallest possible surface.
- [ ] Auth/security fixes get negative tests (RED LINE 3).
- [ ] Re-smoke on both platforms after each merge.

### 8d.3 — Web regression check
- [ ] After every Phase 8d PR: full web e2e nightly run. Behavior unchanged.

### 8d.4 — Exit criteria
- [ ] Zero P1/P2 native bugs open.
- [ ] Web e2e green.
- [ ] Coverage thresholds maintained on both platforms.
- [ ] `CLAUDE.md` SECTION 5 has a "Native builds" subsection summarizing the runbooks.
- [ ] Root `README.md` updated with sideload instructions and env-var matrix.

---

## Out-of-scope follow-ups (separate specs)

These are explicitly NOT part of Phase 8. Each gets its own future spec when prioritized.

- **Phase 9 (or later):** Push notifications via SNS Mobile Push or Pinpoint.
- **Phase N:** Custom domain registration + Route 53 + ACM + CloudFront alias → enables AASA + assetlinks.json → universal links.
- **Phase N:** Play Store + App Store submission, including privacy labels, store screenshots, Fastlane / EAS Submit, service-account setup.
- **Phase N:** Federated login (Google + Apple Sign-in) — likely triggers Amplify Auth migration.
- **Phase N:** Mobile e2e via Maestro on EAS-built artifacts.
- **Phase N:** CI auto-build of native artifacts on tagged releases.
- **Phase N:** Biometric auth (Face ID / fingerprint) for refresh-token unlock.
