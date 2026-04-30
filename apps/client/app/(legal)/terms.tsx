import { useRouter } from 'expo-router';
import { Pressable, ScrollView, Text, View } from 'react-native';

const EFFECTIVE = '2026-04-29';

export default function TermsScreen() {
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
        <Text testID="terms-title" className="text-3xl font-bold text-neutral-900">
          Terms of Service
        </Text>
        <Text className="text-sm text-neutral-500">Effective date: {EFFECTIVE}</Text>

        <Section title="Acceptance">
          By creating an account or using ContriCool, you agree to these terms. If you do not agree,
          do not use the service.
        </Section>

        <Section title="The service">
          ContriCool helps small groups split shared expenses. It is a record-keeping tool; it does
          not move money, charge cards, or settle debts on your behalf. Any monetary settlement
          between users happens off-platform.
        </Section>

        <Section title="Your account">
          You must provide an accurate email and keep your password confidential. You are
          responsible for activity under your account. Notify us at{' '}
          <Text className="font-medium">support@contricool.app</Text> of unauthorized access.
        </Section>

        <Section title="Acceptable use">
          Do not: (a) attempt to access another user's account or data; (b) abuse the service to
          spam or harass; (c) attempt to discover security vulnerabilities without coordinating with
          us first; (d) submit content that is illegal, fraudulent, or infringes others' rights.
        </Section>

        <Section title="No financial advice">
          Balances and split math are best-effort calculations. ContriCool is not a regulated
          financial service; figures shown are not legal accounting records.
        </Section>

        <Section title="Availability">
          We aim for high availability but do not guarantee uptime. The service is provided "as is"
          without warranties of any kind to the extent permitted by law.
        </Section>

        <Section title="Limitation of liability">
          To the maximum extent permitted by applicable law, our aggregate liability for any claim
          arising out of the service is limited to USD 50.
        </Section>

        <Section title="Termination">
          You may delete your account at any time from{' '}
          <Text className="font-medium">Settings → Delete my account</Text>. We may suspend accounts
          that violate these terms.
        </Section>

        <Section title="Changes">
          When we update these terms we will post the new effective date and notify account holders
          by email for material changes. Continued use after the effective date constitutes
          acceptance.
        </Section>

        <Section title="Governing law">
          These terms are governed by the laws of the user's country of residence to the extent
          required by mandatory consumer law; otherwise the laws of the State of Delaware, USA.
        </Section>

        <View className="pt-4">
          <Pressable onPress={onBack} testID="terms-back">
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
