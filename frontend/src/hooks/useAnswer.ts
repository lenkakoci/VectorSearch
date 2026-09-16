import { useCallback, useRef, useState } from 'react'
import { api } from '../services/api'
import type { AnswerOptions, AnswerRequest, AnswerResponse, RequestFilters } from '../types'

export interface ProgressStep {
  step: string
  [key: string]: unknown
}

export interface AnswerState {
  status: 'idle' | 'loading' | 'ok' | 'error'
  request?: AnswerRequest
  answer?: AnswerResponse
  error?: string
  ms?: number
  progress?: ProgressStep[]
}

// One question at a time. An answer takes ten to thirty seconds - grading
// forty candidates and then writing the answer - so a second question sent
// meanwhile must not be overwritten by the first one coming back.
//
// The answer arrives over a server-sent event stream: every step the chain
// reaches is a `progress` event, the finished answer is one `answer` event,
// and a failure is one `error` event. A browser or proxy that cannot stream
// falls back to the plain POST, which returns the same payload at the end.
export function useAnswer() {
  const [state, setState] = useState<AnswerState>({ status: 'idle' })
  const counter = useRef(0)

  const ask = useCallback(async (question: string, filters: RequestFilters, options: AnswerOptions = {}) => {
    const id = ++counter.current
    const started = performance.now()
    const request: AnswerRequest = { question, filters, options }
    const current = () => id === counter.current
    setState({ status: 'loading', request, progress: [] })

    const finish = (answer: AnswerResponse) =>
      setState((previous) => ({
        status: 'ok',
        request,
        answer,
        ms: performance.now() - started,
        progress: previous.progress,
      }))

    try {
      for await (const item of api.answerStream(request)) {
        if (!current()) return
        if (item.event === 'progress') {
          const step = item.data as ProgressStep
          setState((previous) => ({ ...previous, progress: [...(previous.progress ?? []), step] }))
        } else if (item.event === 'answer') {
          finish(item.data as unknown as AnswerResponse)
        } else if (item.event === 'error') {
          const { kind, detail } = item.data as { kind?: string; detail?: string }
          setState({ status: 'error', request, error: `${kind ?? 'Chyba'}: ${detail ?? ''}` })
        }
      }
    } catch (error) {
      if (!current()) return
      try {
        finish(await api.answer(request))
      } catch (fallbackError) {
        if (!current()) return
        setState({ status: 'error', request, error: (fallbackError as Error).message })
      }
    }
  }, [])

  return { state, ask }
}
