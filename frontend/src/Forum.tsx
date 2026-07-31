import { Fragment, useState, useEffect, useCallback } from 'react'

// Callers: App.tsx. API: GET/PATCH /api/forum/questions, POST /api/forum/questions/{id}/generate,
// POST /api/forum/refresh, GET /api/forum/stats.

interface ForumQuestion {
  id: number
  source: string
  source_id: string
  title: string
  description: string
  url: string
  comments_count: number
  ai_answer: string | null
  answer_generated_at: string | null
  status: string
  answered_at: string | null
  answer_url: string | null
  created_at: string
  updated_at: string
}

interface ForumStats {
  by_status: Record<string, number>
  by_source: Record<string, number>
}

type ForumStatus = 'new' | 'answered' | 'archived'

type ForumProps = {
  onInboxChange?: () => void
}

const STATUS_TABS: { key: ForumStatus; label: string }[] = [
  { key: 'new', label: 'New' },
  { key: 'answered', label: 'Answered' },
  { key: 'archived', label: 'Skipped' },
]

const EMPTY_COPY: Record<ForumStatus, string> = {
  new: 'No new forum questions. Questions are checked every 30 minutes.',
  answered: 'No answered questions yet. Mark questions as answered when you respond on the forum.',
  archived: 'No skipped questions.',
}

const SOURCE_META: Record<string, { label: string; short: string; title: string }> = {
  squarespace_forum: { label: 'SS', short: 'SS', title: 'Squarespace Forum' },
  stackoverflow: { label: 'SO', short: 'SO', title: 'Stack Overflow' },
}

function sourceMeta(source: string) {
  return SOURCE_META[source] || { label: source.slice(0, 2).toUpperCase(), short: source.slice(0, 2).toUpperCase(), title: source }
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

function isLastDay(iso: string | null): boolean {
  if (!iso) return false
  const then = new Date(iso).getTime()
  const now = Date.now()
  return (now - then) < 24 * 60 * 60 * 1000
}

async function copyText(text: string) {
  try {
    await navigator.clipboard.writeText(text)
  } catch {
    // ignore
  }
}

export default function Forum({ onInboxChange }: ForumProps) {
  const [questions, setQuestions] = useState<ForumQuestion[]>([])
  const [stats, setStats] = useState<ForumStats | null>(null)
  const [activeTab, setActiveTab] = useState<ForumStatus>('new')
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

  const fetchQuestions = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await fetch(`/api/forum/questions?status=${activeTab}&limit=50`)
      if (res.ok) {
        setQuestions(await res.json())
      } else {
        setError(`Failed to fetch questions: ${res.status}`)
      }
    } catch (e) {
      console.error('Failed to fetch questions:', e)
      setError('Failed to connect to server')
    } finally {
      setLoading(false)
    }
  }, [activeTab])

  const fetchStats = useCallback(async () => {
    try {
      const res = await fetch('/api/forum/stats')
      if (res.ok) {
        setStats(await res.json())
        notifyInbox()
      }
    } catch (e) {
      console.error('Failed to fetch stats:', e)
    }
  }, [notifyInbox])

  useEffect(() => {
    fetchQuestions()
    fetchStats()
  }, [fetchQuestions, fetchStats])

  const handleRefresh = async () => {
    setRefreshing(true)
    try {
      await fetch('/api/forum/refresh', { method: 'POST' })
      await new Promise(resolve => setTimeout(resolve, 2000))
      await fetchQuestions()
      await fetchStats()
    } catch (e) {
      console.error('Refresh failed:', e)
    } finally {
      setRefreshing(false)
    }
  }

  const handleStatusUpdate = async (id: number, updates: Partial<ForumQuestion>) => {
    try {
      const res = await fetch(`/api/forum/questions/${id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(updates),
      })
      if (res.ok) {
        await fetchQuestions()
        await fetchStats()
      }
    } catch (e) {
      console.error('Status update failed:', e)
    }
  }

  const handleMarkAnswered = async (id: number, answerUrl: string) => {
    await handleStatusUpdate(id, {
      status: 'answered',
      answered_at: new Date().toISOString(),
      answer_url: answerUrl,
    })
  }

  const handleSkip = async (id: number) => {
    await handleStatusUpdate(id, { status: 'archived' })
  }

  const handleGenerate = async (id: number) => {
    setGeneratingId(id)
    setError(null)
    try {
      const res = await fetch(`/api/forum/questions/${id}/generate`, { method: 'POST' })
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        setError(body.detail || `AI generation failed: ${res.status}`)
        return
      }
      const data = await res.json()
      setQuestions(prev =>
        prev.map(q =>
          q.id === id
            ? { ...q, ai_answer: data.ai_answer, answer_generated_at: data.answer_generated_at }
            : q
        )
      )
      setExpandedId(id)
    } catch (e) {
      console.error('AI generation failed:', e)
      setError('Failed to generate AI answer')
    } finally {
      setGeneratingId(null)
    }
  }

  const flashCopied = (key: string) => {
    setCopiedKey(key)
    window.setTimeout(() => setCopiedKey(prev => (prev === key ? null : prev)), 1500)
  }

  const handleCopyAnswer = async (question: ForumQuestion) => {
    if (!question.ai_answer) return
    await copyText(question.ai_answer)
    flashCopied(`answer-${question.id}`)
  }

  const filteredQuestions = questions.filter(q => {
    const matchesSearch = searchQuery === '' ||
      q.title.toLowerCase().includes(searchQuery.toLowerCase()) ||
      q.description.toLowerCase().includes(searchQuery.toLowerCase())
    return matchesSearch && isLastDay(q.created_at)
  })

  const tabCount = (key: ForumStatus) => stats?.by_status[key] || 0
  const colCount = 5

  return (
    <div className="forum-section">
      <div className="section-divider">
        <h3 className="section-title">Forum Monitor</h3>
        <p className="section-description">Unanswered Squarespace CSS/JS questions — generate a draft reply when you want to answer</p>
      </div>

      <header className="section-header">
        <h2>Forum Questions</h2>
        <button className="refresh-button" onClick={handleRefresh} disabled={refreshing}>
          {refreshing ? '↻' : '⟳'} Refresh
        </button>
      </header>

      <div className="inbox-bar">
        <div className="status-tabs" role="tablist" aria-label="Forum status">
          {STATUS_TABS.map(tab => {
            const count = tabCount(tab.key)
            const active = activeTab === tab.key
            return (
              <button
                key={tab.key}
                type="button"
                role="tab"
                aria-selected={active}
                className={`status-tab status-tab--${tab.key} ${active ? 'active' : ''}`}
                onClick={() => setActiveTab(tab.key)}
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
          placeholder="Search questions..."
          className="search-input"
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
        />
      </div>

      {error && <div className="error-message">{error}</div>}

      {loading ? (
        <div className="loading">Loading forum questions...</div>
      ) : filteredQuestions.length === 0 ? (
        <div className="no-results">
          <p>{EMPTY_COPY[activeTab]}</p>
        </div>
      ) : (
        <div className="forum-table-container">
          <table className="forum-table inbox-table">
            <thead>
              <tr>
                <th className="title-col">Title</th>
                <th className="ai-col">AI</th>
                <th className="source-col">Src</th>
                <th className="time-col">Time</th>
                <th className="actions-col">Actions</th>
              </tr>
            </thead>
            <tbody>
              {filteredQuestions.map(question => {
                const meta = sourceMeta(question.source)
                const generating = generatingId === question.id
                const expanded = expandedId === question.id
                return (
                  <Fragment key={question.id}>
                    <tr
                      className={expanded ? 'focused' : ''}
                      onClick={() => setExpandedId(expanded ? null : question.id)}
                    >
                      <td className="title-cell">
                        <div className="forum-title">{question.title}</div>
                      </td>
                      <td className="ai-col">
                        {question.ai_answer ? (
                          <span className="ai-badge" title="Draft ready">✓</span>
                        ) : (
                          <span className="no-ai-badge">—</span>
                        )}
                      </td>
                      <td className="source-col">
                        <span
                          className={`source-icon source-icon--${question.source}`}
                          title={meta.title}
                          aria-label={meta.title}
                        >
                          {meta.short}
                        </span>
                      </td>
                      <td className="time-col">{formatRelativeTime(question.created_at)}</td>
                      <td className="row-actions actions-cell" onClick={(e) => e.stopPropagation()}>
                        <div className="triage-group">
                          <a href={question.url} target="_blank" rel="noopener noreferrer" className="view-link">
                            Open
                          </a>
                          {question.status === 'new' && (
                            <>
                              <button
                                type="button"
                                className="triage-button triage-primary"
                                disabled={generating}
                                onClick={() => handleGenerate(question.id)}
                              >
                                {generating ? 'Generating…' : question.ai_answer ? 'Regenerate' : 'Generate AI'}
                              </button>
                              {question.ai_answer && (
                                <button
                                  type="button"
                                  className="triage-button triage-secondary"
                                  onClick={() => handleCopyAnswer(question)}
                                >
                                  {copiedKey === `answer-${question.id}` ? 'Copied' : 'Copy AI'}
                                </button>
                              )}
                              <button
                                type="button"
                                className="triage-button triage-secondary"
                                onClick={() => {
                                  const answerUrl = prompt('Enter your forum answer URL:')
                                  if (answerUrl) handleMarkAnswered(question.id, answerUrl)
                                }}
                              >
                                Answered
                              </button>
                              <button
                                type="button"
                                className="triage-button triage-ghost"
                                onClick={() => handleSkip(question.id)}
                              >
                                Skip
                              </button>
                            </>
                          )}
                          {question.status === 'archived' && (
                            <button
                              type="button"
                              className="triage-button triage-ghost"
                              onClick={() => handleStatusUpdate(question.id, { status: 'new' })}
                            >
                              Restore
                            </button>
                          )}
                          {question.status === 'answered' && question.ai_answer && (
                            <button
                              type="button"
                              className="triage-button triage-secondary"
                              onClick={() => handleCopyAnswer(question)}
                            >
                              {copiedKey === `answer-${question.id}` ? 'Copied' : 'Copy AI'}
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>
                    {expanded && (
                      <tr className="detail-row">
                        <td colSpan={colCount}>
                          <div className="row-detail">
                            <p className="row-detail-body">{question.description}</p>
                            {question.ai_answer && (
                              <div className="ai-answer-box">
                                <div className="ai-answer-toolbar">
                                  <strong>Draft reply</strong>
                                  <button
                                    type="button"
                                    className="triage-button triage-secondary"
                                    onClick={() => handleCopyAnswer(question)}
                                  >
                                    {copiedKey === `answer-${question.id}` ? 'Copied' : 'Copy reply'}
                                  </button>
                                </div>
                                <p>{question.ai_answer}</p>
                              </div>
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
