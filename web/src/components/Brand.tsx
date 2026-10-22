import truefitLogo from '../assets/truefit-logo.png'
import truefitLogoLight from '../assets/truefit-logo-light.png'
import { useTheme } from '../state/theme'

// TrueFit 로고 이미지. 다크 화면에는 밝은 글자, 라이트 화면에는 어두운 글자 버전을 쓴다.
export default function Brand() {
  const { theme } = useTheme()
  return (
    <span className="tf-brand" aria-hidden="true">
      <img src={theme === 'light' ? truefitLogoLight : truefitLogo} alt="" />
    </span>
  )
}
