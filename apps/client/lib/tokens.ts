/**
 * Design tokens shared between the Tailwind/NativeWind theme and
 * any runtime JS that needs raw values (e.g. animated gestures or
 * RN components that bypass className).
 *
 * Keep in sync with tailwind.config.ts.
 */

export const colors = {
  primary: {
    50: '#eff6ff',
    100: '#dbeafe',
    500: '#3b82f6',
    600: '#2563eb',
    700: '#1d4ed8',
    900: '#1e3a8a',
  },
  neutral: {
    50: '#f8fafc',
    100: '#f1f5f9',
    200: '#e2e8f0',
    300: '#cbd5e1',
    500: '#64748b',
    700: '#334155',
    900: '#0f172a',
  },
  success: { 600: '#16a34a' },
  warning: { 600: '#d97706' },
  danger: { 600: '#dc2626' },
  surface: '#ffffff',
  text: '#0f172a',
  muted: '#64748b',
} as const;

export const radii = { sm: 4, md: 8, lg: 12, full: 9999 } as const;
export const space = { 1: 4, 2: 8, 3: 12, 4: 16, 6: 24, 8: 32 } as const;
export const typography = {
  fontFamily: { sans: 'Inter, system-ui, sans-serif' },
  size: { xs: 12, sm: 14, base: 16, lg: 18, xl: 20, '2xl': 24 },
  weight: { regular: '400', medium: '500', semibold: '600', bold: '700' },
} as const;
