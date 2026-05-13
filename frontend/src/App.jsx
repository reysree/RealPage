import { useEffect, useState } from 'react'
import './App.css'
import { getBackendHealth } from './api'

function App() {
  const [connection, setConnection] = useState({
    status: 'checking',
    message: 'Checking backend connection...',
  })

  useEffect(() => {
    let cancelled = false

    getBackendHealth()
      .then((health) => {
        if (!cancelled) {
          setConnection({
            status: 'connected',
            message: `Connected to ${health.service}`,
          })
        }
      })
      .catch((error) => {
        if (!cancelled) {
          setConnection({
            status: 'error',
            message: error.message,
          })
        }
      })

    return () => {
      cancelled = true
    }
  }, [])

  return (
    <main className="app-shell">
      <section className="connection-card">
        <p className="eyebrow">RealPage Lumina</p>
        <h1>Frontend to backend connection</h1>
        <p>
          The React app calls the FastAPI health endpoint from the browser using
          CORS.
        </p>
        <div className={`status ${connection.status}`}>
          <span>{connection.status}</span>
          <strong>{connection.message}</strong>
        </div>
      </section>
    </main>
  )
}

export default App
