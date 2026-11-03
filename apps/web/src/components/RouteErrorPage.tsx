import { Link, useRouteError } from 'react-router-dom'

export function RouteErrorPage() {
  const error = useRouteError()
  if (import.meta.env.DEV) {
    console.error('Route rendering failed', error)
  }

  return (
    <section className="route-state-card" role="alert">
      <span className="route-state-symbol">!</span>
      <h1>页面暂时无法打开</h1>
      <p>页面暂时无法打开，请稍后重试。</p>
      <div className="route-error-actions">
        <Link className="primary-button link-button" to="/">返回首页</Link>
        <button type="button" className="secondary-button" onClick={() => window.location.reload()}>
          重新加载
        </button>
      </div>
    </section>
  )
}
