// 지난 견적 이어가기 제안(A1)에 칩 대신 글로 답했을 때 — "이어서 해줘"·"새로 시작할게요".
// 예전에는 이 말이 조건 대화로 가서 지난 견적을 불러오지 않았다(10/15 QA #65). 조건 대화 모델에는 이어가기 도구가 없다.
export type OfferReply = 'resume' | 'fresh' | null

const RESUME = /이어(?:서|가|하|할)|계속\s*(?:해|하|할|진행)|불러\s*(?:와|줘|오)|그대로\s*(?:해|할|진행|써|쓸)/
const FRESH = /새로|처음부터|다시\s*시작/
const NEGATED = /말고|하지\s*마|안\s*(?:해|할)|싫/
const YES = /^(?:응+|ㅇㅇ+|네+|넵|넹|예|그래요?|좋아요?|좋습니다|ㅇㅋ|오케이|ok)[.!~]*$/i
const NO = /^(?:아니(?:요|오)?|아뇨|ㄴㄴ|싫어요?)[.!~]*$/
// 조건을 함께 말한 문장("이어서 하되 예산은 200만원으로")은 조건 대화에 맡긴다 — 이어가기로 가로채면 뒷말이 사라진다.
// 길이(공백 빼고 15자)와 숫자로 가른다. "지난 견적 이어서 할게요"는 10자.
const MAX_LENGTH = 15

/** `onlyQuestion`: 제안이 마지막 질문일 때만(뒤에 선호 되묻기가 없을 때) "응"·"아니요" 한마디를 이 제안의 답으로 본다. */
export function readOfferReply(text: string, onlyQuestion: boolean): OfferReply {
  const t = text.trim()
  if (!t || t.replace(/\s/g, '').length > MAX_LENGTH || /\d/.test(t)) return null
  if (FRESH.test(t)) return 'fresh'
  if (RESUME.test(t)) return NEGATED.test(t) ? 'fresh' : 'resume'
  if (onlyQuestion && YES.test(t)) return 'resume'
  if (onlyQuestion && NO.test(t)) return 'fresh'
  return null
}
