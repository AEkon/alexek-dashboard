import { useState, useEffect } from 'react'

// Types for our job data
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
}

interface JobsStats {
  by_status: Record<string, number>
  by_source: Record<string, number>
  by_type: Record<string, number>
  recent_7days: number
}

function App() {
  const [jobs, setJobs] = useState<Job[]>([])
  const [stats, setStats] = useState<JobsStats | null>(null)
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Filter states
  const [jobTypeFilter, setJobTypeFilter] = useState<string | null>(null)
  const [sourceFilter, setSourceFilter] = useState<string | null>(null)
  const [searchQuery, setSearchQuery] = useState('')

  // Sort states
  const [sortKey, setSortKey] = useState('posted_date')
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc')

  // Fetch jobs on mount
  useEffect(() => {
    fetchJobs()
    fetchStats()
  }, [])

  const fetchJobs = async () => {
    try {
      setLoading(true)
      setError(null)

      const params = new URLSearchParams()
      if (jobTypeFilter) params.append('job_type', jobTypeFilter)
      if (sourceFilter) params.append('source', sourceFilter)
      params.append('limit', '50')

      const response = await fetch(`/api/jobs?${params.toString()}`)
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
      const response = await fetch('/api/jobs/stats')
      if (!response.ok) throw new Error('Failed to fetch stats')

      const data = await response.json()
      setStats(data)
    } catch (err) {
      console.error('Failed to fetch stats:', err)
    }
  }

  const handleRefresh = async () => {
    setRefreshing(true)
    try {
      await fetch('/api/refresh/jobs', { method: 'POST' })

      // Wait a moment for scraping, then fetch fresh data
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
      setSortDir('asc')
    }
  }

  // Filter and sort jobs
  const filteredJobs = jobs
    .filter(job => {
      if (searchQuery) {
        const query = searchQuery.toLowerCase()
        return (
          job.title.toLowerCase().includes(query) ||
          job.description.toLowerCase().includes(query) ||
          job.keyword_matches.toLowerCase().includes(query)
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

  // Extract unique values for filters
  const jobTypes = [...new Set(jobs.map(j => j.job_type).filter(Boolean))]
  const sources = [...new Set(jobs.map(j => j.source).filter(Boolean))]

  return (
    <div className="dashboard">
      <header className="dashboard-header">
        <h1>Squarespace Job Monitor</h1>
        <button
          className="refresh-button"
          onClick={handleRefresh}
          disabled={refreshing}
        >
          {refreshing ? '↻' : '⟳'} Refresh
        </button>
      </header>

      {stats && (
        <div className="stats-row">
          <div className="stat-card">
            <div className="stat-value">{stats.by_status.new || 0}</div>
            <div className="stat-label">New Jobs</div>
          </div>
          <div className="stat-card">
            <div className="stat-value">{stats.by_type['short-term'] || 0}</div>
            <div className="stat-label">Short-Term</div>
          </div>
          <div className="stat-card">
            <div className="stat-value">{stats.recent_7days}</div>
            <div className="stat-label">Last 7 Days</div>
          </div>
        </div>
      )}

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
                <th onClick={() => toggleSort('title')} className="sortable">
                  Title {sortKey === 'title' ? (sortDir === 'asc' ? '▲' : '▼') : ''}
                </th>
                <th onClick={() => toggleSort('source')} className="sortable">
                  Source {sortKey === 'source' ? (sortDir === 'asc' ? '▲' : '▼') : ''}
                </th>
                <th onClick={() => toggleSort('job_type')} className="sortable">
                  Type {sortKey === 'job_type' ? (sortDir === 'asc' ? '▲' : '▼') : ''}
                </th>
                <th onClick={() => toggleSort('rate_min')} className="sortable">
                  Rate {sortKey === 'rate_min' ? (sortDir === 'asc' ? '▲' : '▼') : ''}
                </th>
                <th onClick={() => toggleSort('posted_date')} className="sortable">
                  Posted {sortKey === 'posted_date' ? (sortDir === 'asc' ? '▲' : '▼') : ''}
                </th>
                <th>Keywords</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody>
              {filteredJobs.map(job => (
                <tr key={job.id}>
                  <td className="job-title">
                    <div>{job.title}</div>
                    {job.description && (
                      <div className="job-description">
                        {job.description.substring(0, 100)}
                        {job.description.length > 100 && '...'}
                      </div>
                    )}
                  </td>
                  <td>{job.source}</td>
                  <td>{job.job_type}</td>
                  <td>
                    {job.rate_min && job.rate_max ? (
                      <span className="rate">
                        ${job.rate_min}-{job.rate_max}
                      </span>
                    ) : job.rate_min ? (
                      <span className="rate">${job.rate_min}</span>
                    ) : (
                      <span className="rate-unknown">-</span>
                    )}
                  </td>
                  <td>{new Date(job.posted_date).toLocaleDateString()}</td>
                  <td className="keywords">
                    {job.keyword_matches.split(',').slice(0, 2).map((kw, i) => (
                      <span key={i} className="keyword-tag">{kw.trim()}</span>
                    ))}
                  </td>
                  <td>
                    <a
                      href={job.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="apply-button"
                    >
                      View
                    </a>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          {filteredJobs.length === 0 && (
            <div className="no-results">
              No jobs found. Try adjusting your filters or search terms.
            </div>
          )}
        </div>
      )}
    </div>
  )
}

export default App