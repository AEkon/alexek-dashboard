import { useState, useEffect, useCallback } from 'react'

// Callers: App.tsx. API: GET/PATCH/DELETE /api/jobs, POST /api/refresh/jobs, GET /api/jobs/stats.
// Schema: jobs (source, source_id, title, description, url, status, job_type, earnings_usd, ...)

interface Job {
  id: number
  source: string
  source_id: string
  title: string
  description: string
  url: string
  status: string
  job_type: string
  earnings_usd: number | null
  priority_score: number | null
  posted_date: string
  created_at: string
  updated_at: string
}

interface JobStats {
  by_status: Record<string, number>
  by_source: Record<string, number>
  by_type: Record<string, number>
  recent_7days: number
  weekly_revenue_usd: number
}

type JobStatus = 'new' | 'interested' | 'applied' | 'skipped' | 'archived' | 'gone' | 'won' | 'lost' | 'no_reply' | 'closed'

const STATUS_TABS: { key: JobStatus; label: string }[] = [
  { key: 'new', label: 'New' },
  { key: 'interested', label: 'Interested' },
  { key: 'applied', label: 'Applied' },
  { key: 'closed', label: 'Closed' },
]

const EMPTY_COPY: Record<JobStatus, string> = {
  new: 'No new jobs. Jobs are checked every 30 minutes.',
  interested: 'No jobs marked as interested.',
  applied: 'No applied jobs.',
  skipped: 'No skipped jobs.',
  archived: 'No archived jobs.',
  gone: 'No gone jobs.',
  won: 'No won jobs.',
  lost: 'No lost jobs.',
  no_reply: 'No jobs with no reply.',
  closed: 'No closed jobs.',
}

function formatRelativeTime(iso: string | null): string {
  if (!iso) return 'Unknown'
  const then = new Date(iso).getTime()
  const now = Date.now()
  const diff = now - then

  if (diff < 60000) return 'Just now'
  if (diff < 3600000) return `${Math.floor(diff / 60000)}m ago`
  if (diff < 86400000) return `${Math.floor(diff / 3600000)}h ago`
  if (diff < 604800000) return `${Math.floor(diff / 86400000)}d ago`
  return new Date(iso).toLocaleDateString()
}

export default function Jobs() {
  const [jobs, setJobs] = useState<Job[]>([])
  const [stats, setStats] = useState<JobStats | null>(null)
  const [activeTab, setActiveTab] = useState<JobStatus>('new')
  const [refreshing, setRefreshing] = useState(false)
  const [expandedId, setExpandedId] = useState<number | null>(null)
  const [searchQuery, setSearchQuery] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  const fetchJobs = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await fetch(`/api/jobs?status=${activeTab}&limit=50`)
      if (res.ok) {
        const data = await res.json()
        setJobs(data)
      } else {
        setError(`Failed to fetch jobs: ${res.status}`)
      }
    } catch (e) {
      console.error('Failed to fetch jobs:', e)
      setError('Failed to connect to server')
    } finally {
      setLoading(false)
    }
  }, [activeTab])

  const fetchStats = useCallback(async () => {
    try {
      const res = await fetch('/api/jobs/stats')
      if (res.ok) {
        const data = await res.json()
        setStats(data)
      }
    } catch (e) {
      console.error('Failed to fetch stats:', e)
    }
  }, [])

  useEffect(() => {
    fetchJobs()
    fetchStats()
  }, [fetchJobs, fetchStats])

  const handleRefresh = async () => {
    setRefreshing(true)
    try {
      await fetch('/api/refresh/jobs', { method: 'POST' })
      await fetchJobs()
      await fetchStats()
    } catch (e) {
      console.error('Refresh failed:', e)
    } finally {
      setRefreshing(false)
    }
  }

  const handleStatusUpdate = async (id: number, updates: Partial<Job>) => {
    try {
      const res = await fetch(`/api/jobs/${id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(updates),
      })
      if (res.ok) {
        await fetchJobs()
        await fetchStats()
      }
    } catch (e) {
      console.error('Status update failed:', e)
    }
  }

  const handleArchive = async (id: number) => {
    await handleStatusUpdate(id, { status: 'archived' })
  }

  const filteredJobs = jobs.filter(job =>
    job.title.toLowerCase().includes(searchQuery.toLowerCase()) ||
    job.description.toLowerCase().includes(searchQuery.toLowerCase())
  )

  const tabCount = (key: JobStatus) => {
    if (key === 'closed') {
      return (stats?.by_status['won'] || 0) + (stats?.by_status['lost'] || 0) + (stats?.by_status['no_reply'] || 0)
    }
    return stats?.by_status[key] || 0
  }

  return (
    <div className="jobs-section">
      <div className="section-divider">
        <h3 className="section-title">Job Opportunities</h3>
        <p className="section-description">Squarespace-related job listings and freelance opportunities</p>
      </div>

      <header className="section-header">
        <h2>Jobs Board</h2>
        <button
          className="refresh-button"
          onClick={handleRefresh}
          disabled={refreshing}
        >
          {refreshing ? '↻' : '⟳'} Refresh
        </button>
      </header>

      <div className="inbox-bar">
        <div className="status-tabs" role="tablist" aria-label="Job status">
          {STATUS_TABS.map(tab => {
            const count = tabCount(tab.key as JobStatus)
            const active = activeTab === tab.key
            return (
              <button
                key={tab.key}
                type="button"
                role="tab"
                aria-selected={active}
                className={`status-tab status-tab--${tab.key} ${active ? 'active' : ''}`}
                onClick={() => setActiveTab(tab.key as JobStatus)}
              >
                <span className="status-tab-label">{tab.label}</span>
                <span className="status-tab-count">{count}</span>
              </button>
            )
          })}
        </div>
      </div>

      <div className="controls">
        <input
          type="text"
          placeholder="Search jobs..."
          className="search-input"
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
        />
      </div>

      {error && (
        <div className="error-message">
          {error}
        </div>
      )}

      {loading ? (
        <div className="loading">Loading jobs...</div>
      ) : filteredJobs.length === 0 ? (
        <div className="no-results">
          <p>{EMPTY_COPY[activeTab] || 'No jobs found.'}</p>
        </div>
      ) : (
        <div className="jobs-table-container">
          <table className="jobs-table">
            <thead>
              <tr>
                <th onClick={() => {/* TODO: Add sorting */}} className="sortable">
                  Title {'▲'}
                </th>
                <th>Source</th>
                <th>Type</th>
                <th>Earnings</th>
                <th>Posted</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {filteredJobs.map(job => (
                <tr
                  key={job.id}
                  className={expandedId === job.id ? 'focused' : ''}
                  onClick={() => setExpandedId(expandedId === job.id ? null : job.id)}
                >
                  <td className="title-cell">
                    <div className="job-title">{job.title}</div>
                    {expandedId === job.id && (
                      <div className="job-description">
                        <p>{job.description}</p>
                      </div>
                    )}
                  </td>
                  <td>
                    <span className="source-badge">{job.source}</span>
                  </td>
                  <td>
                    <span className="type-badge">{job.job_type || 'Unknown'}</span>
                  </td>
                  <td>
                    {job.earnings_usd ? `$${job.earnings_usd}` : '—'}
                  </td>
                  <td>{formatRelativeTime(job.posted_date)}</td>
                  <td className="row-actions" onClick={(e) => e.stopPropagation()}>
                    <a href={job.url} target="_blank" rel="noopener noreferrer" className="view-link">
                      Open
                    </a>
                    {job.status === 'new' && (
                      <>
                        <button
                          className="triage-button triage-secondary"
                          onClick={() => handleStatusUpdate(job.id, { status: 'interested' })}
                        >
                          Interested
                        </button>
                        <button
                          className="triage-button triage-ghost"
                          onClick={() => handleArchive(job.id)}
                        >
                          Skip
                        </button>
                      </>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}