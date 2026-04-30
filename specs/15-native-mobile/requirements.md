# ContriCool — Native Mobile Apps (Android + iOS) — Requirements

## Overview

ContriCool's web app (Phases 0–6) is shipping. Phase 7 is in flight on a parallel thread. This spec defines the native mobile rollout — Android first, iOS second — built on the existing Expo + React Native + RN-Web codebase under `apps/client`. The single client tree already powers web; native is the second and third output of that same tree, **with maximum reuse and zero backend changes** for v1.

The non-negotiable property is **identical look and feel and identical feature set across web, Android, and iOS**. A user on Android must be able to do everything a user on web can — auth, friends, transactions (create / edit / delete / restore / audit), settings — and the screens must read the same way.

## What we're building

**A1.** A user can install ContriCool on an Android device by sideloading an APK (`adb install`) and use every feature available on web today.

**A2.** A user can install ContriCool on an iPhone by building it on a Mac in Xcode (or `eas build --local`) using a free Apple-ID development profile, and use every feature available on web today.

**A3.** Authentication on both platforms uses the existing `/v1/auth/*` REST endpoints; refresh tokens persist in platform-secure storage (`expo-secure-store` → iOS Keychain / Android EncryptedSharedPreferences) and access/id tokens stay in memory, matching the security posture of the web app (`RED LINE 1`, `RED LINE 3`).

**A4.** The native apps emit crash and error reports to Sentry from the first build, with PII scrubbed per the existing denylist (`CLAUDE.md` SECTION 4).

**A5.** The web app continues to ship and pass its existing test suite, bundle-size gate, and nightly e2e — no regressions because of native work.

**A6.** Test coverage stays at the global thresholds (`lib/**` ≥ 99%, `app/**` & `components/**` ≥ 80%) for the shared codebase, with native-specific code unit-tested under the same thresholds.

## What we're NOT building in v1

**B1.** Play Store / App Store submission — sideload only. No Fastlane, no EAS Submit, no Play Console service account, no App Store Connect API setup, no privacy labels, no store screenshots.

**B2.** Push notifications. Deferred until store launch (designs in `specs/14-notifications/` already note the deferral).

**B3.** Universal links / app links / AASA / assetlinks.json. Requires a real owned HTTPS domain; we ship on the AWS-default `cloudfront.net` (`CONSTRAINTS.md`). Custom-scheme deep links (`contricool://...`) work; HTTPS deep links do not.

**B4.** Federated login (Google / Apple Sign-in). Already deferred at MVP per Design 4.

**B5.** Migration to AWS Amplify Auth v6. The hand-rolled REST + `expo-secure-store` driver is intentional for v1.

**B6.** CI auto-build of native artifacts. Manual `eas build` per release until the distribution model firms up.

**B7.** Background sync, biometric auth, in-app purchases, app-rating prompts, in-app updates, app shortcuts, widgets.

Anything in this list that becomes a v2 priority gets its own follow-up spec.

## User stories

**U1.** As a user, I can sideload the ContriCool APK on my Android phone and sign in with the same account I use on the web — and see my existing friends and transactions.

**U2.** As a user, I can install ContriCool on my iPhone via Xcode and sign in with the same account — same data, same UI patterns.

**U3.** As a user, when I close the Android app and reopen it days later, I'm still signed in (refresh token in secure storage works).

**U4.** As a user, when my session expires while I'm using the app, the next API call transparently refreshes my session — no re-login interruption (mirrors web behavior).

**U5.** As a user, when the app crashes or hits a network error, the developer (oah1234) gets a structured event in Sentry within seconds — with no user PII attached.

**U6.** As a developer, I can run a single command (`eas build --profile preview --platform android`) to produce an installable APK pointing at the dev backend.

**U7.** As a developer, I can plug in my iPhone, hit Run in Xcode, and have the app installed on my device using my free personal Apple-ID team.

**U8.** As a developer, I can re-deploy the web app and trust the existing CI gates (lint, typecheck, test, bundle-size) catch any regression introduced by the native work.

## Edge cases & constraints

**E1. Token refresh under platform-specific failure modes.** On native, `expo-secure-store` can fail (e.g., user wipes app data, biometric storage corruption). The driver must clear in-memory state and surface a clean re-login prompt — never crash, never throw an unhandled rejection.

**E2. Cellular flaps.** Mobile users transition between WiFi and LTE mid-request. The SDK retry logic (already in `packages/client-sdk`) should cover transient failures; no native-specific retry tuning at v1.

**E3. Keyboard occlusion of submit buttons.** Forms must use `KeyboardAvoidingView` (or NativeWind equivalent) on native to keep CTAs visible above the IME. Web has no equivalent issue.

**E4. Notch / Dynamic Island / Android status bar.** All screens must render inside `SafeAreaView`; no content under the status bar or home indicator.

**E5. The `Select` primitive currently returns `null` on native** (`apps/client/components/ui/Select.tsx` Phase 2d limitation). Native must implement a Sheet-based picker so any screen using a dropdown actually works.

**E6. Android back button.** Hardware back must navigate the expo-router stack correctly (default behavior is correct for stack screens; modal/sheet screens may need explicit handling).

**E7. iOS swipe-back gesture.** Must not conflict with horizontal-scroll regions inside lists.

**E8. Free Apple-ID provisioning expires every 7 days.** The iOS sideload runbook must include re-install instructions; this is acceptable for personal-device use only.

**E9. Sentry source-map upload must succeed.** Without source maps, native stack traces are unreadable. EAS post-build hook returns non-zero on upload failure → build fails loudly rather than silently shipping unsymbolicated.

**E10. PII denylist applies to Sentry too.** `email`, `phone`, `password`, `code`, `otp`, `Authorization`, `Cookie`, `set-cookie`, `secret`, `token`, `refresh_token` must be scrubbed in Sentry's `beforeSend`.

**E11. Sideload-only means no rollback.** A bad APK installed via `adb install -r` doesn't auto-revert. Mitigation: keep the previous APK on disk; reinstall manually if needed. Acceptable for personal-use distribution.

**E12. Web bundle must not regress.** Every native change ships behind a Metro platform suffix (`.native.ts` / `.ios.ts` / `.android.ts`) or a runtime `Platform.OS` check, so the web bundle stays byte-equivalent where possible.

**E13. Phase 7 conflict.** Phase 7 (in flight on a parallel thread) may modify shared client files. Phase 8a does not start until Phase 7 is merged to `main`.

**E14. CORS on API Gateway.** Native clients send no `Origin` header; the existing permissive API Gateway CORS config (Design 9) must continue to accept native requests. (Audit confirms: it already does.)

**E15. Test infrastructure.** Vitest with `react-native-web` aliasing covers shared logic. Native-only components need either a Vitest skip-on-web sentinel or a parallel jest setup; v1 tolerates a small native-only blind spot if the component is purely presentational.

## Constraints inherited from project standards

- `RED LINE 1` — No CloudFront domain, no Cognito pool ID, no AWS account ID hardcoded. Build-time injection only via `EXPO_PUBLIC_*` env vars passed through `eas build --env-file`.
- `RED LINE 2` — No new AWS resources at v1 (no SNS Mobile Push, no Pinpoint). Backend cost guardrails unchanged.
- `RED LINE 3` — Auth, secure-storage, and refresh paths get negative tests: missing token, expired token, secure-store wipe, refresh failure clears state.
- Coverage floor 99% on `lib/**`, 80% on `app/**` and `components/**`.
- One thing at a time, no gold-plating, no dead code (CLAUDE.md SECTION 9).

## Acceptance criteria

The native mobile rollout is complete when:

1. An APK signed by EAS installs cleanly on a real Android device via `adb install -r`, and a smoke pass through every screen succeeds against dev backend.
2. An IPA built locally on the Mac installs via Xcode on the user's iPhone, and the same smoke pass succeeds.
3. Sentry receives test events from both platforms with correct `dist:android` / `dist:ios` tags and source-mapped stack traces; no PII appears in any event.
4. The full web e2e nightly continues to pass with no regressions traced to native work.
5. `pnpm --filter @contricool/client test:coverage` stays at thresholds.
6. Runbooks for both sideload procedures exist under `specs/runbooks/` and have been executed end-to-end at least once.

## Summary

Native is reachable from the existing codebase with no backend changes, no new AWS infrastructure, no store accounts, and no new heavy dependencies. The rollout is four phases (foundation → Android → iOS → parity fixes), governed by the existing red lines, and intentionally lean — push, universal links, federation, and store submission are deferred to follow-up specs. The single biggest risk is timing against Phase 7 in the parallel thread; the mitigation is to gate Phase 8a start on Phase 7 merge.
