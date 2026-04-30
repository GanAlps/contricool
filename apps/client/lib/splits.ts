/**
 * Client-side preview of the server's split-method math.
 *
 * Mirrors `apps/api/app/features/transactions/splits.py`:
 * `ROUND_DOWN` per-member share + last-member-absorbs-remainder
 * so `sum(owed) === amount` exactly. We do the math in integer
 * cents (BigInt) to avoid IEEE-754 drift; no float arithmetic
 * anywhere on the money path.
 *
 * Inputs are strings so we can faithfully round-trip the
 * decimal places the user typed (`'30.00'` not `30.0`).
 */

const SCALE = 100n;

function toCents(amount: string): bigint {
  const trimmed = amount.trim();
  const m = /^(\d+)(?:\.(\d{1,2}))?$/.exec(trimmed);
  if (!m) {
    throw new Error(`invalid amount string: ${amount}`);
  }
  const whole = BigInt(m[1] ?? '0');
  const frac = (m[2] ?? '00').padEnd(2, '0').slice(0, 2);
  return whole * SCALE + BigInt(frac);
}

function fromCents(cents: bigint): string {
  const negative = cents < 0n;
  const abs = negative ? -cents : cents;
  const whole = abs / SCALE;
  const frac = (abs % SCALE).toString().padStart(2, '0');
  return `${negative ? '-' : ''}${whole.toString()}.${frac}`;
}

export type SplitMethod = 'equal' | 'amount' | 'share' | 'percent';

export function previewEqualSplit(amount: string, memberCount: number): string[] {
  if (memberCount < 1) throw new Error('memberCount must be ≥ 1');
  const cents = toCents(amount);
  const per = cents / BigInt(memberCount); // ROUND_DOWN
  const head = Array.from({ length: memberCount - 1 }, () => fromCents(per));
  const used = per * BigInt(memberCount - 1);
  head.push(fromCents(cents - used));
  return head;
}

export function previewShareSplit(amount: string, shares: string[]): string[] {
  const cents = toCents(amount);
  const sharesC = shares.map((s) => toCents(s));
  const total = sharesC.reduce((a, b) => a + b, 0n);
  if (total <= 0n) throw new Error('shares must sum to a positive number');
  const head = sharesC.slice(0, -1).map((s) => fromCents((cents * s) / total));
  const used = head.reduce((a, b) => a + toCents(b), 0n);
  head.push(fromCents(cents - used));
  return head;
}

export function previewPercentSplit(amount: string, percents: string[]): string[] {
  const cents = toCents(amount);
  const head = percents.slice(0, -1).map((p) => fromCents((cents * toCents(p)) / (100n * SCALE)));
  const used = head.reduce((a, b) => a + toCents(b), 0n);
  head.push(fromCents(cents - used));
  return head;
}

export function sumAmounts(amounts: string[]): string {
  const total = amounts.reduce((acc, a) => acc + toCents(a), 0n);
  return fromCents(total);
}

export { fromCents as _fromCents, toCents as _toCents };
