# Runbook — Android Sideload (Phase 8b)

**Audience:** the developer (you, AFK or back at desk) shipping a debug build of ContriCool to a personal Android device. No Play Store account, no Fastlane, no CI/CD for native artifacts at v1 — manual end-to-end.

**Distribution model:** sideload-only. Each build is downloaded as an APK from EAS, then installed via `adb install -r`. Replacing an installed APK with `-r` keeps existing data; uninstalling first wipes secure storage including the saved refresh token.

---

## One-time setup (already done; re-do if a teammate joins)

1. **Expo / EAS account.** Free tier is fine for personal sideload. Run `pnpm dlx eas-cli@latest login` once on the dev machine. Stored in `~/.expo/state.json`.

2. **EAS project init.** `eas init` (one-time per repo) mints a project ID, which goes into `apps/client/app.json` under `extra.eas.projectId`. **Do not commit the project ID if it ties to a personal account** — EAS treats it as semi-public, but per RED LINE 1 it's safer to inject via env var at build time. Until we have an org account, accept the personal-project ID being committed and rotate when transferring to an org.

3. **Android adb.** Install `android-tools` (Linux: `apt install android-tools`; macOS: `brew install android-platform-tools`). Verify: `adb devices` shows your device when plugged in (after enabling USB debugging in Developer Options).

---

## Per-release flow

### 1. Build the APK

```bash
cd apps/client
pnpm dlx eas-cli build --profile preview --platform android
```

This kicks off a cloud build. Watch progress in the terminal or at `https://expo.dev/accounts/<your-account>/projects/contricool/builds`. Typical wall-clock: **~10–15 min**.

The `preview` profile in `apps/client/eas.json`:
- builds an APK (not AAB — APK is what `adb install` accepts)
- uses `:app:assembleRelease` Gradle task
- bundles the **dev** API base URL (override via `--env-file` if shipping a build pointed at prod)

### 2. Download and install

When the build finishes, EAS prints a download URL. Either:

```bash
# Option A: let the CLI install it for you (asks before installing)
pnpm dlx eas-cli build:run -p android

# Option B: download and install manually
curl -L "https://expo.dev/artifacts/.../build.apk" -o /tmp/contricool.apk
adb install -r /tmp/contricool.apk
```

`-r` replaces the existing install. Without `-r`, adb refuses if the package is already installed.

### 3. Smoke checklist (the same one you run on web before tagging a release)

Run through every screen before considering the build "soaked." Each numbered item is a single click-path:

1. **Cold start** — kill the app from Recents, launch fresh. Should land on `/` or `/login` (depending on saved refresh-token state).
2. **Login** — sign in with a test account; expect to land on the dashboard.
3. **Refresh-token bootstrap** — kill and reopen the app within 30 days. Expect silent re-auth (no login screen).
4. **Friend list / detail** — tap through.
5. **Add friend** — happy path + already-friends 409 + non-existent email 404.
6. **Create transaction** — multi-payer + non-equal split. Verify the audit trail entry shows up.
7. **Edit transaction** — change amount; verify the optimistic update + final state.
8. **Delete transaction** — soft-delete; verify it disappears from the list.
9. **Restore transaction** — un-delete; verify it returns.
10. **Comments** — add + view.
11. **Settings** — currency change, delete account flow (don't confirm in prod).
12. **Sign out** — expect to land back on `/login`. Re-launching app should land on `/login` (no stale token).
13. **Negative cases** —
    - airplane-mode mid-request → expected error toast, app doesn't crash
    - 6th OTP request in an hour → 429 with rate-limit UI
    - expired token (force-refresh manually) → re-login prompt, no boot loop

### 4. Verify telemetry

1. Open the Sentry dashboard, filter by `dist:android` (or whatever EAS Build set as `dist`).
2. Trigger a deliberate JS error from the QA debug button (TBD — Phase 8d adds it) and confirm it lands within 60s.
3. Verify the event is **scrubbed**: no `email`, no `password`, no `Authorization` header, no `refresh_token` anywhere in the payload (Issues view → Event JSON tab).

If a PII leak is found here, RED LINE 1 fail — file an immediate fix and roll back to the previous APK on your device.

---

## Rolling back a bad build

There is no app-store rollback because there is no app store. To revert to the previous build:

1. Find the prior APK in `~/Downloads` or your build artifact archive.
2. `adb install -r <prior>.apk` (or `-r -d` to allow downgrade if `versionCode` decreased).

If you uninstall first instead of replacing, secure-storage refresh token is wiped → user has to sign in again. That's an inconvenience, not data loss.

---

## Known gotchas

- **First build often fails on `gradlew :app:assembleRelease` due to Gradle/JDK mismatch.** EAS provides a known-good Android image; we don't manage Gradle locally. If a build fails with a Gradle error, re-run — usually a transient cache issue.
- **`adb install` fails with `INSTALL_FAILED_INSUFFICIENT_STORAGE`**: check device free space; the APK installs ~80–120 MB.
- **Push not working**: deferred to post-MVP. There is no SNS/FCM wiring yet.
- **Hot reload doesn't work in this build**: `preview` is a release-flavored build. For hot reload, use `pnpm dev` with the Expo Go client on the device (development profile).
- **Sentry source maps not symbolicated**: deferred to Phase 8d (EAS post-build hook). For now, stack traces show minified Hermes output. Workable for debugging, not pretty.
- **Free Apple-style 7-day expiry does NOT apply to Android.** Once installed, the APK runs indefinitely.

---

## When to escalate to a real Play Store release

Trigger conditions for filing the v2 spec:
- More than ~5 sideloads in a month → friction is too high.
- Need to share a build with someone who isn't on your machine.
- A compliance / legal requirement appears (Play Store data-safety attestations).

The v2 spec covers: Play Console enrollment, app-signing key management, Fastlane, EAS Submit, internal testing track, screenshots, store listing copy, privacy labels.

---

## Quick reference — useful commands

```bash
# List connected devices
adb devices

# Tail logs from the app (filter by package)
adb logcat | grep com.contricool.app

# Force-stop the app
adb shell am force-stop com.contricool.app

# Clear app data (wipes secure-storage refresh token)
adb shell pm clear com.contricool.app

# Verify the installed APK version
adb shell dumpsys package com.contricool.app | grep versionName
```
