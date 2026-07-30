import { useState, useEffect, useCallback } from 'react'
import {
  buildProposalStub,
  detectProposalKind,
  PROPOSAL_KINDS,
  type ProposalKind,
} from './proposal'
import Forum from './Forum'

// Callers: main.tsx. API: GET/PATCH /api/jobs (+ earnings_usd), /api/jobs/stats (+ weekly_revenue_usd).
// Schema: jobs.earnings_usd; stats.weekly_revenue_usd.
// User: "do them all"

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
  earnings_usd: number | null
}

interface JobsStats {
  by_status: Record<string, number>
  by_source: Record<string, number>
  by_type: Record<string, number>
  recent_7days: number
  weekly_revenue_usd?: number
}

type JobStatus = 'new' | 'interested' | 'applied' | 'skipped' | 'won' | 'lost' | 'no_reply'
type TabKey = 'new' | 'interested' | 'applied' | 'closed' | 'skipped' | 'forum'
type OutcomeFilter = 'won' | 'lost' | 'no_reply'
type Density = 'comfortable' | 'compact'

const STATUS_TABS: { key: TabKey; label: string }[] = [
  { key: 'new', label: 'New' },
  { key: 'interested', label: 'Interested' },
  { key: 'applied', label: 'Applied' },
  { key: 'closed', label: 'Closed' },
  { key: 'skipped', label: 'Skipped' },
  { key: 'forum', label: 'Forum' },
]

const OUTCOME_PILLS: { key: OutcomeFilter; label: string }[] = [
  { key: 'won', label: 'Won' },
  { key: 'lost', label: 'Lost' },
  { key: 'no_reply', label: 'No reply' },
]

const CLOSED_STATUSES: OutcomeFilter[] = ['won', 'lost', 'no_reply']

const EMPTY_COPY: Record<TabKey, string> = {
  new: 'No new jobs. Click Refresh to pull Freelancer Squarespace listings.',
  interested: 'Nothing shortlisted yet — Shortlist jobs from New, or press I on a focused row.',
  applied: 'No open bids. Use Apply on New/Interested, then track outcomes here.',
  closed: 'No outcomes yet — mark Applied jobs Won, Lost, or No reply when you hear back.',
  skipped: 'No skipped jobs. Skipped items are purged after a week.',
  forum: 'Forum questions are loaded in the Forum section.',
}

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

function winRate(stats: JobsStats | null): string | null {
  if (!stats) return null
  const won = stats.by_status.won || 0
  const lost = stats.by_status.lost || 0
  const noReply = stats.by_status.no_reply || 0
  const closed = won + lost + noReply
  if (closed === 0) return null
  return `${Math.round((won / closed) * 100)}% win rate`
}

function formatRelativeTime(iso: string | null): string {
  if (!iso) return 'Never scraped'
  const then = new Date(iso).getTime()
  if (Number.isNaN(then)) return 'Unknown'
  const mins = Math.max(0, Math.round((Date.now() - then) / 60000))
  if (mins < 1) return 'Updated just now'
  if (mins < 60) return `Updated ${mins}m ago`
  const hours = Math.round(mins / 60)
  if (hours < 48) return `Updated ${hours}h ago`
  const days = Math.round(hours / 24)
  return `Updated ${days}d ago`
}

function loadDensity(): Density {
  try {
    const v = localStorage.getItem('dashboard-density')
    if (v === 'compact' || v === 'comfortable') return v
  } catch { /* ignore */ }
  return 'comfortable'
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
  const [proposalKind, setProposalKind] = useState<ProposalKind>('general')
  const [proposalText, setProposalText] = useState('')
  const [copied, setCopied] = useState(false)
  const [markingApplied, setMarkingApplied] = useState(false)

  const [focusedIndex, setFocusedIndex] = useState(0)
  const [expandedId, setExpandedId] = useState<number | null>(null)
  const [lastScrapedAt, setLastScrapedAt] = useState<string | null>(null)
  const [density, setDensity] = useState<Density>(loadDensity)

  useEffect(() => {
    fetchJobs()
    fetchStats()
    fetchLastScraped()
  }, [statusFilter, outcomeFilter, jobTypeFilter, sourceFilter])

  useEffect(() => {
    setFocusedIndex(0)
    setExpandedId(null)
  }, [statusFilter, outcomeFilter, jobTypeFilter, sourceFilter, searchQuery])

  useEffect(() => {
    try {
      localStorage.setItem('dashboard-density', density)
    } catch { /* ignore */ }
  }, [density])

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
      setStats(await response.json())
    } catch (err) {
      console.error('Failed to fetch stats:', err)
    }
  }

  const fetchLastScraped = async () => {
    try {
      const response = await fetch('/api/scrape-log', { credentials: 'same-origin' })
      if (!response.ok) return
      const logs: Array<{ scraper: string; status: string; finished_at: string | null; started_at: string }> =
        await response.json()
      const latest = logs.find(l => l.scraper === 'jobs' && l.status === 'success')
      setLastScrapedAt(latest?.finished_at || latest?.started_at || null)
    } catch {
      /* non-critical */
    }
  }

  const closeApplyDrawer = useCallback(() => {
    setApplyJob(null)
    setProposalText('')
    setProposalKind('general')
    setCopied(false)
    setMarkingApplied(false)
  }, [])

  const patchJob = useCallback(async (jobId: number, body: Record<string, unknown>) => {
    const response = await fetch(`/api/jobs/${jobId}`, {
      method: 'PATCH',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    if (response.status === 401) {
      window.location.href = '/login'
      return false
    }
    if (!response.ok) throw new Error('Failed to update job')
    return true
  }, [])

  const setJobStatus = useCallback(async (jobId: number, status: JobStatus) => {
    try {
      const ok = await patchJob(jobId, { status })
      if (!ok) return
      setJobs(prev => prev.filter(j => j.id !== jobId))
      fetchStats()
      setApplyJob(prev => (prev?.id === jobId ? null : prev))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to update job')
    }
  }, [patchJob])

  const markWon = useCallback(async (job: Job) => {
    const hint = job.budget_mid_usd != null ? String(job.budget_mid_usd) : ''
    const raw = window.prompt('Earnings USD for this win? (blank to skip)', hint)
    if (raw === null) return
    const trimmed = raw.trim()
    const payload: Record<string, unknown> = { status: 'won' }
    if (trimmed !== '') {
      const amount = Number(trimmed)
      if (Number.isNaN(amount) || amount < 0) {
        setError('Earnings must be a non-negative number')
        return
      }
      payload.earnings_usd = amount
    }
    try {
      const ok = await patchJob(job.id, payload)
      if (!ok) return
      setJobs(prev => prev.filter(j => j.id !== job.id))
      fetchStats()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to mark won')
    }
  }, [patchJob])

  const openApplyDrawer = useCallback((job: Job) => {
    const kind = detectProposalKind(job)
    setApplyJob(job)
    setProposalKind(kind)
    setProposalText(buildProposalStub(job, kind))
    setCopied(false)
  }, [])

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
        fetchLastScraped()
        setRefreshing(false)
      }, 3000)
    } catch {
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

  useEffect(() => {
    if (focusedIndex >= filteredJobs.length) {
      setFocusedIndex(Math.max(0, filteredJobs.length - 1))
    }
  }, [filteredJobs.length, focusedIndex])

  const focusedJob = filteredJobs[focusedIndex] || null

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null
      const tag = target?.tagName
      if (tag === 'INPUT' || tag === 'TEXTAREA' || target?.isContentEditable) return
      if (applyJob && e.key === 'Escape') {
        e.preventDefault()
        closeApplyDrawer()
        return
      }
      if (applyJob) return
      if (!filteredJobs.length) return

      if (e.key === 'j' || e.key === 'ArrowDown') {
        e.preventDefault()
        setFocusedIndex(i => Math.min(filteredJobs.length - 1, i + 1))
        return
      }
      if (e.key === 'k' || e.key === 'ArrowUp') {
        e.preventDefault()
        setFocusedIndex(i => Math.max(0, i - 1))
        return
      }
      if (e.key === 'Enter') {
        e.preventDefault()
        if (!focusedJob) return
        setExpandedId(id => (id === focusedJob.id ? null : focusedJob.id))
        return
      }
      if (!focusedJob) return

      const status = focusedJob.status as JobStatus
      if (e.key === 'a' || e.key === 'A') {
        if (status === 'new' || status === 'interested') {
          e.preventDefault()
          openApplyDrawer(focusedJob)
        }
        return
      }
      if (e.key === 'i' || e.key === 'I') {
        if (status === 'new') {
          e.preventDefault()
          setJobStatus(focusedJob.id, 'interested')
        }
        return
      }
      if (e.key === 's' || e.key === 'S') {
        if (status === 'new' || status === 'interested' || status === 'applied') {
          e.preventDefault()
          setJobStatus(focusedJob.id, 'skipped')
        }
        return
      }
      if (status === 'applied') {
        if (e.key === '1') {
          e.preventDefault()
          markWon(focusedJob)
        } else if (e.key === '2') {
          e.preventDefault()
          setJobStatus(focusedJob.id, 'lost')
        } else if (e.key === '3') {
          e.preventDefault()
          setJobStatus(focusedJob.id, 'no_reply')
        }
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [applyJob, filteredJobs, focusedJob, closeApplyDrawer, openApplyDrawer, setJobStatus, markWon])

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
            <button type="button" className="triage-button triage-primary" onClick={() => markWon(job)}>Won</button>
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

  const scoreBreakdown = (job: Job) => (
    <div className="job-preview">
      <p className="job-preview-description">
        {job.description?.trim() || 'No description snippet stored.'}
      </p>
      <dl className="score-breakdown">
        <div>
          <dt>Priority</dt>
          <dd>{job.priority_score ?? '—'}</dd>
        </div>
        <div>
          <dt>Budget mid</dt>
          <dd>{job.budget_mid_usd != null ? `$${job.budget_mid_usd}` : formatBudget(job)}</dd>
        </div>
        <div>
          <dt>Effort</dt>
          <dd>{effortLabel(job.effort_score)}</dd>
        </div>
        <div>
          <dt>Type</dt>
          <dd>{job.job_type || '—'}</dd>
        </div>
        {job.status === 'won' && (
          <div>
            <dt>Earned</dt>
            <dd>{job.earnings_usd != null ? `$${job.earnings_usd}` : '—'}</dd>
          </div>
        )}
      </dl>
      {job.keyword_matches && (
        <p className="job-preview-keywords">Keywords: {job.keyword_matches}</p>
      )}
    </div>
  )

  const renderJobMeta = (job: Job) => (
    <>
      <span className="rate">{formatBudget(job)}</span>
      <span className="meta-sep">·</span>
      <span>{effortLabel(job.effort_score)}</span>
      <span className="meta-sep">·</span>
      <span>{job.source}</span>
      <span className="meta-sep">·</span>
      <span>{new Date(job.posted_date).toLocaleDateString()}</span>
    </>
  )

  const jobTypes = [...new Set(jobs.map(j => j.job_type).filter(Boolean))]
  const sources = [...new Set(jobs.map(j => j.source).filter(Boolean))]
  const closedWinRate = winRate(stats)
  const weeklyRevenue = stats?.weekly_revenue_usd

  return (
    <div className={`dashboard density-${density}`}>
      <header className="dashboard-header sticky-header">
        <div className="header-titles">
          <h1>Squarespace Job Monitor</h1>
          <p className="scrape-status">{formatRelativeTime(lastScrapedAt)}</p>
        </div>
        <div className="header-actions">
          <button
            type="button"
            className="density-toggle"
            onClick={() => setDensity(d => (d === 'comfortable' ? 'compact' : 'comfortable'))}
            title="Toggle row density"
          >
            {density === 'comfortable' ? 'Compact' : 'Comfortable'}
          </button>
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
        {statusFilter === 'closed' && closedWinRate && (
          <span className="win-rate-chip">{closedWinRate}</span>
        )}
        {typeof weeklyRevenue === 'number' && weeklyRevenue > 0 && (
          <span className="revenue-chip">${Math.round(weeklyRevenue)} this week</span>
        )}
      </div>

      <p className="keyboard-hint">
        Focus: ↑↓ or J/K · Enter preview · A apply · I shortlist · S skip · Applied: 1 won · 2 lost · 3 no reply
      </p>

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
      ) : statusFilter === 'forum' ? (
        <Forum />
      ) : (
        <>
          <div className="jobs-table-container desktop-only">
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
                {filteredJobs.map((job, index) => {
                  const focused = index === focusedIndex
                  const expanded = expandedId === job.id
                  return (
                    <tr
                      key={job.id}
                      className={[
                        focused ? 'row-focused' : '',
                        applyJob?.id === job.id ? 'row-active' : '',
                        expanded ? 'row-expanded' : '',
                      ].filter(Boolean).join(' ') || undefined}
                      onClick={() => setFocusedIndex(index)}
                    >
                      <td className="score-cell">
                        {job.priority_score != null ? (
                          <span className="score">{job.priority_score}</span>
                        ) : (
                          <span className="rate-unknown">—</span>
                        )}
                      </td>
                      <td className="job-title">
                        <div className="job-title-row">
                          <button
                            type="button"
                            className="title-expand"
                            onClick={(e) => {
                              e.stopPropagation()
                              setFocusedIndex(index)
                              setExpandedId(id => (id === job.id ? null : job.id))
                            }}
                          >
                            {job.title}
                          </button>
                          {CLOSED_STATUSES.includes(job.status as OutcomeFilter) && (
                            <span className={`outcome-badge outcome-badge--${job.status}`}>
                              {outcomeLabel(job.status)}
                            </span>
                          )}
                        </div>
                        {!expanded && job.description && (
                          <div className="job-description">
                            {job.description.substring(0, 100)}
                            {job.description.length > 100 && '...'}
                          </div>
                        )}
                        {expanded && scoreBreakdown(job)}
                      </td>
                      <td>
                        <span className="rate">{formatBudget(job)}</span>
                      </td>
                      <td>{effortLabel(job.effort_score)}</td>
                      <td>{job.source}</td>
                      <td>{new Date(job.posted_date).toLocaleDateString()}</td>
                      <td className="actions-cell" onClick={(e) => e.stopPropagation()}>
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
                  )
                })}
              </tbody>
            </table>
          </div>

          <div className="jobs-cards mobile-only">
            {filteredJobs.map((job, index) => {
              const focused = index === focusedIndex
              const expanded = expandedId === job.id
              return (
                <article
                  key={job.id}
                  className={`job-card ${focused ? 'row-focused' : ''} ${expanded ? 'row-expanded' : ''}`}
                  onClick={() => setFocusedIndex(index)}
                >
                  <div className="job-card-top">
                    <span className="score">{job.priority_score ?? '—'}</span>
                    {CLOSED_STATUSES.includes(job.status as OutcomeFilter) && (
                      <span className={`outcome-badge outcome-badge--${job.status}`}>
                        {outcomeLabel(job.status)}
                      </span>
                    )}
                  </div>
                  <button
                    type="button"
                    className="title-expand job-card-title"
                    onClick={(e) => {
                      e.stopPropagation()
                      setFocusedIndex(index)
                      setExpandedId(id => (id === job.id ? null : job.id))
                    }}
                  >
                    {job.title}
                  </button>
                  <div className="job-card-meta">{renderJobMeta(job)}</div>
                  {expanded && scoreBreakdown(job)}
                  {!expanded && job.description && (
                    <p className="job-description">
                      {job.description.substring(0, 120)}
                      {job.description.length > 120 && '...'}
                    </p>
                  )}
                  <div className="row-actions" onClick={(e) => e.stopPropagation()}>
                    <a href={job.url} target="_blank" rel="noopener noreferrer" className="view-link">Open</a>
                    {triageActions(job)}
                  </div>
                </article>
              )
            })}
          </div>

          {filteredJobs.length === 0 && (
            <div className="no-results">
              {jobs.length === 0
                ? EMPTY_COPY[statusFilter]
                : 'No jobs match your filters or search. Clear them to see all results.'}
            </div>
          )}
        </>
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

            <div className="proposal-kind-row" role="group" aria-label="Proposal type">
              {PROPOSAL_KINDS.map(k => (
                <button
                  key={k.key}
                  type="button"
                  className={`proposal-kind-pill ${proposalKind === k.key ? 'active' : ''}`}
                  onClick={() => {
                    setProposalKind(k.key)
                    setProposalText(buildProposalStub(applyJob, k.key))
                  }}
                >
                  {k.label}
                </button>
              ))}
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
