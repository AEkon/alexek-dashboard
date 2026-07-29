import { useState, useEffect } from 'react'
import { buildProposalStub } from './proposal'

// Callers: main.tsx. API: GET/PATCH /api/jobs, /api/jobs/stats.
// User: "Implement the plan as specified" (Apply assist).

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

type JobStatus = 'new' | 'interested' | 'applied' | 'skipped' | 'won' | 'lost' | 'no_reply'
type TabKey = 'new' | 'interested' | 'applied' | 'closed' | 'skipped'
type OutcomeFilter = 'won' | 'lost' | 'no_reply'

const STATUS_TABS: { key: TabKey; label: string }[] = [
  { key: 'new', label: 'New' },
  { key: 'interested', label: 'Interested' },
  { key: 'applied', label: 'Applied' },
  { key: 'closed', label: 'Closed' },
  { key: 'skipped', label: 'Skipped' },
]

const OUTCOME_PILLS: { key: OutcomeFilter; label: string }[] = [
  { key: 'won', label: 'Won' },
  { key: 'lost', label: 'Lost' },
  { key: 'no_reply', label: 'No reply' },
]

const CLOSED_STATUSES: OutcomeFilter[] = ['won', 'lost', 'no_reply']

function tabCount(stats: JobsStats | null, key: TabKey): number {
  if (!stats) return 0
  if (key === 'closed') {
    return CLOSED_STATUSES.reduce((sum, s) => sum + (stats.by_status[s] || 0), 0)
  }
  return stats.by_status[key] || 0
}

function outcomeLabel(status: string): string {
  if (status === 'no_reply') return 'No reply'
  if (status === 'won') return 'Won'
  if (status === 'lost') return 'Lost'
  return status
}

function App() {
  const [jobs, setJobs] = useState<Job[]>([])
  const [stats, setStats] = useState<JobsStats | null>(null)
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [statusFilter, setStatusFilter] = useState<TabKey>('new')
  const [outcomeFilter, setOutcomeFilter] = useState<OutcomeFilter | null>(null)

  const [jobTypeFilter, setJobTypeFilter] = useState<string | null>(null)
  const [sourceFilter, setSourceFilter] = useState<string | null>(null)
  const [searchQuery, setSearchQuery] = useState('')

  const [sortKey, setSortKey] = useState('priority_score')
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc')

  const [applyJob, setApplyJob] = useState<Job | null>(null)
  const [proposalText, setProposalText] = useState('')
  const [copied, setCopied] = useState(false)
  const [markingApplied, setMarkingApplied] = useState(false)

  useEffect(() => {
    fetchJobs()
    fetchStats()
  }, [statusFilter, outcomeFilter, jobTypeFilter, sourceFilter])

  const fetchJobs = async () => {
    try {
      setLoading(true)
      setError(null)

      const params = new URLSearchParams()
      params.append('status', statusFilter)
      if (statusFilter === 'closed' && outcomeFilter) params.append('outcome', outcomeFilter)
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

  const setJobStatus = async (jobId: number, status: JobStatus) => {
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
      if (applyJob?.id === jobId) closeApplyDrawer()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to update job')
    }
  }

  const openApplyDrawer = (job: Job) => {
    setApplyJob(job)
    setProposalText(buildProposalStub(job))
    setCopied(false)
  }

  const closeApplyDrawer = () => {
    setApplyJob(null)
    setProposalText('')
    setCopied(false)
    setMarkingApplied(false)
  }

  const copyProposal = async () => {
    try {
      await navigator.clipboard.writeText(proposalText)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1600)
    } catch {
      setError('Could not copy to clipboard')
    }
  }

  const markAppliedFromDrawer = async () => {
    if (!applyJob) return
    setMarkingApplied(true)
    await setJobStatus(applyJob.id, 'applied')
    setMarkingApplied(false)
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
    switch (job.status as JobStatus) {
      case 'new':
        return (
          <div className="triage-group" role="group" aria-label="Triage">
            <button type="button" className="triage-button triage-primary" onClick={() => openApplyDrawer(job)}>Apply</button>
            <button type="button" className="triage-button triage-secondary" onClick={() => setJobStatus(job.id, 'interested')}>Shortlist</button>
            <button type="button" className="triage-button triage-ghost" onClick={() => setJobStatus(job.id, 'skipped')}>Skip</button>
          </div>
        )
      case 'interested':
        return (
          <div className="triage-group" role="group" aria-label="Triage">
            <button type="button" className="triage-button triage-primary" onClick={() => openApplyDrawer(job)}>Apply</button>
            <button type="button" className="triage-button triage-ghost" onClick={() => setJobStatus(job.id, 'skipped')}>Skip</button>
            <button type="button" className="triage-button triage-ghost" onClick={() => setJobStatus(job.id, 'new')}>Undo</button>
          </div>
        )
      case 'applied':
        return (
          <div className="triage-group" role="group" aria-label="Outcome">
            <button type="button" className="triage-button triage-primary" onClick={() => setJobStatus(job.id, 'won')}>Won</button>
            <button type="button" className="triage-button triage-secondary" onClick={() => setJobStatus(job.id, 'lost')}>Lost</button>
            <button type="button" className="triage-button triage-secondary" onClick={() => setJobStatus(job.id, 'no_reply')}>No reply</button>
            <button type="button" className="triage-button triage-ghost" onClick={() => setJobStatus(job.id, 'interested')}>Back</button>
            <button type="button" className="triage-button triage-ghost" onClick={() => setJobStatus(job.id, 'skipped')}>Skip</button>
          </div>
        )
      case 'won':
      case 'lost':
      case 'no_reply':
        return (
          <div className="triage-group" role="group" aria-label="Outcome">
            <button type="button" className="triage-button triage-secondary" onClick={() => setJobStatus(job.id, 'applied')}>Back to Applied</button>
          </div>
        )
      case 'skipped':
        return (
          <div className="triage-group" role="group" aria-label="Triage">
            <button type="button" className="triage-button triage-secondary" onClick={() => setJobStatus(job.id, 'new')}>Restore</button>
          </div>
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

      <div className="inbox-bar">
        <div className="status-tabs" role="tablist" aria-label="Job status">
          {STATUS_TABS.map(tab => {
            const count = tabCount(stats, tab.key)
            const active = statusFilter === tab.key
            return (
              <button
                key={tab.key}
                type="button"
                role="tab"
                aria-selected={active}
                className={`status-tab status-tab--${tab.key} ${active ? 'active' : ''}`}
                onClick={() => {
                  setStatusFilter(tab.key)
                  if (tab.key !== 'closed') setOutcomeFilter(null)
                }}
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

        {statusFilter === 'closed' && (
          <div className="filter-pills">
            {OUTCOME_PILLS.map(pill => (
              <button
                key={pill.key}
                type="button"
                className={`filter-pill ${outcomeFilter === pill.key ? 'active' : ''}`}
                onClick={() => setOutcomeFilter(outcomeFilter === pill.key ? null : pill.key)}
              >
                {pill.label}
                <span className="filter-pill-count">{stats?.by_status[pill.key] || 0}</span>
              </button>
            ))}
          </div>
        )}

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
                <th className="actions-col">Triage</th>
              </tr>
            </thead>
            <tbody>
              {filteredJobs.map(job => (
                <tr key={job.id} className={applyJob?.id === job.id ? 'row-active' : undefined}>
                  <td className="score-cell">
                    {job.priority_score != null ? (
                      <span className="score">{job.priority_score}</span>
                    ) : (
                      <span className="rate-unknown">—</span>
                    )}
                  </td>
                  <td className="job-title">
                    <div className="job-title-row">
                      <span>{job.title}</span>
                      {CLOSED_STATUSES.includes(job.status as OutcomeFilter) && (
                        <span className={`outcome-badge outcome-badge--${job.status}`}>
                          {outcomeLabel(job.status)}
                        </span>
                      )}
                    </div>
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
                  <td className="actions-cell">
                    <div className="row-actions">
                      <a
                        href={job.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="view-link"
                      >
                        Open
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

      {applyJob && (
        <>
          <button
            type="button"
            className="apply-drawer-backdrop"
            aria-label="Close apply panel"
            onClick={closeApplyDrawer}
          />
          <aside className="apply-drawer" role="dialog" aria-modal="true" aria-labelledby="apply-drawer-title">
            <div className="apply-drawer-header">
              <div>
                <p className="apply-drawer-kicker">Apply assist</p>
                <h2 id="apply-drawer-title">{applyJob.title}</h2>
              </div>
              <button type="button" className="apply-drawer-close" onClick={closeApplyDrawer} aria-label="Close">
                ×
              </button>
            </div>

            <div className="apply-drawer-meta">
              <span>Score {applyJob.priority_score ?? '—'}</span>
              <span>{formatBudget(applyJob)}</span>
              <span>{effortLabel(applyJob.effort_score)}</span>
              <span>{applyJob.source}</span>
            </div>

            <label className="apply-drawer-label" htmlFor="proposal-text">
              Proposal stub
            </label>
            <textarea
              id="proposal-text"
              className="apply-drawer-textarea"
              value={proposalText}
              onChange={(e) => setProposalText(e.target.value)}
              rows={12}
            />

            <div className="apply-drawer-actions">
              <button type="button" className="triage-button triage-secondary" onClick={copyProposal}>
                {copied ? 'Copied' : 'Copy'}
              </button>
              <a
                href={applyJob.url}
                target="_blank"
                rel="noopener noreferrer"
                className="triage-button triage-secondary apply-drawer-open"
              >
                Open listing
              </a>
              <button
                type="button"
                className="triage-button triage-primary"
                onClick={markAppliedFromDrawer}
                disabled={markingApplied}
              >
                {markingApplied ? 'Saving…' : 'Mark applied'}
              </button>
              <button type="button" className="triage-button triage-ghost" onClick={closeApplyDrawer}>
                Close
              </button>
            </div>
          </aside>
        </>
      )}
    </div>
  )
}

export default App
