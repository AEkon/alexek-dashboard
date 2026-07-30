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

  const fetchQuestions = useCallback(async () => {
    try {
      const res = await fetch(`/api/forum/questions?status=${activeTab}&limit=50`)
      if (res.ok) {
        const data = await res.json()
        setQuestions(data)
      }
    } catch (e) {
      console.error('Failed to fetch questions:', e)
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
      <header className="section-header">
        <h2>Forum Monitor</h2>
        <button
          className="refresh-btn"
          onClick={handleRefresh}
          disabled={refreshing}
        >
          {refreshing ? '↻' : '⟳'}
        </button>
      </header>

      <div className="stats-bar">
        {STATUS_TABS.map(tab => (
          <button
            key={tab.key}
            className={`tab ${activeTab === tab.key ? 'active' : ''}`}
            onClick={() => setActiveTab(tab.key)}
          >
            {tab.label} ({tabCount(tab.key)})
          </button>
        ))}
      </div>

      <div className="search-bar">
        <input
          type="text"
          placeholder="Search questions..."
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
        />
      </div>

      {filteredQuestions.length === 0 ? (
        <div className="empty-state">
          <p>{EMPTY_COPY[activeTab]}</p>
        </div>
      ) : (
        <div className="questions-list">
          {filteredQuestions.map(question => (
            <div key={question.id} className="question-card">
              <div className="question-header">
                <h3
                  className="question-title"
                  onClick={() => setExpandedId(expandedId === question.id ? null : question.id)}
                >
                  {question.title}
                  <span className="expand-icon">
                    {expandedId === question.id ? '▼' : '▶'}
                  </span>
                </h3>
                <div className="question-meta">
                  <span className="source-badge">{question.source}</span>
                  <span className="comments">{question.comments_count} comments</span>
                  <span className="time">{formatRelativeTime(question.created_at)}</span>
                </div>
              </div>

              {expandedId === question.id && (
                <div className="question-details">
                  <p className="description">{question.description}</p>

                  {question.ai_answer && (
                    <div className="ai-answer">
                      <h4>AI Suggested Answer:</h4>
                      <p>{question.ai_answer}</p>
                    </div>
                  )}

                  <div className="question-actions">
                    <a
                      href={question.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="action-btn primary"
                    >
                      Answer on Forum →
                    </a>

                    {question.status === 'new' && (
                      <>
                        <button
                          className="action-btn"
                          onClick={() => {
                            const answerUrl = prompt('Enter your forum answer URL:')
                            if (answerUrl) handleMarkAnswered(question.id, answerUrl)
                          }}
                        >
                          Mark Answered
                        </button>
                        <button
                          className="action-btn secondary"
                          onClick={() => handleArchive(question.id)}
                        >
                          Archive
                        </button>
                      </>
                    )}
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
