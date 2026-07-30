import { useState, useEffect, useCallback } from 'react'

// Callers: App.tsx. API: GET/PATCH /api/forum/questions, POST /api/forum/refresh, GET /api/forum/stats.
// Schema: forum_questions (source, source_id, title, description, url, comments_count, ai_answer, status, ...)

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

const STATUS_TABS: { key: ForumStatus; label: string }[] = [
  { key: 'new', label: 'New' },
  { key: 'answered', label: 'Answered' },
  { key: 'archived', label: 'Archived' },
]

const EMPTY_COPY: Record<ForumStatus, string> = {
  new: 'No new forum questions. Questions are checked every 30 minutes.',
  answered: 'No answered questions yet. Mark questions as answered when you respond on the forum.',
  archived: 'No archived questions.',
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

export default function Forum() {
  const [questions, setQuestions] = useState<ForumQuestion[]>([])
  const [stats, setStats] = useState<ForumStats | null>(null)
  const [activeTab, setActiveTab] = useState<ForumStatus>('new')
  const [refreshing, setRefreshing] = useState(false)
  const [expandedId, setExpandedId] = useState<number | null>(null)
  const [searchQuery, setSearchQuery] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  const fetchQuestions = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await fetch(`/api/forum/questions?status=${activeTab}&limit=50`)
      if (res.ok) {
        const data = await res.json()
        setQuestions(data)
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
        const data = await res.json()
        setStats(data)
      }
    } catch (e) {
      console.error('Failed to fetch stats:', e)
    }
  }, [])

  useEffect(() => {
    fetchQuestions()
    fetchStats()
  }, [fetchQuestions, fetchStats])

  const handleRefresh = async () => {
    setRefreshing(true)
    try {
      await fetch('/api/forum/refresh', { method: 'POST' })
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

  const handleArchive = async (id: number) => {
    await handleStatusUpdate(id, { status: 'archived' })
  }

  const filteredQuestions = questions.filter(q =>
    q.title.toLowerCase().includes(searchQuery.toLowerCase()) ||
    q.description.toLowerCase().includes(searchQuery.toLowerCase())
  )

  const tabCount = (key: ForumStatus) => stats?.by_status[key] || 0

  return (
    <div className="forum-section">
      <div className="section-divider">
        <h3 className="section-title">Forum Monitor</h3>
        <p className="section-description">Unanswered Squarespace CSS/JS questions with AI answer suggestions</p>
      </div>

      <header className="section-header">
        <h2>Forum Questions</h2>
        <button
          className="refresh-button"
          onClick={handleRefresh}
          disabled={refreshing}
        >
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

      {error && (
        <div className="error-message">
          {error}
        </div>
      )}

      {loading ? (
        <div className="loading">Loading forum questions...</div>
      ) : filteredQuestions.length === 0 ? (
        <div className="no-results">
          <p>{EMPTY_COPY[activeTab]}</p>
        </div>
      ) : (
        <div className="forum-table-container">
          <table className="forum-table">
            <thead>
              <tr>
                <th onClick={() => {/* TODO: Add sorting */}} className="sortable">
                  Title {'▲'}
                </th>
                <th>AI Answer</th>
                <th>Source</th>
                <th>Comments</th>
                <th>Time</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {filteredQuestions.map(question => (
                <tr
                  key={question.id}
                  className={expandedId === question.id ? 'focused' : ''}
                  onClick={() => setExpandedId(expandedId === question.id ? null : question.id)}
                >
                  <td className="title-cell">
                    <div className="forum-title">{question.title}</div>
                    {expandedId === question.id && (
                      <div className="forum-description">
                        <p>{question.description}</p>
                        {question.ai_answer && (
                          <div className="ai-answer-box">
                            <strong>AI Answer:</strong>
                            <p>{question.ai_answer}</p>
                          </div>
                        )}
                      </div>
                    )}
                  </td>
                  <td>
                    {question.ai_answer ? (
                      <span className="ai-badge">✓ AI</span>
                    ) : (
                      <span className="no-ai-badge">—</span>
                    )}
                  </td>
                  <td>
                    <span className="source-badge">{question.source}</span>
                  </td>
                  <td>{question.comments_count}</td>
                  <td>{formatRelativeTime(question.created_at)}</td>
                  <td className="row-actions" onClick={(e) => e.stopPropagation()}>
                    <a href={question.url} target="_blank" rel="noopener noreferrer" className="view-link">
                      Open
                    </a>
                    {question.status === 'new' && (
                      <>
                        <button
                          className="triage-button triage-secondary"
                          onClick={() => {
                            const answerUrl = prompt('Enter your forum answer URL:')
                            if (answerUrl) handleMarkAnswered(question.id, answerUrl)
                          }}
                        >
                          Answered
                        </button>
                        <button
                          className="triage-button triage-ghost"
                          onClick={() => handleArchive(question.id)}
                        >
                          Archive
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
