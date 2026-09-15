import { useCallback, useRef, useState } from 'react'
import { api } from '../services/api'
import type { AnswerOptions, AnswerRequest, AnswerResponse, RequestFilters } from '../types'

export interface AnswerState {
  status: 'idle' | 'loading' | 'ok' | 'error'
  request?: AnswerRequest
  answer?: AnswerResponse
  error?: string
  ms?: number
}

// One question at a time. An answer takes ten to thirty seconds - grading
// forty candidates and then writing the answer - so a second question sent
// meanwhile must not be overwritten by the first one coming back.
export function useAnswer() {
  const [state, setState] = useState<AnswerState>({ status: 'idle' })
  const counter = useRef(0)

  const ask = useCallback(async (question: string, filters: RequestFilters, options: AnswerOptions = {}) => {
    const id = ++counter.current
    const started = performance.now()
    const request: AnswerRequest = { question, filters, options }
    setState({ status: 'loading', request })
    try {
      const answer = await api.answer(request)
      if (id !== counter.current) return
      setState({ status: 'ok', request, answer, ms: performance.now() - started })
    } catch (error) {
      if (id !== counter.current) return
      setState({ status: 'error', request, error: (error as Error).message })
    }
  }, [])

  return { state, ask }
}
