import { useRouter } from 'expo-router';
import { Pressable, ScrollView, Text, View } from 'react-native';

const EFFECTIVE = '2026-04-29';

export default function PrivacyScreen() {
  const router = useRouter();
  const onBack = (): void => {
    if (router.canGoBack()) {
      router.back();
    } else {
      router.replace('/login');
    }
  };
  return (
    <ScrollView className="flex-1 bg-neutral-50" contentContainerClassName="p-6">
      <View className="mx-auto w-full max-w-2xl gap-4">
        <Text testID="privacy-title" className="text-3xl font-bold text-neutral-900">
          Privacy Policy
        </Text>
        <Text className="text-sm text-neutral-500">Effective date: {EFFECTIVE}</Text>

        <Section title="Who we are">
          ContriCool ("we", "us") is a hobby-scale expense-splitting service. Contact:{' '}
          <Text className="font-medium">support@contricool.app</Text>.
        </Section>

        <Section title="What we collect">
          - Account data: email address, display name, default currency.{'\n'}- Transaction data:
          amounts, descriptions, dates, members, payers and split shares for transactions you create
          or are added to.{'\n'}- Friend graph: pairs of users you have added as friends.{'\n'}-
          Operational logs: request metadata (no request bodies), error traces with PII scrubbed.
        </Section>

        <Section title="What we do NOT collect">
          - We do not collect your phone number at MVP.{'\n'}- We do not collect device identifiers,
          advertising IDs, or precise location.{'\n'}- We do not sell or rent your data to third
          parties.
        </Section>

        <Section title="How we use it">
          Solely to operate the service: authenticate you, render your transactions and friends, and
          email you transactional notifications (sign-up confirmation, password reset). No marketing
          email at MVP.
        </Section>

        <Section title="Where it is stored">
          AWS (us-west-2). DynamoDB and S3 with encryption at rest; TLS 1.2+ in transit.
        </Section>

        <Section title="Your rights">
          You can export all of your data from{' '}
          <Text className="font-medium">Settings → Export my data</Text> (rate-limited to one per
          day). Each export contains your most-recent 500 transactions; if you have more, request
          another export after the cooldown — full data is always available on request via{' '}
          <Text className="font-medium">support@contricool.app</Text>.{'\n'}You can delete your
          account from <Text className="font-medium">Settings → Delete my account</Text>. Deletion
          is immediate from your perspective. Your profile, friend graph, and Cognito identity are
          hard-deleted after a 30-day window so the action remains reversible by support if you
          change your mind. Transactions you shared with other users keep your opaque internal
          user-ID on the membership row (no email, name, or phone) so the other parties' history
          stays intact — the UI renders the missing user as "—".{'\n'}California residents (CCPA)
          and India residents (DPDP Act 2023) have additional rights to access, correct, and delete
          personal data. Email <Text className="font-medium">support@contricool.app</Text> to
          exercise them outside of the in-app controls.
        </Section>

        <Section title="Cookies and tracking">
          We use one strictly-necessary first-party cookie to keep you signed in. No third-party
          analytics or ad cookies.
        </Section>

        <Section title="Children">
          ContriCool is not directed at children under 13. We do not knowingly collect personal data
          from children.
        </Section>

        <Section title="Changes">
          When we update this policy we will post the new effective date at the top. For material
          changes we will also email account holders.
        </Section>

        <View className="pt-4">
          <Pressable onPress={onBack} testID="privacy-back">
            <Text className="text-blue-600 underline">← Back</Text>
          </Pressable>
        </View>
      </View>
    </ScrollView>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <View className="mt-2 gap-2">
      <Text className="text-xl font-semibold text-neutral-900">{title}</Text>
      <Text className="text-base leading-6 text-neutral-700">{children}</Text>
    </View>
  );
}
