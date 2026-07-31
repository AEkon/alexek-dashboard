/** Client-side proposal library. Callers: App.tsx Apply drawer. No API/DB.
 * Schema: none (local templates only).
 * User: "do them all" (fix / redesign / CSS templates).
 */

export type ProposalKind = 'fix' | 'css' | 'redesign' | 'general'

export type ProposalJob = {
  title: string
  description?: string | null
  keyword_matches?: string | null
  budget: string | null
  rate_min: number | null
  rate_max: number | null
  currency: string
  effort_score: number | null
}

export const PROPOSAL_KINDS: { key: ProposalKind; label: string }[] = [
  { key: 'fix', label: 'Fix' },
  { key: 'css', label: 'CSS' },
  { key: 'redesign', label: 'Redesign' },
  { key: 'general', label: 'General' },
]

function formatBudget(job: ProposalJob): string | null {
  if (job.budget) return job.budget
  const sym = job.currency === 'GBP' ? '£' : job.currency === 'EUR' ? '€' : '$'
  if (job.rate_min != null && job.rate_max != null && job.rate_min !== job.rate_max) {
    return `${sym}${job.rate_min}–${job.rate_max}`
  }
  if (job.rate_min != null) return `${sym}${job.rate_min}`
  return null
}

function effortBand(score: number | null): string | null {
  if (score == null) return null
  if (score <= 3) return 'low'
  if (score <= 6) return 'mid'
  return 'high'
}

/** Infer proposal kind from listing text (mirrors backend detect_job_kind). */
export function detectProposalKind(job: ProposalJob): ProposalKind {
  const text = `${job.title} ${job.description || ''} ${job.keyword_matches || ''}`.toLowerCase()
  if (
    ['redesign', 'rebrand', 'from scratch', 'full website', 'full site', 'migration', 'migrate'].some(
      (p) => text.includes(p),
    )
  ) {
    return 'redesign'
  }
  if (['custom css', 'css fix', 'css', 'styling', 'style'].some((p) => text.includes(p))) {
    return 'css'
  }
  if (
    ['quick fix', 'bug fix', 'small fix', 'fix', 'tweak', 'urgent', 'broken'].some((p) =>
      text.includes(p),
    )
  ) {
    return 'fix'
  }
  return 'general'
}

function bodyForKind(kind: ProposalKind, title: string): string[] {
  switch (kind) {
    case 'fix':
      return [
        `I can help with "${title}" — I've fixed a lot of Squarespace layout, mobile, and content bugs.`,
        'Typical turnaround is same-day or next-day once I can see the page and editor access.',
      ]
    case 'css':
      return [
        `I can help with "${title}" — custom CSS and design polish on Squarespace is my day job.`,
        'I keep overrides clean, mobile-safe, and easy for you to maintain after handoff.',
      ]
    case 'redesign':
      return [
        `I can help with "${title}" — I redesign and rebuild Squarespace sites end to end.`,
        'Happy to clarify pages, brand direction, and a phased delivery so scope stays clear.',
      ]
    default:
      return [
        `I can help with "${title}".`,
        'Happy to clarify scope and deliver a clean turnaround.',
      ]
  }
}

/** Paste-ready proposal stub from job fields + selected kind (template only, no AI). */
export function buildProposalStub(job: ProposalJob, kind?: ProposalKind): string {
  const resolved = kind ?? detectProposalKind(job)
  const budget = formatBudget(job)
  const effort = effortBand(job.effort_score)
  const lines = ["Hi — I'm Alex, a Squarespace specialist.", '', ...bodyForKind(resolved, job.title)]

  if (budget || effort) {
    const parts: string[] = []
    if (budget) parts.push(budget)
    if (effort) parts.push(`estimated effort ${effort}`)
    lines.push(`Budget noted: ${parts.join(' · ')}.`)
  }

  lines.push('', 'Thanks,', 'Alex')
  return lines.join('\n')
}

export type JobAdvice = {
  budgetLabel: string | null
  suggestedOffer: string | null
  estimatedDays: string | null
  effortLabel: string | null
  score: number | null
  summary: string
}

/** Heuristic bid/days advice from parsed budget + effort (RSS has no AI fields). */
export function buildJobAdvice(job: {
  budget: string | null
  rate_min?: number | null
  rate_max?: number | null
  currency?: string
  budget_mid_usd?: number | null
  effort_score: number | null
  priority_score?: number | null
}): JobAdvice {
  const effort = job.effort_score
  const mid = job.budget_mid_usd
  const currency = job.currency || 'USD'
  const sym = currency === 'GBP' ? '£' : currency === 'EUR' ? '€' : '$'

  let estimatedDays: string | null = null
  let effortLabel: string | null = null
  if (effort != null) {
    if (effort <= 2) {
      estimatedDays = '0.5 day'
      effortLabel = 'quick'
    } else if (effort <= 4) {
      estimatedDays = '1 day'
      effortLabel = 'low'
    } else if (effort <= 6) {
      estimatedDays = '2–3 days'
      effortLabel = 'mid'
    } else if (effort <= 8) {
      estimatedDays = '4–5 days'
      effortLabel = 'high'
    } else {
      estimatedDays = '1–2 weeks'
      effortLabel = 'large'
    }
  }

  let suggestedOffer: string | null = null
  if (mid != null && mid > 0) {
    // Bid near mid-budget, slightly under average to stay competitive on Freelancer
    const offer = Math.round(mid * 0.9)
    suggestedOffer = `${sym}${offer}`
  } else if (job.rate_min != null && job.rate_max != null) {
    const offer = Math.round((job.rate_min + job.rate_max) / 2)
    suggestedOffer = `${sym}${offer}`
  } else if (job.rate_min != null) {
    suggestedOffer = `${sym}${job.rate_min}`
  }

  const budgetLabel = job.budget || null
  const parts: string[] = []
  if (suggestedOffer) parts.push(`offer ~${suggestedOffer}`)
  if (estimatedDays) parts.push(`~${estimatedDays}`)
  if (budgetLabel) parts.push(`client ${budgetLabel}`)

  return {
    budgetLabel,
    suggestedOffer,
    estimatedDays,
    effortLabel,
    score: job.priority_score ?? null,
    summary: parts.length ? parts.join(' · ') : 'No budget in listing — estimate from scope',
  }
}
