export type CommunityBoard = 'all' | 'popular' | 'question' | 'review' | 'tip' | 'free'
export type CommunityView = 'home' | 'board' | 'post' | 'write' | 'deals' | 'search'

export interface CommunityPost {
  id: string
  board: Exclude<CommunityBoard, 'all'>
  boardLabel: string
  author: string
  handle: string
  time: string
  title: string
  excerpt: string
  comments: number
  likes: number
  views: number
  is_example: boolean
  likedByMe?: boolean
  mediaCount?: number
  badge?: string
  specs?: Array<{ label: string; value: string }>
  products?: Array<{ kind: string; name: string; detail: string }>
}

export const boardInfo: Record<CommunityBoard, { label: string; description: string }> = {
  all: { label: '전체 글', description: '커뮤니티의 모든 게시글을 최신순으로 확인하세요.' },
  popular: { label: '인기 글', description: '최근 조회·댓글·추천 반응이 뜨거운 게시글을 모았습니다.' },
  question: { label: '질문 · Q&A', description: '견적, 호환성, 조립과 설정에 관한 질문을 나눠보세요.' },
  review: { label: '사용기 · 리뷰', description: '직접 사용한 제품과 셋업 경험을 공유합니다.' },
  tip: { label: '정보 · 팁', description: '부품 선택과 관리에 도움이 되는 정보를 모았습니다.' },
  free: { label: '자유 게시판', description: 'PC와 게임에 관한 이야기를 자유롭게 나눠보세요.' },
}

const exampleCommunityPosts: Array<Omit<CommunityPost, 'is_example'>> = [
  {
    id: 'build-check-200', board: 'question', boardLabel: '견적질문', author: '프레임장인', handle: '@frame_maker', time: '18분',
    title: '200만원대 영상 편집용 PC, 이 구성 괜찮을까요?',
    excerpt: '4K 영상 편집과 가벼운 3D 작업용입니다. 파워 용량과 쿨러 구성이 과하지 않은지 궁금합니다.',
    comments: 24, likes: 18, views: 318, badge: '답변 진행 중',
    specs: [{ label: '예산', value: '180~220만원' }, { label: '용도', value: '4K 편집' }, { label: '중요 조건', value: '저소음' }],
  },
  {
    id: 'mouse-review', board: 'review', boardLabel: '사용기 · 마우스', author: '클릭연구소', handle: '@click_lab', time: '31분',
    title: '경량 무선 마우스 한 달 사용기 — 그립감과 배터리 중심',
    excerpt: '손 크기 18cm 기준으로 팜·클로 그립을 번갈아 사용했습니다. 클릭감과 충전 주기를 정리했습니다.',
    comments: 14, likes: 42, views: 521, mediaCount: 2, badge: '베스트',
    products: [{ kind: '마우스', name: 'AeroFit M8 Wireless', detail: '58g · 무선 · 26K 센서' }],
  },
  {
    id: 'keyboard-review', board: 'review', boardLabel: '사용기 · 키보드', author: '키캡수집가', handle: '@keycap_room', time: '48분',
    title: '저소음 기계식 키보드 실사용 후기',
    excerpt: '사무실과 집에서 번갈아 사용하며 타건음, 키압, 연결 안정성을 확인했습니다.',
    comments: 19, likes: 36, views: 447, mediaCount: 2,
    products: [{ kind: '키보드', name: 'QuietType TKL 87', detail: '텐키리스 · 무선 · 저소음축' }],
  },
  {
    id: 'cooling-tip', board: 'tip', boardLabel: '정보 · 쿨링', author: '온도계', handle: '@temp_check', time: '1시간',
    title: '여름철 CPU 온도 잡는 순서, 쿨러 교체 전 확인할 것',
    excerpt: '팬 곡선, 흡배기 방향, 먼지 필터를 먼저 점검하면 불필요한 지출을 줄일 수 있습니다.',
    comments: 11, likes: 64, views: 882,
    specs: [{ label: '난이도', value: '초급' }, { label: '소요 시간', value: '20분' }, { label: '비용', value: '0원' }],
  },
  {
    id: 'white-setup', board: 'review', boardLabel: '후기 · 셋업', author: '메쉬러버', handle: '@mesh_lover', time: '2시간',
    title: '책상 폭 1200mm에서 완성한 작은 화이트 셋업',
    excerpt: '본체는 바닥으로 내리고 모니터암과 무선 주변기기로 공간을 확보했습니다.',
    comments: 32, likes: 47, views: 736, mediaCount: 2, badge: '베스트',
  },
  {
    id: 'gpu-game', board: 'free', boardLabel: '자유', author: '밤샘게이머', handle: '@night_gamer', time: '3시간',
    title: '그래픽카드 업그레이드 체감이 가장 큰 게임은 뭘까요?',
    excerpt: '요즘 게임 중 GPU를 바꿨을 때 차이가 제일 크게 느껴졌던 타이틀을 알려주세요.',
    comments: 29, likes: 12, views: 391,
  },
  {
    id: 'qhd-monitor', board: 'review', boardLabel: '후기 · 모니터', author: '픽셀헌터', handle: '@pixel_hunter', time: '4시간',
    title: '27인치 QHD 180Hz 모니터 일주일 사용기',
    excerpt: '패널 품질, 응답 속도, 번인 걱정까지 일주일 동안 직접 써보고 느낀 점입니다.',
    comments: 16, likes: 31, views: 603, mediaCount: 3,
    specs: [{ label: '해상도', value: '2560×1440' }, { label: '주사율', value: '180Hz' }, { label: '가격', value: '249,000원' }],
  },
  {
    id: 'ssd-choice', board: 'question', boardLabel: '부품질문', author: '조립첫날', handle: '@first_build', time: '5시간',
    title: '게임용 SSD 1TB와 2TB 중 어느 쪽이 나을까요?',
    excerpt: '게임 5~6개와 작업 파일을 함께 보관할 예정입니다. 예산 차이는 6만원 정도입니다.',
    comments: 21, likes: 9, views: 275,
  },
  {
    id: 'mini-pc-review', board: 'review', boardLabel: '후기 · 사용기', author: '코딩하는곰', handle: '@coding_bear', time: '5시간',
    title: '3개월 실사용: 미니 PC로 개발 환경을 바꾼 후기', excerpt: '소음, 발열, 작업 속도가 데스크톱과 어떻게 달라졌는지 정리했습니다.',
    comments: 41, likes: 64, views: 1200, mediaCount: 1, badge: '베스트',
  },
  {
    id: 'memory-led', board: 'question', boardLabel: '질문 · Q&A', author: '조립초보', handle: '@build_beginner', time: '6시간',
    title: '부팅 후 메모리 LED가 계속 켜져 있습니다', excerpt: '램을 다시 장착하고 슬롯도 바꿨지만 메인보드의 메모리 LED가 꺼지지 않습니다.',
    comments: 19, likes: 8, views: 266,
  },
  {
    id: 'ssd-thermal', board: 'tip', boardLabel: '정보 · 팁', author: '벤치마커', handle: '@bench_marker', time: '7시간',
    title: 'SSD 온도에 따른 쓰로틀링 직접 측정', excerpt: '방열판 유무와 연속 쓰기 구간별 온도·속도 변화를 비교했습니다.',
    comments: 36, likes: 91, views: 1800,
  },
  {
    id: 'windows-settings', board: 'tip', boardLabel: '정보 · 팁', author: '클린설치', handle: '@clean_install', time: '8시간',
    title: '윈도우 설치 직후 꼭 확인할 설정 7가지', excerpt: '드라이버, 전원 관리, 시작 프로그램까지 설치 직후 확인 순서를 정리했습니다.',
    comments: 29, likes: 76, views: 1100,
  },
  {
    id: 'monitor-color', board: 'tip', boardLabel: '정보 · 팁', author: '컬러체크', handle: '@color_check', time: '9시간',
    title: '모니터 색상 설정 전에 알아둘 기본 용어', excerpt: '감마, 색온도, 색역을 실제 설정 화면과 연결해 설명합니다.',
    comments: 18, likes: 39, views: 684,
  },
  {
    id: 'screen-black', board: 'question', boardLabel: '질문 · Q&A', author: '픽셀러', handle: '@pixeler', time: '10시간',
    title: '게임 중 화면이 검게 변하고 소리만 들립니다', excerpt: 'GPU 드라이버를 다시 설치해도 고사양 게임에서 같은 문제가 반복됩니다.',
    comments: 27, likes: 12, views: 418,
  },
  {
    id: 'cpu-idle-temp', board: 'question', boardLabel: '질문 · Q&A', author: '첫조립', handle: '@first_assembly', time: '11시간',
    title: 'CPU 온도가 대기 상태에서 60도면 높은가요?', excerpt: '공랭 쿨러 장착 후 아이들 온도가 예상보다 높아 점검 순서가 궁금합니다.',
    comments: 31, likes: 10, views: 357,
  },
  {
    id: 'cable-management', board: 'free', boardLabel: '자유', author: '정리초보', handle: '@cable_beginner', time: '12시간',
    title: '책상 위 케이블 정리 다들 어떻게 하시나요?', excerpt: '모니터암 아래 전원선과 USB 허브 선을 깔끔하게 숨기는 방법을 찾고 있습니다.',
    comments: 44, likes: 18, views: 466,
  },
  {
    id: 'fan-noise', board: 'question', boardLabel: '질문 · Q&A', author: '사일런트', handle: '@silent_pc', time: '13시간',
    title: '케이스 팬 소음을 줄이는 가장 쉬운 방법', excerpt: '팬 교체 전 BIOS 팬 곡선부터 조정해보려는데 기준점을 알고 싶습니다.',
    comments: 38, likes: 22, views: 512,
  },
  {
    id: 'old-pc', board: 'free', boardLabel: '자유', author: '추억의PC', handle: '@retro_pc', time: '14시간',
    title: '오래된 PC를 정리하려니 아쉽네요', excerpt: '첫 조립 때 사용했던 부품을 어디까지 보관할지 고민입니다.',
    comments: 33, likes: 25, views: 342,
  },
  {
    id: 'parts-arrived', board: 'free', boardLabel: '자유', author: '토요일조립', handle: '@saturday_build', time: '15시간',
    title: '주말에 조립할 부품이 모두 도착했습니다', excerpt: '조립 전 박스와 구성품을 확인하고 있습니다. 놓치기 쉬운 준비물이 있을까요?',
    comments: 26, likes: 21, views: 284,
  },
  {
    id: 'bios-order', board: 'question', boardLabel: '질문 · Q&A', author: '오버클럭입문', handle: '@bios_beginner', time: '16시간',
    title: 'BIOS 업데이트 후 부팅 순서가 바뀌었습니다', excerpt: '업데이트 뒤 다른 드라이브로 부팅되어 원래 설정으로 되돌리는 방법을 찾고 있습니다.',
    comments: 14, likes: 6, views: 204,
  },
  {
    id: 'quiet-keyboard', board: 'review', boardLabel: '후기 · 키보드', author: '키감연구소', handle: '@key_lab', time: '17시간',
    title: '저소음 키보드 한 달 사용 후 느낀 점', excerpt: '사무실에서 한 달 동안 사용한 타건음과 장시간 입력 피로를 정리했습니다.',
    comments: 21, likes: 29, views: 388, mediaCount: 1,
  },
]

export const communityPosts: CommunityPost[] = exampleCommunityPosts.map(post => ({ ...post, is_example: true }))

export const deals = [
  { id: 'ssd', discount: '-27%', badge: '무료배송', title: 'NVMe SSD 2TB 고성능 모델 특가', price: '129,000원', note: '역대가 근접', stats: '좋아요 218 · 댓글 64', time: '12분 전' },
  { id: 'ram', discount: '-31%', badge: '쿠폰', title: 'DDR5 6000 32GB 메모리 패키지', price: '98,500원', note: '평균가 -18%', stats: '좋아요 172 · 댓글 38', time: '34분 전' },
  { id: 'monitor', discount: '-22%', badge: '카드할인', title: '27인치 QHD 180Hz 게이밍 모니터', price: '249,000원', note: '배송 포함', stats: '좋아요 144 · 댓글 51', time: '1시간 전' },
  { id: 'power', discount: '-18%', badge: 'PC부품', title: '750W 골드 풀모듈러 파워서플라이', price: '109,000원', note: '회원 추천', stats: '좋아요 98 · 댓글 27', time: '2시간 전' },
  { id: 'keyboard', discount: '-25%', badge: '주변기기', title: '저소음 기계식 키보드 텐키리스', price: '79,900원', note: '한정 수량', stats: '좋아요 87 · 댓글 22', time: '3시간 전' },
  { id: 'cooler', discount: '-20%', badge: '종료 임박', title: '듀얼타워 공랭 CPU 쿨러 패키지', price: '45,000원', note: '오늘 종료', stats: '좋아요 76 · 댓글 19', time: '4시간 전' },
]

export const productCatalog = [
  { id: 'mouse-1', kind: '마우스', maker: 'TrueFit Lab', name: 'AeroFit M8 Wireless', detail: '58g · 무선 · 26K 센서', options: [] },
  { id: 'mouse-2', kind: '마우스', maker: 'TrueFit Lab', name: 'Aero M55', detail: '55g · 2.4GHz · USB-C', options: [] },
  { id: 'keyboard-1', kind: '키보드', maker: 'TrueFit Lab', name: 'QuietType TKL 87', detail: '텐키리스 · 무선 · 저소음축', options: ['저소음 적축', '갈축'] },
  { id: 'keyboard-2', kind: '키보드', maker: 'TrueFit Lab', name: 'Slate 75', detail: '75% · 가스켓 · 무선', options: ['45g 리니어', '저소음 적축', '갈축'] },
  { id: 'monitor-1', kind: '모니터', maker: 'TrueFit Lab', name: 'ViewEdge Q27 180', detail: 'QHD · 180Hz · 27인치', options: [] },
  { id: 'monitor-2', kind: '모니터', maker: 'TrueFit Lab', name: 'ViewEdge 4K 27', detail: '4K · 144Hz · 27인치', options: [] },
  { id: 'speaker-1', kind: '스피커', maker: 'TrueFit Lab', name: 'DeskSound S2', detail: '2채널 · USB-C · 블루투스', options: [] },
]
