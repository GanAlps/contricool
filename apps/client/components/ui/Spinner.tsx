import { ActivityIndicator } from 'react-native';

import { colors } from '~/lib/tokens';

export function Spinner({
  size = 'small',
  color = colors.primary[600],
  testID,
}: {
  size?: 'small' | 'large';
  color?: string;
  testID?: string;
}) {
  return <ActivityIndicator size={size} color={color} testID={testID ?? 'spinner'} />;
}
