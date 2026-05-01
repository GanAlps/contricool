import { Platform, Text, View } from 'react-native';

import { Button } from '~/components/ui/Button';
import { Card } from '~/components/ui/Card';
import { reportError } from '~/lib/telemetry';

/**
 * QA tools card — hidden on web and on native production builds.
 *
 * Visible when **both** are true:
 *   - `Platform.OS !== 'web'` (so the web bundle stays clean — these
 *     are smoke buttons for sideloaded native builds)
 *   - `process.env.EXPO_PUBLIC_ENV !== 'production'` (so a release
 *     APK / IPA pointed at prod doesn't expose a "crash the app"
 *     button to a real user)
 *
 * The card is referenced by both sideload runbooks
 * (`specs/runbooks/sideload-{android,ios-personal-team}.md`) as the
 * way to verify Sentry capture + PII scrubbing during the smoke
 * pass — trigger an error here, then check the Sentry dashboard
 * filtered by `dist:android` (or `ios`) to confirm:
 *   1. the event arrives,
 *   2. release / dist tags are correct,
 *   3. NO PII (`email`, `Authorization`, etc.) appears in the
 *      payload (RED LINE 1).
 */
export function QaTools() {
  if (Platform.OS === 'web') {
    return null;
  }
  if (process.env.EXPO_PUBLIC_ENV === 'production') {
    return null;
  }
  return (
    <Card testID="qa-tools">
      <Text className="mb-1 text-base font-semibold text-neutral-900">QA tools (debug build)</Text>
      <Text className="mb-3 text-sm text-neutral-600">
        Smoke buttons for verifying telemetry capture. Hidden in web and production native builds.
      </Text>
      <View className="flex-row flex-wrap gap-2">
        <Button
          testID="qa-tools-throw-js"
          variant="ghost"
          onPress={() => {
            // Route through the telemetry helper so we test the same
            // path the ErrorBoundary uses in the wild. Native bundle
            // forwards this to Sentry; web (which never renders this
            // card) would have routed to /v1/telemetry/error.
            reportError('qa-tools-deliberate-js-error', new Error('QA: deliberate JS error'));
          }}
        >
          Trigger JS error
        </Button>
        <Button
          testID="qa-tools-fetch-fail"
          variant="ghost"
          onPress={() => {
            // Fire a deliberately-broken fetch so we exercise the
            // network-error capture path. We don't care about the
            // response — only that the failure surfaces in Sentry.
            void fetch('http://localhost:0/qa-tools-deliberate-fetch-fail').catch((e: unknown) => {
              reportError('qa-tools-deliberate-fetch-error', e);
            });
          }}
        >
          Trigger fetch error
        </Button>
      </View>
    </Card>
  );
}
