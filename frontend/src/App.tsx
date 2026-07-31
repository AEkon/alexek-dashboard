import React, { useCallback, useEffect, useState } from 'react'
import Jobs from './Jobs'
import Forum from './Forum'

type View = 'jobs' | 'forum'

type InboxCounts = {
  jobsNew: number
  forumNew: number
}

const App: React.FC = () => {
  const [currentView, setCurrentView] = useState<View>('jobs')
  const [counts, setCounts] = useState<InboxCounts>({ jobsNew: 0, forumNew: 0 })

  const refreshCounts = useCallback(async () => {
    try {
      const [jobsRes, forumRes] = await Promise.all([
        fetch('/api/jobs/stats'),
        fetch('/api/forum/stats'),
      ])
      const jobs = jobsRes.ok ? await jobsRes.json() : null
      const forum = forumRes.ok ? await forumRes.json() : null
      setCounts({
        jobsNew: Number(jobs?.by_status?.new || 0),
        forumNew: Number(forum?.by_status?.new || 0),
      })
    } catch {
      // ignore — badges are advisory
    }
  }, [])

  useEffect(() => {
    refreshCounts()
    const id = window.setInterval(refreshCounts, 60_000)
    return () => window.clearInterval(id)
  }, [refreshCounts])

  // Re-fetch when switching views so badges stay fresh after triage
  useEffect(() => {
    refreshCounts()
  }, [currentView, refreshCounts])

  return (
    <div className="app">
      <header className="app-header">
        <h1>Dashboard</h1>
        <nav className="main-nav" role="tablist" aria-label="Dashboard sections">
          <button
            type="button"
            role="tab"
            aria-selected={currentView === 'jobs'}
            className={`nav-button ${currentView === 'jobs' ? 'active' : ''}`}
            onClick={() => setCurrentView('jobs')}
          >
            <span className="nav-button-label">Jobs</span>
            <span
              className={`nav-badge ${counts.jobsNew > 0 ? 'nav-badge--hot' : ''}`}
              aria-label={`${counts.jobsNew} new jobs`}
            >
              {counts.jobsNew > 0 ? `${counts.jobsNew} new` : 'Clear'}
            </span>
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={currentView === 'forum'}
            className={`nav-button ${currentView === 'forum' ? 'active' : ''}`}
            onClick={() => setCurrentView('forum')}
          >
            <span className="nav-button-label">Forum</span>
            <span
              className={`nav-badge ${counts.forumNew > 0 ? 'nav-badge--hot' : ''}`}
              aria-label={`${counts.forumNew} new questions`}
            >
              {counts.forumNew > 0 ? `${counts.forumNew} new` : 'Clear'}
            </span>
          </button>
        </nav>
      </header>
      <main className="app-main">
        <section className="dashboard-section">
          {currentView === 'jobs' ? (
            <Jobs onInboxChange={refreshCounts} />
          ) : (
            <Forum onInboxChange={refreshCounts} />
          )}
        </section>
      </main>
    </div>
  )
}

export default App
