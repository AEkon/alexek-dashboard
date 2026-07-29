/** Client-side proposal stub. Callers: App.tsx Apply drawer. No API/DB.
 * User: "Implement the plan as specified" (Apply assist).
 */

export type ProposalJob = {
  title: string
  budget: string | null
  rate_min: number | null
  rate_max: number | null
  currency: string
  effort_score: number | null
}

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

/** Paste-ready proposal stub from job fields (template only, no AI). */
export function buildProposalStub(job: ProposalJob): string {
  const budget = formatBudget(job)
  const effort = effortBand(job.effort_score)
  const lines = [
    "Hi — I'm Alex, a Squarespace specialist.",
    '',
    `I can help with "${job.title}".`,
  ]

  if (budget || effort) {
    const parts: string[] = []
    if (budget) parts.push(budget)
    if (effort) parts.push(`estimated effort ${effort}`)
    lines.push(`Budget noted: ${parts.join(' · ')}.`)
  }

  lines.push(
    'Happy to clarify scope and deliver a clean turnaround.',
    '',
    'Thanks,',
    'Alex',
  )

  return lines.join('\n')
}
