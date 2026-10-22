import { Link, type LinkProps } from 'react-router-dom'

/** Keep existing navigation preparation on ordinary clicks; let the browser handle new tabs and windows. */
export default function NavigationLink({ onClick, className = '', ...props }: LinkProps) {
  return <Link {...props} className={`navigation-link ${className}`} onClick={event => {
    if (event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return
    if (onClick) {
      event.preventDefault()
      onClick(event)
    }
  }} />
}
