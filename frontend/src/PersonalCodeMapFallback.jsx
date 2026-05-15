/**
 * Shown when `frontend/src/personal/CodeMapReview.jsx` is absent (e.g. CI).
 * Your local copy lives in gitignored `src/personal/` — see repo .gitignore.
 */
export default function PersonalCodeMapFallback() {
  return (
    <main className="code-map-fallback">
      <h1>Personal code map</h1>
      <p>
        Add <code>frontend/src/personal/CodeMapReview.jsx</code> (and optional{' '}
        <code>CodeMapReview.css</code>) on your machine. That folder is gitignored so it stays
        local.
      </p>
      <p>
        Then open: <code>{`${window.location.origin}${window.location.pathname}#/personal/code-map`}</code>
      </p>
    </main>
  )
}
