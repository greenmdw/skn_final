import { Component, type ErrorInfo, type ReactNode } from 'react'

/** 화면 안에서 렌더링 오류가 나도 앱 전체가 흰 화면이 되지 않게 막는다 — 오류 안내와 새로고침 버튼을 보인다. */
export default class CheckBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false }

  static getDerivedStateFromError() { return { failed: true } }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('받은 견적 점검 화면 오류', error, info.componentStack)
  }

  render() {
    if (!this.state.failed) return this.props.children
    return (
      <section className="c2-card warn" role="alert">
        <strong>화면을 그리다 문제가 생겼어요.</strong>
        <p className="c2-sub">입력한 내용은 서버에 저장돼 있어요. 새로고침하면 이어서 할 수 있어요.</p>
        <div className="c2-actions"><button type="button" className="c2-btn primary" onClick={() => window.location.reload()}>새로고침</button></div>
      </section>
    )
  }
}
