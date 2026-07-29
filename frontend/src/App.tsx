import { useState, useEffect } from 'react'

// Callers: main.tsx. API: GET/PATCH /api/jobs, /api/jobs/stats. Schema: jobs.status.
// User: "Implement the plan as specified" (job triage + lean DB).

interface Job {
  id: number
  source: string
  source_id: string
  title: string
  description: string
  url: string
  posted_date: string
  job_type: string
  rate_min: number | null
  rate_max: number | null
  currency: string
  keyword_matches: string
  status: string
  created_at: string
  updated_at: string
  budget: string | null
  budget_mid_usd: number | null
  effort_score: number | null
  priority_score: number | null
}

interface JobsStats {
  by_status: Record<string, number>
  by_source: Record<string, number>
  by_type: Record<string, number>
  recent_7days: number
}

type TriageStatus = 'new' | 'interested' | 'applied' | 'skipped'

const STATUS_TABS: { key: TriageStatus; label: string }[] = [
  { key: 'new', label: 'New' },
  { key: 'interested', label: 'Interested' },
  { key: 'applied', label: 'Applied' },
  { key: 'skipped', label: 'Skipped' },
]

function App() {
  const [jobs, setJobs] = useState<Job[]>([])
  const [stats, setStats] = useState<JobsStats | null>(null)
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [statusFilter, setStatusFilter] = useState<TriageStatus>('new')

  const [jobTypeFilter, setJobTypeFilter] = useState<string | null>(null)
  const [sourceFilter, setSourceFilter] = useState<string | null>(null)
  const [searchQuery, setSearchQuery] = useState('')

  const [sortKey, setSortKey] = useState('priority_score')
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc')

  useEffect(() => {
    fetchJobs()
    fetchStats()
  }, [statusFilter, jobTypeFilter, sourceFilter])

  const fetchJobs = async () => {
    try {
      setLoading(true)
      setError(null)

      const params = new URLSearchParams()
      params.append('status', statusFilter)
      if (jobTypeFilter) params.append('job_type', jobTypeFilter)
      if (sourceFilter) params.append('source', sourceFilter)
      params.append('limit', '50')

      const response = await fetch(`/api/jobs?${params.toString()}`, { credentials: 'same-origin' })
      if (response.status === 401) {
        window.location.href = '/login'
        return
      }
      if (!response.ok) throw new Error('Failed to fetch jobs')

      const data = await response.json()
      setJobs(data)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error')
    } finally {
      setLoading(false)
    }
  }

  const fetchStats = async () => {
    try {
      const response = await fetch('/api/jobs/stats', { credentials: 'same-origin' })
      if (!response.ok) throw new Error('Failed to fetch stats')

      const data = await response.json()
      setStats(data)
    } catch (err) {
      console.error('Failed to fetch stats:', err)
    }
  }

  const setJobStatus = async (jobId: number, status: TriageStatus) => {
    try {
      const response = await fetch(`/api/jobs/${jobId}`, {
        method: 'PATCH',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status }),
      })
      if (response.status === 401) {
        window.location.href = '/login'
        return
      }
      if (!response.ok) throw new Error('Failed to update job')
      setJobs(prev => prev.filter(j => j.id !== jobId))
      fetchStats()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to update job')
    }
  }

  const handleRefresh = async () => {
    setRefreshing(true)
    try {
      const refreshRes = await fetch('/api/refresh/jobs', { method: 'POST', credentials: 'same-origin' })
      if (refreshRes.status === 401) {
        window.location.href = '/login'
        return
      }

      setTimeout(() => {
        fetchJobs()
        fetchStats()
        setRefreshing(false)
      }, 3000)
    } catch (err) {
      setError('Failed to refresh jobs')
      setRefreshing(false)
    }
  }

  const toggleSort = (key: string) => {
    if (sortKey === key) {
      setSortDir(sortDir === 'asc' ? 'desc' : 'asc')
    } else {
      setSortKey(key)
      setSortDir(['priority_score', 'budget_mid_usd', 'effort_score', 'rate_min', 'posted_date'].includes(key) ? 'desc' : 'asc')
    }
  }

  const formatBudget = (job: Job) => {
    if (job.budget) return job.budget
    if (job.rate_min != null && job.rate_max != null && job.rate_min !== job.rate_max) {
      return `${job.currency === 'GBP' ? '£' : job.currency === 'EUR' ? '€' : '$'}${job.rate_min}-${job.rate_max}`
    }
    if (job.rate_min != null) {
      return `${job.currency === 'GBP' ? '£' : job.currency === 'EUR' ? '€' : '$'}${job.rate_min}`
    }
    return '—'
  }

  const effortLabel = (score: number | null) => {
    if (score == null) return '—'
    if (score <= 3) return `${score} low`
    if (score <= 6) return `${score} mid`
    return `${score} high`
  }

  const triageActions = (job: Job) => {
    switch (job.status as TriageStatus) {
      case 'new':
        return (
          <>
            <button type="button" className="triage-button" onClick={() => setJobStatus(job.id, 'interested')}>Interested</button>
            <button type="button" className="triage-button" onClick={() => setJobStatus(job.id, 'applied')}>Applied</button>
            <button type="button" className="triage-button triage-skip" onClick={() => setJobStatus(job.id, 'skipped')}>Skip</button>
          </>
        )
      case 'interested':
        return (
          <>
            <button type="button" className="triage-button" onClick={() => setJobStatus(job.id, 'applied')}>Applied</button>
            <button type="button" className="triage-button triage-skip" onClick={() => setJobStatus(job.id, 'skipped')}>Skip</button>
            <button type="button" className="triage-button triage-muted" onClick={() => setJobStatus(job.id, 'new')}>Back to New</button>
          </>
        )
      case 'applied':
        return (
          <>
            <button type="button" className="triage-button triage-skip" onClick={() => setJobStatus(job.id, 'skipped')}>Skip</button>
            <button type="button" className="triage-button triage-muted" onClick={() => setJobStatus(job.id, 'interested')}>Back to Interested</button>
          </>
        )
      case 'skipped':
        return (
          <button type="button" className="triage-button" onClick={() => setJobStatus(job.id, 'new')}>Restore</button>
        )
      default:
        return null
    }
  }

  const filteredJobs = jobs
    .filter(job => {
      if (searchQuery) {
        const query = searchQuery.toLowerCase()
        return (
          job.title.toLowerCase().includes(query) ||
          (job.description || '').toLowerCase().includes(query) ||
          (job.keyword_matches || '').toLowerCase().includes(query)
        )
      }
      return true
    })
    .sort((a, b) => {
      const aValue = a[sortKey as keyof Job]
      const bValue = b[sortKey as keyof Job]

      if (aValue === null) return 1
      if (bValue === null) return -1
      if (aValue === bValue) return 0

      const comparison = aValue < bValue ? -1 : 1
      return sortDir === 'asc' ? comparison : -comparison
    })

  const jobTypes = [...new Set(jobs.map(j => j.job_type).filter(Boolean))]
  const sources = [...new Set(jobs.map(j => j.source).filter(Boolean))]

  return (
    <div className="dashboard">
      <header className="dashboard-header">
        <h1>Squarespace Job Monitor</h1>
        <div className="header-actions">
          <button
            className="refresh-button"
            onClick={handleRefresh}
            disabled={refreshing}
          >
            {refreshing ? '↻' : '⟳'} Refresh
          </button>
          <button
            className="logout-button"
            onClick={async () => {
              await fetch('/api/logout', { method: 'POST', credentials: 'same-origin' })
              window.location.href = '/login'
            }}
          >
            Sign out
          </button>
        </div>
      </header>

      {stats && (
        <div className="stats-row">
          <div className="stat-card">
            <div className="stat-value">{stats.by_status.new || 0}</div>
            <div className="stat-label">New</div>
          </div>
          <div className="stat-card">
            <div className="stat-value">{stats.by_status.interested || 0}</div>
            <div className="stat-label">Interested</div>
          </div>
          <div className="stat-card">
            <div className="stat-value">{stats.by_status.applied || 0}</div>
            <div className="stat-label">Applied</div>
          </div>
        </div>
      )}

      <div className="status-tabs">
        {STATUS_TABS.map(tab => (
          <button
            key={tab.key}
            type="button"
            className={`status-tab ${statusFilter === tab.key ? 'active' : ''}`}
            onClick={() => setStatusFilter(tab.key)}
          >
            {tab.label}
            <span className="status-tab-count">{stats?.by_status[tab.key] || 0}</span>
          </button>
        ))}
      </div>

      <div className="controls">
        <input
          type="text"
          placeholder="Search jobs..."
          className="search-input"
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
        />

        {jobTypes.length > 0 && (
          <div className="filter-pills">
            {jobTypes.map(type => (
              <button
                key={type}
                className={`filter-pill ${jobTypeFilter === type ? 'active' : ''}`}
                onClick={() => setJobTypeFilter(jobTypeFilter === type ? null : type)}
              >
                {type}
              </button>
            ))}
          </div>
        )}

        {sources.length > 0 && (
          <div className="filter-pills">
            {sources.map(source => (
              <button
                key={source}
                className={`filter-pill ${sourceFilter === source ? 'active' : ''}`}
                onClick={() => setSourceFilter(sourceFilter === source ? null : source)}
              >
                {source}
              </button>
            ))}
          </div>
        )}
      </div>

      {error && (
        <div className="error-message">
          {error}
        </div>
      )}

      {loading ? (
        <div className="loading">Loading jobs...</div>
      ) : (
        <div className="jobs-table-container">
          <table className="jobs-table">
            <thead>
              <tr>
                <th onClick={() => toggleSort('priority_score')} className="sortable">
                  Score {sortKey === 'priority_score' ? (sortDir === 'asc' ? '▲' : '▼') : ''}
                </th>
                <th onClick={() => toggleSort('title')} className="sortable">
                  Title {sortKey === 'title' ? (sortDir === 'asc' ? '▲' : '▼') : ''}
                </th>
                <th onClick={() => toggleSort('budget_mid_usd')} className="sortable">
                  Budget {sortKey === 'budget_mid_usd' ? (sortDir === 'asc' ? '▲' : '▼') : ''}
                </th>
                <th onClick={() => toggleSort('effort_score')} className="sortable">
                  Effort {sortKey === 'effort_score' ? (sortDir === 'asc' ? '▲' : '▼') : ''}
                </th>
                <th onClick={() => toggleSort('source')} className="sortable">
                  Source {sortKey === 'source' ? (sortDir === 'asc' ? '▲' : '▼') : ''}
                </th>
                <th onClick={() => toggleSort('posted_date')} className="sortable">
                  Posted {sortKey === 'posted_date' ? (sortDir === 'asc' ? '▲' : '▼') : ''}
                </th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody>
              {filteredJobs.map(job => (
                <tr key={job.id}>
                  <td className="score-cell">
                    {job.priority_score != null ? (
                      <span className="score">{job.priority_score}</span>
                    ) : (
                      <span className="rate-unknown">—</span>
                    )}
                  </td>
                  <td className="job-title">
                    <div>{job.title}</div>
                    {job.description && (
                      <div className="job-description">
                        {job.description.substring(0, 100)}
                        {job.description.length > 100 && '...'}
                      </div>
                    )}
                  </td>
                  <td>
                    <span className="rate">{formatBudget(job)}</span>
                  </td>
                  <td>{effortLabel(job.effort_score)}</td>
                  <td>{job.source}</td>
                  <td>{new Date(job.posted_date).toLocaleDateString()}</td>
                  <td>
                    <div className="row-actions">
                      <a
                        href={job.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="apply-button"
                      >
                        View
                      </a>
                      {triageActions(job)}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          {filteredJobs.length === 0 && (
            <div className="no-results">
              {jobs.length === 0
                ? `No ${statusFilter} jobs. Click Refresh to pull Freelancer Squarespace listings.`
                : 'No jobs match your filters or search. Clear them to see all results.'}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

export default App
