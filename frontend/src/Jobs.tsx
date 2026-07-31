import { Fragment, useState, useEffect, useCallback } from 'react'
import { buildJobAdvice } from './proposal'

// Callers: App.tsx. API: GET/PATCH /api/jobs, POST /api/jobs/{id}/generate, POST /api/refresh/jobs, GET /api/jobs/stats.

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
  budget: string | null
  budget_mid_usd: number | null
  rate_min: number | null
  rate_max: number | null
  currency: string
  effort_score: number | null
  priority_score: number | null
  ai_proposal: string | null
  ai_bid_amount: number | null
  ai_bid_days: number | null
  proposal_generated_at: string | null
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

type JobsProps = {
  onInboxChange?: () => void
}

const STATUS_TABS: { key: JobStatus; label: string }[] = [
  { key: 'new', label: 'New' },
  { key: 'interested', label: 'Interested' },
  { key: 'applied', label: 'Applied' },
  { key: 'closed', label: 'Closed' },
]

const EMPTY_COPY: Record<string, string> = {
  new: 'No new jobs. Jobs are checked every 30 minutes.',
  interested: 'No jobs marked as interested.',
  applied: 'No applied jobs.',
  closed: 'No closed jobs.',
}

const SOURCE_META: Record<string, { short: string; title: string }> = {
  freelancer: { short: 'FL', title: 'Freelancer' },
  peopleperhour: { short: 'PPH', title: 'PeoplePerHour' },
  upwork: { short: 'UW', title: 'Upwork' },
}

function sourceMeta(source: string) {
  const key = (source || '').toLowerCase()
  return SOURCE_META[key] || { short: (source || '??').slice(0, 2).toUpperCase(), title: source || 'Unknown' }
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

function formatMoney(amount: number | null, currency: string | null): string {
  if (amount == null) return '—'
  const sym = currency === 'GBP' ? '£' : currency === 'EUR' ? '€' : '$'
  return `${sym}${Number.isInteger(amount) ? amount : amount.toFixed(2)}`
}

function promptEarnings(): number | null {
  const raw = prompt('Earnings (USD)?')
  if (raw == null || raw.trim() === '') return null
  const n = Number(raw)
  return Number.isFinite(n) && n >= 0 ? n : null
}

async function copyText(text: string) {
  try {
    await navigator.clipboard.writeText(text)
  } catch {
    // ignore
  }
}

export default function Jobs({ onInboxChange }: JobsProps) {
  const [jobs, setJobs] = useState<Job[]>([])
  const [stats, setStats] = useState<JobStats | null>(null)
  const [activeTab, setActiveTab] = useState<JobStatus>('new')
  const [refreshing, setRefreshing] = useState(false)
  const [expandedId, setExpandedId] = useState<number | null>(null)
  const [searchQuery, setSearchQuery] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [generatingId, setGeneratingId] = useState<number | null>(null)
  const [copiedKey, setCopiedKey] = useState<string | null>(null)

  const notifyInbox = useCallback(() => {
    onInboxChange?.()
  }, [onInboxChange])

  const fetchJobs = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await fetch(`/api/jobs?status=${activeTab}&limit=50`)
      if (res.ok) {
        setJobs(await res.json())
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
        setStats(await res.json())
        notifyInbox()
      }
    } catch (e) {
      console.error('Failed to fetch stats:', e)
    }
  }, [notifyInbox])

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

  const handleSkip = async (id: number) => {
    await handleStatusUpdate(id, { status: 'archived' })
  }

  const handleWon = async (id: number) => {
    const earnings = promptEarnings()
    await handleStatusUpdate(id, {
      status: 'won',
      ...(earnings != null ? { earnings_usd: earnings } : {}),
    })
  }

  const handleGenerate = async (id: number) => {
    setGeneratingId(id)
    setError(null)
    try {
      const res = await fetch(`/api/jobs/${id}/generate`, { method: 'POST' })
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        setError(typeof body.detail === 'string' ? body.detail : `AI generation failed: ${res.status}`)
        return
      }
      const data = await res.json()
      setJobs(prev =>
        prev.map(j =>
          j.id === id
            ? {
                ...j,
                ai_proposal: data.ai_proposal,
                ai_bid_amount: data.ai_bid_amount,
                ai_bid_days: data.ai_bid_days,
                proposal_generated_at: data.proposal_generated_at,
              }
            : j
        )
      )
      setExpandedId(id)
    } catch (e) {
      console.error('AI generation failed:', e)
      setError('Failed to generate proposal')
    } finally {
      setGeneratingId(null)
    }
  }

  const flashCopied = (key: string) => {
    setCopiedKey(key)
    window.setTimeout(() => setCopiedKey(prev => (prev === key ? null : prev)), 1500)
  }

  const handleCopy = async (key: string, text: string) => {
    await copyText(text)
    flashCopied(key)
  }

  const handleCopyPack = async (job: Job) => {
    if (!job.ai_proposal) return
    const pack = [
      job.ai_proposal,
      '',
      `Bid: ${formatMoney(job.ai_bid_amount, job.currency)}`,
      `Days: ${job.ai_bid_days ?? '—'}`,
    ].join('\n')
    await handleCopy(`pack-${job.id}`, pack)
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

  const generateButton = (job: Job) => {
    const generating = generatingId === job.id
    return (
      <button
        type="button"
        className="triage-button triage-primary"
        disabled={generating}
        onClick={() => handleGenerate(job.id)}
      >
        {generating ? 'Generating…' : job.ai_proposal ? 'Regenerate AI' : 'Generate AI'}
      </button>
    )
  }

  const copyButtons = (job: Job) => {
    if (!job.ai_proposal) return null
    return (
      <button
        type="button"
        className="triage-button triage-secondary"
        onClick={() => handleCopyPack(job)}
      >
        {copiedKey === `pack-${job.id}` ? 'Copied' : 'Copy AI'}
      </button>
    )
  }

  const renderActions = (job: Job) => {
    const open = (
      <a href={job.url} target="_blank" rel="noopener noreferrer" className="view-link">
        Open
      </a>
    )

    if (job.status === 'new') {
      return (
        <div className="triage-group">
          {open}
          {generateButton(job)}
          {copyButtons(job)}
          <button
            type="button"
            className="triage-button triage-secondary"
            onClick={() => handleStatusUpdate(job.id, { status: 'interested' })}
          >
            Interested
          </button>
          <button type="button" className="triage-button triage-ghost" onClick={() => handleSkip(job.id)}>
            Skip
          </button>
        </div>
      )
    }

    if (job.status === 'interested') {
      return (
        <div className="triage-group">
          {open}
          {generateButton(job)}
          {copyButtons(job)}
          <button
            type="button"
            className="triage-button triage-secondary"
            onClick={() => handleStatusUpdate(job.id, { status: 'applied' })}
          >
            Applied
          </button>
          <button
            type="button"
            className="triage-button triage-ghost"
            onClick={() => handleStatusUpdate(job.id, { status: 'new' })}
          >
            Undo
          </button>
          <button type="button" className="triage-button triage-ghost" onClick={() => handleSkip(job.id)}>
            Skip
          </button>
        </div>
      )
    }

    if (job.status === 'applied') {
      return (
        <div className="triage-group">
          {open}
          {generateButton(job)}
          {copyButtons(job)}
          <button type="button" className="triage-button triage-primary" onClick={() => handleWon(job.id)}>
            Won
          </button>
          <button
            type="button"
            className="triage-button triage-secondary"
            onClick={() => handleStatusUpdate(job.id, { status: 'lost' })}
          >
            Lost
          </button>
          <button
            type="button"
            className="triage-button triage-ghost"
            onClick={() => handleStatusUpdate(job.id, { status: 'no_reply' })}
          >
            No reply
          </button>
          <button
            type="button"
            className="triage-button triage-ghost"
            onClick={() => handleStatusUpdate(job.id, { status: 'interested' })}
          >
            Back
          </button>
          <button type="button" className="triage-button triage-ghost" onClick={() => handleSkip(job.id)}>
            Skip
          </button>
        </div>
      )
    }

    if (['won', 'lost', 'no_reply'].includes(job.status)) {
      return (
        <div className="triage-group">
          {open}
          {copyButtons(job)}
          <button
            type="button"
            className="triage-button triage-secondary"
            onClick={() => handleStatusUpdate(job.id, { status: 'applied' })}
          >
            Back to Applied
          </button>
        </div>
      )
    }

    return <div className="triage-group">{open}</div>
  }

  const colCount = 5

  return (
    <div className="jobs-section">
      <div className="section-divider">
        <h3 className="section-title">Job Opportunities</h3>
        <p className="section-description">
          Squarespace gigs — generate a Freelancer proposal, bid amount, and delivery days when ready to bid
        </p>
      </div>

      <header className="section-header">
        <h2>Jobs Board</h2>
        <button className="refresh-button" onClick={handleRefresh} disabled={refreshing}>
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

      {error && <div className="error-message">{error}</div>}

      {loading ? (
        <div className="loading">Loading jobs...</div>
      ) : filteredJobs.length === 0 ? (
        <div className="no-results">
          <p>{EMPTY_COPY[activeTab] || 'No jobs found.'}</p>
        </div>
      ) : (
        <div className="jobs-table-container">
          <table className="jobs-table inbox-table">
            <thead>
              <tr>
                <th className="title-col">Title</th>
                <th className="source-col">Src</th>
                <th className="advice-col">Bid pack</th>
                <th className="time-col">Posted</th>
                <th className="actions-col">Actions</th>
              </tr>
            </thead>
            <tbody>
              {filteredJobs.map(job => {
                const advice = buildJobAdvice(job)
                const meta = sourceMeta(job.source)
                const hasPack = Boolean(job.ai_proposal)
                const expanded = expandedId === job.id
                return (
                  <Fragment key={job.id}>
                    <tr
                      className={expanded ? 'focused' : ''}
                      onClick={() => setExpandedId(expanded ? null : job.id)}
                    >
                      <td className="title-cell">
                        <div className="job-title">{job.title}</div>
                      </td>
                      <td className="source-col">
                        <span
                          className={`source-icon source-icon--${(job.source || '').toLowerCase()}`}
                          title={meta.title}
                          aria-label={meta.title}
                        >
                          {meta.short}
                        </span>
                      </td>
                      <td className="advice-cell">
                        {hasPack ? (
                          <>
                            <div className="advice-summary">
                              {formatMoney(job.ai_bid_amount, job.currency)} · {job.ai_bid_days}d
                            </div>
                            <div className="advice-score">AI ready</div>
                          </>
                        ) : (
                          <>
                            <div className="advice-summary">{advice.summary}</div>
                            {advice.score != null && (
                              <div className="advice-score">score {Math.round(advice.score)}</div>
                            )}
                          </>
                        )}
                      </td>
                      <td className="time-col">{formatRelativeTime(job.posted_date)}</td>
                      <td className="row-actions actions-cell" onClick={(e) => e.stopPropagation()}>
                        {renderActions(job)}
                      </td>
                    </tr>
                    {expanded && (
                      <tr className="detail-row">
                        <td colSpan={colCount}>
                          <div className="row-detail">
                            <p className="row-detail-body">{job.description}</p>
                            {hasPack ? (
                              <div className="job-proposal-box">
                                <div className="job-proposal-meta">
                                  <span>
                                    <strong>Bid</strong> {formatMoney(job.ai_bid_amount, job.currency)}
                                  </span>
                                  <span>
                                    <strong>Days</strong> {job.ai_bid_days}
                                  </span>
                                  <button
                                    type="button"
                                    className="triage-button triage-secondary"
                                    onClick={() =>
                                      handleCopy(
                                        `bid-${job.id}`,
                                        String(job.ai_bid_amount ?? '')
                                      )
                                    }
                                  >
                                    {copiedKey === `bid-${job.id}` ? 'Copied' : 'Copy bid'}
                                  </button>
                                  <button
                                    type="button"
                                    className="triage-button triage-secondary"
                                    onClick={() =>
                                      handleCopy(`days-${job.id}`, String(job.ai_bid_days ?? ''))
                                    }
                                  >
                                    {copiedKey === `days-${job.id}` ? 'Copied' : 'Copy days'}
                                  </button>
                                  <button
                                    type="button"
                                    className="triage-button triage-secondary"
                                    onClick={() =>
                                      handleCopy(`proposal-${job.id}`, job.ai_proposal || '')
                                    }
                                  >
                                    {copiedKey === `proposal-${job.id}` ? 'Copied' : 'Copy proposal'}
                                  </button>
                                  <button
                                    type="button"
                                    className="triage-button triage-primary"
                                    onClick={() => handleCopyPack(job)}
                                  >
                                    {copiedKey === `pack-${job.id}` ? 'Copied' : 'Copy all'}
                                  </button>
                                </div>
                                <strong className="job-proposal-label">Proposal</strong>
                                <p className="job-proposal-text">{job.ai_proposal}</p>
                              </div>
                            ) : (
                              <div className="job-advice-box">
                                <strong>Quick heuristic</strong>
                                <p>{advice.summary}</p>
                                <p className="advice-hint">
                                  Click Generate AI for a Freelancer-ready proposal, bid, and days.
                                </p>
                              </div>
                            )}
                            {job.earnings_usd != null && (
                              <p className="job-earnings">Won: ${job.earnings_usd}</p>
                            )}
                          </div>
                        </td>
                      </tr>
                    )}
                  </Fragment>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
