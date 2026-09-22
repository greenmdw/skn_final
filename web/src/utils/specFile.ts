// 견적 점검의 사양 파일에서 부품별 문구를 뽑는다. 실서버는 자유 문장·이미지까지 LLM으로 추출하지만
// (src/agent/spec_extraction_agent.py), 그게 꺼져 있거나 목업 모드일 때를 대비해 여기서도 같은
// key: value 규칙 기반 파서를 하나 둔다 — 백엔드의 규칙 파서(src/engine/spec_text.py)와 같은 키·형식이다.
const SPEC_KEY_MAP: Record<string, string> = {
  cpu: 'CPU', 프로세서: 'CPU',
  gpu: 'GPU', 그래픽카드: 'GPU', 그래픽: 'GPU',
  ram: 'RAM', 메모리: 'RAM',
  메인보드: '메인보드', mainboard: '메인보드', motherboard: '메인보드',
  저장장치: '저장장치', ssd: '저장장치', storage: '저장장치',
  파워: '파워', psu: '파워', power: '파워',
  케이스: '케이스', case: '케이스',
  쿨러: '쿨러', cooler: '쿨러',
}
const SPEC_LINE = /^\s*(cpu|프로세서|gpu|그래픽카드|그래픽|ram|메모리|메인보드|mainboard|motherboard|저장장치|ssd|storage|파워|psu|power|케이스|case|쿨러|cooler)\s*[:=]\s*(.+?)\s*$/gim

export const SPEC_FILE_ACCEPT = '.txt,.csv,.md,.json,.log,.nfo,.xml'
export const SPEC_FILE_MAX_BYTES = 1_000_000    // 텍스트 파일 크기 상한
export const SPEC_TEXT_MAX_CHARS = 20_000       // 서버(_MAX_TEXT_CHARS)와 같은, 실제 보낼 글자 수 상한

export const SPEC_IMAGE_ACCEPT = '.png,.jpg,.jpeg,.webp'
export const SPEC_IMAGE_MAX_BYTES = 5_000_000   // 서버(_MAX_IMAGE_DATA_URL_CHARS)와 맞춘 원본 이미지 크기 상한
const IMAGE_EXT = /\.(png|jpe?g|webp)$/i

export function isImageFile(file: File): boolean {
  return file.type.startsWith('image/') || IMAGE_EXT.test(file.name)
}

/** 이미지를 "data:image/png;base64,..." 형식으로 읽는다 — 서버 image_data_url이 그대로 기대하는 형식. */
export function readImageAsDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result))
    reader.onerror = () => reject(reader.error ?? new Error('파일을 읽지 못했습니다.'))
    reader.readAsDataURL(file)
  })
}

export function parseSpecFileText(content: string): Record<string, string> {
  const specs: Record<string, string> = {}
  for (const match of content.matchAll(SPEC_LINE)) {
    const slot = SPEC_KEY_MAP[match[1].toLowerCase()]
    const value = match[2].trim()
    if (slot && value) specs[slot] = value
  }
  return specs
}
