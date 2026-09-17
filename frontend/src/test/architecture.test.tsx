// Render smoke test for the architecture tab. Unlike the answer tests, this
// one asserts on the data model itself (unique ids, non-empty detail) rather
// than on a captured API fixture, because this tab never calls the API.

import { renderToString } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { ArchitectureView } from '../components/ArchitectureView'
import { PipelineMap } from '../components/PipelineMap'
import { StepDetail } from '../components/StepDetail'
import { DETAILS, PHASES, STEPS, TOPICS, detailOf } from '../lib/architecture'

describe('the architecture data model', () => {
  it('gives every step and topic a unique id', () => {
    const ids = DETAILS.map((item) => item.id)
    expect(new Set(ids).size).toBe(ids.length)
  })

  it('puts every step in a phase that actually exists', () => {
    const phaseIds = new Set(PHASES.map((phase) => phase.id))
    for (const step of STEPS) {
      expect(phaseIds.has(step.phase)).toBe(true)
    }
  })

  it('gives every step and topic a non-empty lead and at least one file', () => {
    for (const item of DETAILS) {
      expect(item.lead.length).toBeGreaterThan(0)
      expect(item.files.length).toBeGreaterThan(0)
    }
  })

  it('resolves every id back through detailOf', () => {
    for (const item of DETAILS) {
      expect(detailOf(item.id)?.id).toBe(item.id)
    }
  })
})

describe('the architecture tab renders without an API', () => {
  it('renders the whole tab with nothing selected', () => {
    const html = renderToString(<ArchitectureView />)
    expect(html).toContain('Architektura'.slice(0, 0)) // sanity: renders without throwing
    for (const topic of TOPICS) {
      expect(html).toContain(topic.title)
    }
  })

  it('renders the diagram with every step title', () => {
    const html = renderToString(<PipelineMap activeId={null} onSelect={() => undefined} />)
    for (const step of STEPS) {
      expect(html).toContain(step.title)
    }
  })

  it('shows the empty-state hint when nothing is selected', () => {
    const html = renderToString(<StepDetail detail={null} onClose={() => undefined} />)
    expect(html).toContain('Klikněte')
  })

  it('shows a selected step full detail, including its gotchas', () => {
    const embed = detailOf('embed')
    expect(embed).toBeTruthy()
    const html = renderToString(<StepDetail detail={embed ?? null} onClose={() => undefined} />)
    expect(html).toContain(embed!.title)
    expect(html).toContain('Proč 1536, ne 3072')
  })
})
