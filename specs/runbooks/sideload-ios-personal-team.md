# Runbook — iOS Sideload via Personal Team (Phase 8c)

**Audience:** the developer running the build on a Mac and installing the app on a personal iPhone using a free Apple ID provisioning profile. **No paid Apple Developer Program account at v1.**

**Distribution model:** sideload-only. Each build either gets installed via Xcode → Devices and Simulators (drag-drop) or via `eas build --local` + `xcrun devicectl`. No App Store, no TestFlight. Free Apple ID provisioning expires every **7 days**, so plan to reinstall weekly during soak.

---

## One-time setup

1. **Mac with Xcode installed** (latest stable; Xcode 16 or newer at the time of writing). The full Xcode app, not just Command Line Tools — we need the iOS SDK and `xcrun simctl`.

2. **Apple ID signed into Xcode.**
   - Xcode → Settings → Accounts → `+` → Apple ID.
   - The personal Apple ID will show one provisioning team named **"<Your Name> (Personal Team)"** — that's what free signing uses.

3. **iPhone in Developer Mode.**
   - Plug the iPhone into the Mac. Trust the computer when prompted.
   - On the iPhone: Settings → Privacy & Security → Developer Mode → On (requires a restart).

4. **Expo / EAS account.** Same as Android. `pnpm dlx eas-cli@latest login` once.

---

## Per-release flow — Option A (recommended): EAS local build → Xcode install

This keeps you on the cloud build pipeline (consistent with Android) but produces an `.ipa` you can drag into Xcode.

### 1. Build locally

```bash
cd apps/client
pnpm build:ios
# equivalent: pnpm dlx eas-cli build --profile preview --platform ios --local
```

**Use `--profile preview`, NOT `development`**, for sideload. The `development` profile in `eas.json` has `simulator: true` — it builds a Simulator-only artifact (x86_64 / arm64-simulator slice) that **cannot install on a physical iPhone** and Xcode's drag-drop will fail with a cryptic architecture error. The `preview` profile has `simulator: false` and produces a device-deployable `.ipa`.

`--local` runs the build on your Mac instead of EAS Cloud, which is required for free Apple-ID signing (EAS Cloud doesn't accept personal-team profiles for cloud signing). It also doesn't burn the 15-build/month quota on the free Expo plan. Output: an `.ipa` archive. Wall-clock: **~15–20 min** on an M-series Mac.

If you specifically want a Simulator build for desktop testing (no iPhone in hand), keep the `development` profile and install the `.app` via `xcrun simctl install booted <path>` instead.

### 2. Install via Xcode

1. Plug in the iPhone, unlock it.
2. Xcode → Window → Devices and Simulators (`Cmd+Shift+2`).
3. Select your iPhone in the left panel.
4. Drag the `.ipa` into the **Installed Apps** list (Xcode unwraps the archive automatically).
5. Watch the progress bar — installation takes ~30s. The app icon appears on the home screen.

### 3. First-launch trust prompt

iOS won't run a personally-signed app until you explicitly trust the developer. On the iPhone:

- Settings → General → VPN & Device Management → **Developer App** section
- Tap your Apple ID → **Trust "<your apple id>"**
- Confirm.

The app now launches. Subsequent reinstalls of the same app/team don't repeat this dance.

---

## Per-release flow — Option B: Xcode prebuild + Run

If you'd rather skip EAS and build straight from Xcode:

```bash
cd apps/client
# Use the project-pinned Expo CLI (`pnpm exec expo`), NOT
# `pnpm dlx expo` — the latter pulls the latest expo-cli (currently
# tracking SDK 55 / RN 0.83 templates) and emits an
# AppDelegate.swift that imports `ReactAppDependencyProvider`,
# which doesn't exist in our pinned RN 0.76. The project-pinned
# CLI emits the older AppDelegate.h/.mm that matches RN 0.76.
pnpm exec expo prebuild --platform ios --clean
open ios/ContriCool.xcworkspace
```

After prebuild, inject the local-only env vars + Xcode 26 C++ override
(`ios/` is gitignored, so these don't survive a clean prebuild):

```bash
# 1. Tell the bundler script which API to bake into the JS bundle.
#    Without this, `lib/api.ts` falls back to '/v1' (relative URL)
#    which fails on native fetch with no host context.
cat >> apps/client/ios/.xcode.env.local <<'EOF'
export SENTRY_DISABLE_AUTO_UPLOAD=true
export EXPO_PUBLIC_API_BASE_URL=https://<your-dev-cloudfront-domain>/v1
EOF

# 2. Patch the Podfile post_install hook so every Pod target compiles
#    with C++20 — Xcode 26's default for some pod build configs is
#    c++14, which breaks RCT-Folly (`static_assert(__cplusplus >= 201703L)`)
#    and React-perflogger's `FuseboxTracer.cpp` (uses `std::unordered_map::contains`,
#    a c++20 feature). Insert just before the closing `end end` of
#    the existing `post_install do |installer|` block:
#
#    installer.pods_project.targets.each do |target|
#      target.build_configurations.each do |config|
#        config.build_settings['CLANG_CXX_LANGUAGE_STANDARD'] = 'c++20'
#        config.build_settings['CLANG_CXX_LIBRARY'] = 'libc++'
#      end
#    end

cd apps/client/ios && pod install && cd -
```

(Folding both into a config plugin so they survive prebuilds is
tracked as a Phase 8d follow-up.)

In Xcode:
1. Select the **ContriCool** target → Signing & Capabilities → Team → your personal team.
2. Select your iPhone as the run destination (top toolbar).
3. **Edit Scheme** (⌘<) → Run → Build Configuration: **Release**.
   Debug builds expect a Metro packager on `localhost:8081`; Release
   embeds `main.jsbundle` so the app runs standalone like Android does.
4. ⌘R to build and run.

This is the fastest iteration loop (Xcode's incremental build) but bypasses EAS, so the artifact isn't reproducible in CI. Use Option A for "official" sideload builds, Option B for active development.

---

## Smoke checklist

Same 13 items as `sideload-android.md` plus three iOS-specific:

- **Status bar style.** Should switch correctly across light/dark theme on a Dynamic Island iPhone (14 Pro and newer).
- **Swipe-back gesture.** Native iOS swipe-from-left-edge should work on every screen with a back button. expo-router handles this — verify it doesn't break on screens that programmatically `router.replace()`.
- **Notch / Dynamic Island clipping.** Verify no UI is hidden under the notch on the dashboard, friends list, transactions list. `react-native-safe-area-context` is already wired; this is about catching screens that forgot to use `<SafeAreaView>`.

Verify Sentry events tagged `dist:ios` (separate from Android).

---

## Re-installing every 7 days

Free Apple ID provisioning expires after exactly 7 days. Symptoms:
- App icon dims and won't launch ("Untrusted Developer" or just nothing happens).
- Tapping → "<App> not available" or "could not connect to host."

To refresh: re-run the install (Option A or Option B). The new provisioning profile is stamped automatically. **Existing app data persists** because the bundle ID (`com.contricool.app`) is unchanged.

If you find yourself re-installing 4× per month, that's the trigger to enroll in the **Apple Developer Program** ($99/year) — which extends provisioning to 1 year and unlocks TestFlight. Out of v1 scope; tracked as an open item in the rollout plan.

---

## Known gotchas

- **"No matching provisioning profiles found"** in Xcode signing: the personal team's profile gets generated lazily on first build. Click "Try Again" and Xcode mints one. If it loops, sign out / sign in to your Apple ID in Xcode → Settings → Accounts.
- **App crashes on launch with "Killed: 9"** in Console.app: usually a Sentry/Firebase native module that wasn't pod-installed. Re-run `pod install` inside `ios/` (or just re-run prebuild with `--clean`).
- **`xcrun: error: unable to lookup item 'PlatformPath'`**: open Xcode at least once to accept the EULA, then `sudo xcode-select --switch /Applications/Xcode.app`.
- **EAS local build fails with "no provisioning profile"**: free Apple-ID profiles can't be uploaded to EAS for cloud builds. Use Option A (`--local`) or Option B (Xcode-direct).
- **Hermes is on by default** in Expo SDK 52 — stack traces are minified. Sentry source-map upload (Phase 8d) symbolicates them. For local dev, lean on the JS Debugger in Safari (Develop menu → iPhone → ContriCool).

---

## Quick reference

```bash
# List paired devices visible to Xcode
xcrun xctrace list devices

# Stream logs from a real device:
#   open Console.app → in the left sidebar pick your iPhone → filter
#   the search bar by "ContriCool". The device must be plugged in and
#   trusted (the same Trust prompt as the first install).
#
# For Simulator only (NOT a real device):
xcrun simctl spawn booted log stream --predicate 'process == "ContriCool"'

# Force-quit the app from Mac
xcrun devicectl device process terminate --device <udid> --bundle-id com.contricool.app

# Inspect the installed bundle
xcrun devicectl device info apps --device <udid>
```

---

## When to escalate to App Store

Trigger conditions:
- Need to share builds with people who don't have your Mac.
- The 7-day expiry becomes operationally annoying (>1 expiry / week).
- TestFlight beta testing required.
- A compliance / legal requirement appears (App Store data-collection labels).

The v2 spec covers: Apple Developer Program enrollment ($99/year), TestFlight setup, Fastlane match for signing keys, EAS Submit, App Store Connect listing, screenshots, privacy labels (`NSCalendarsUsageDescription`, etc. — currently we use no permissions so this is short), App Tracking Transparency disclosure.
