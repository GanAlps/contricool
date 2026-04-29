import { Link } from 'expo-router';
import { Text, View } from 'react-native';

export default function NotFound() {
  return (
    <View className="flex-1 items-center justify-center bg-neutral-50 p-6">
      <Text className="mb-2 text-2xl font-bold text-neutral-900">404</Text>
      <Text className="mb-4 text-sm text-neutral-700">This page doesn't exist.</Text>
      <Link href="/" className="text-sm text-primary-600">
        Go home
      </Link>
    </View>
  );
}
