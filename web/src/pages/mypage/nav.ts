export type MyPageId = 'dashboard' | 'mypc' | 'configs' | 'consults' | 'reports' | 'profile'

export const NAV: ([MyPageId, string, string] | 'separator')[] = [
  ['dashboard', '⌂', '대시보드'],
  ['mypc', '▣', '내 현재 PC'],
  ['configs', '▦', '내 구성'],
  ['consults', '▤', 'AI 상담 기록'],
  ['reports', '▧', '추천 리포트'],
  'separator',
  ['profile', '♙', '내 정보 관리'],
]
