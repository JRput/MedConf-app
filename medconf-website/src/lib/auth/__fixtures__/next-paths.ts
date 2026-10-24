// Shared fixtures for every `next`-parameter validator test. safeNextPath
// (lib/auth/password.ts) is the single implementation; isSafeNext
// (lib/auth/urls.ts) delegates to it, and both test files run these lists.
export const SAFE_NEXT: string[] = [
  '/',
  '/conferences',
  '/conferences?q=a&b=c',
  '/conferences?q=heart%20failure&x=1',
  '/conferences/548',
  '/auth/reset-password',
  '/conferences?q=a:b#x',
]

export const UNSAFE_NEXT: string[] = [
  '//evil.com',
  '/.//evil.com',
  '/a//b',
  '/a/b//c',
  '/\\evil.com',
  '/a\\b',
  'javascript:alert(1)',
  '/javascript:alert(1)',
  'https://x',
  'https://evil.example/x',
  'conferences',
  '/ok\nnewline',
  '/a b',
  '',
]
