import { useEffect } from 'react'
import { Navigate, useNavigate, useParams } from 'react-router-dom'
import { checkV2 } from '../../api/checkV2'
import CheckLayout, { CHECK2 } from './CheckLayout'

/** `/check/:id` — 지난 점검을 다시 열 때 가장 알맞은 단계로 보낸다: 분석한 적이 있으면 ③ 종합 평가, 없으면 ② 인식 확인. */
export default function ResumePage() {
  const { id } = useParams()
  const navigate = useNavigate()
  useEffect(() => {
    if (!id) return
    let alive = true
    checkV2.getReview(id)
      .then(() => { if (alive) navigate(`${CHECK2}/${id}/review`, { replace: true }) })
      .catch(() => { if (alive) navigate(`${CHECK2}/${id}/parts`, { replace: true }) })
    return () => { alive = false }
  }, [id, navigate])
  if (!id) return <Navigate to={CHECK2} replace />
  return <CheckLayout current="parts" draftId={id} reachable={[]} chat={false}><p className="c2-note">지난 점검을 불러오는 중…</p></CheckLayout>
}
