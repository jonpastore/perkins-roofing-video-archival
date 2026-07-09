import { Component, StrictMode } from 'react'
import type { ReactNode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'

// Last-resort boundary: a render crash anywhere below unmounts React's tree and
// leaves a blank page (this bit us in prod — dashboard shape mismatch, 2026-07-09).
// Show the error instead so failures are diagnosable from a screenshot.
class RootErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state = { error: null as Error | null }
  static getDerivedStateFromError(error: Error) {
    return { error }
  }
  render() {
    if (this.state.error) {
      return (
        <div style={{ padding: 32, fontFamily: 'system-ui, sans-serif', maxWidth: 720, margin: '0 auto' }}>
          <h2 style={{ color: '#0f2a43' }}>Something broke rendering this page</h2>
          <p style={{ color: '#555' }}>
            Reload to try again. If it persists, send this to support:
          </p>
          <pre style={{ background: '#f6f6f6', padding: 12, borderRadius: 6, whiteSpace: 'pre-wrap', fontSize: 12 }}>
            {String(this.state.error?.stack || this.state.error)}
          </pre>
          <button onClick={() => window.location.reload()} style={{ padding: '8px 16px', cursor: 'pointer' }}>
            Reload
          </button>
        </div>
      )
    }
    return this.props.children
  }
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <RootErrorBoundary>
      <App />
    </RootErrorBoundary>
  </StrictMode>,
)
