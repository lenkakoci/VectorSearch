// Render smoke test for the answering tab, over two answers captured from the
// real API: src/test/fixtures/answer.json (a question the corpus answers) and
// src/test/fixtures/no-evidence.json (a locality that is not in the corpus, so
// the gate closed and no model was called). Effects do not run in server
// rendering, so what is asserted here is the first frame the audience sees.

import { renderToString } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { AnswerCard } from '../components/AnswerCard'
import { AskView } from '../components/AskView'
import { PipelineTrace } from '../components/PipelineTrace'
import { SourceList } from '../components/SourceList'
import type { AnswerResponse } from '../types'
import answerFixture from './fixtures/answer.json'
import noEvidenceFixture from './fixtures/no-evidence.json'

const answer = answerFixture as unknown as AnswerResponse
const noEvidence = noEvidenceFixture as unknown as AnswerResponse

// Server rendering separates adjacent text and values with empty comments.
const render = (node: Parameters<typeof renderToString>[0]) => renderToString(node).replace(/<!-- -->/g, '')

const first = answer.statements[0]

describe('the answer itself', () => {
  it('shows the status, the sentence and its citations', () => {
    const html = render(<AnswerCard answer={answer} active={null} onCite={() => undefined} />)
    expect(html).toContain('Odpovězeno')
    expect(html).toContain(first.text)
    // One chip per cited source, and the count the check produced.
    first.source_ids.forEach((id) => expect(html).toContain(`>${id}</button>`))
    expect(html).toContain('ověřeno 1 z 1 vět')
    expect(html).toContain('branou prošlo 4 z 40 kandidátů')
  })

  it('marks a sentence the check did not verify', () => {
    const flagged: AnswerResponse = {
      ...answer,
      status: 'partial',
      statements: [{ ...first, check: 'number_unsupported', note: 'číslo z věty není v citovaných zdrojích: 14' }],
      missing: ['průměr vrtů'],
      conflicts: [{ topic: 'hloubka', source_ids: [1, 3], description: 'jeden zdroj uvádí 80 m, druhý 100 m' }],
    }
    const html = render(<AnswerCard answer={flagged} active={null} onCite={() => undefined} />)
    expect(html).toContain('Částečně')
    expect(html).toContain('Neověřeno')
    expect(html).toContain('číslo z věty ve zdrojích není')
    expect(html).toContain('Ve zdrojích chybí')
    expect(html).toContain('průměr vrtů')
    expect(html).toContain('Rozpory mezi zdroji')
  })
})

describe('an answer that was not paid for twice', () => {
  const cached: AnswerResponse = { ...answer, trace: { ...answer.trace, cache: 'hit' } }

  it('says it came from the cache instead of from the model', () => {
    const card = render(<AnswerCard answer={cached} active={null} onCite={() => undefined} />)
    expect(card).toContain('z cache')

    const trace = render(<PipelineTrace answer={cached} open onToggle={() => undefined} />)
    expect(trace).toContain('z cache: stejná otázka už byla zodpovězena')
  })
})

describe('the sources under the answer', () => {
  it('names each source and says which ones the answer cited', () => {
    const html = render(<SourceList sources={answer.sources} highlight={null} />)
    expect(html).toContain('8 úryvků v kontextu, z toho 2 citovaných')
    expect(html).toContain('citováno')
    expect(html).toContain('kontext')
    expect(html).toContain('známka 3/3')
    expect(html).toContain('chunk #')
  })

  it('links to the page of the PDF the source was cut from', () => {
    const html = render(<SourceList sources={answer.sources} highlight={null} />)
    const source = answer.sources.find((item) => item.page_from)!
    expect(html).toContain(`/api/documents/${source.document_id}/pdf#page=${source.page_from}`)
    expect(html).toContain(`PDF, s. ${source.page_from}`)
  })

  it('highlights the quote inside the source a citation points at', () => {
    const html = render(<SourceList sources={answer.sources} highlight={{ id: first.source_ids[0], quotes: first.quotes }} />)
    expect(html).toContain('<mark')
    // The quote is found in the chunk text even though the spacing differs.
    expect(html).not.toContain('&lt;mark')
  })
})

describe('the expert panel', () => {
  it('lists the whole chain with its counts, the prompt and the raw answer', () => {
    const html = render(<PipelineTrace answer={answer} open onToggle={() => undefined} />)
    expect(html).toContain('Fulltext')
    expect(html).toContain('Vektor')
    expect(html).toContain('Reranking')
    expect(html).toContain('Brána relevance')
    expect(html).toContain('4 z 40 prošlo')
    expect(html).toContain('8 zdrojů')
    expect(html).toContain('Kontrola citací')
    expect(html).toContain('1 z 1 ověřeno')
    expect(html).toContain('Prompt, jak ho dostal model')
    expect(html).toContain('Surová odpověď modelu')
  })
})

describe('a question the corpus cannot answer', () => {
  it('says so, offers the nearest passages and reports that no model ran', () => {
    const html = render(<AskView state={{ status: 'ok', answer: noEvidence }} expertOpen onExpert={() => undefined} />)
    expect(html).toContain('Bez podkladů')
    expect(html).toContain('Model se vůbec nevolal')
    expect(html).toContain('Nejbližší nalezené úryvky')
    expect(html).toContain('pod prahem')
    expect(html).toContain('model se nevolal, nebylo z čeho odpovídat')
  })

  it('shows what is happening while the answer is being written', () => {
    const html = render(<AskView state={{ status: 'loading' }} expertOpen={false} onExpert={() => undefined} />)
    expect(html).toContain('Hledám podklady')
  })
})
