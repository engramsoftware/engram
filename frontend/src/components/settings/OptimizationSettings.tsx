/**
 * "Cost & accuracy" card (in Settings > Models).
 * Response validation and the conversation history limit. Both switches save
 * as soon as they are flipped and revert if saving fails.
 */

import { useState, useEffect, useRef } from 'react'
import { settingsApi } from '../../services/api'
import type { OptimizationConfig } from '../../types/chat.types'
import { ErrorStatus, Switch, useAction } from './primitives'

interface Props {
  config?: OptimizationConfig
  onUpdate: () => void
}

// With the limit off, chat sends the last 25 messages (backend/routers/messages.py)
const FULL_HISTORY_CAP = 25

export default function OptimizationSettings({ config, onUpdate }: Props) {
  const savedValidation = config?.response_validation ?? true
  const savedLimit = config?.history_limit ?? 0
  const [responseValidation, setResponseValidation] = useState(savedValidation)
  const [historyLimit, setHistoryLimit] = useState(savedLimit)
  const [validationState, runValidation] = useAction()
  const [limitState, runLimit] = useAction()

  useEffect(() => { setResponseValidation(savedValidation) }, [savedValidation])
  useEffect(() => { setHistoryLimit(savedLimit) }, [savedLimit])

  // The backend accepts any N; keep a saved value other than 3 (also across off/on)
  const lastLimit = useRef(savedLimit > 0 ? savedLimit : 3)
  if (savedLimit > 0) lastLimit.current = savedLimit
  const limitWhenOn = lastLimit.current

  // Both values are always sent together, as the backend expects
  const save = (validation: boolean, limit: number) => settingsApi.updateLLMSettings({
    optimization: { response_validation: validation, history_limit: limit },
  })

  const flipValidation = (next: boolean) => {
    setResponseValidation(next)
    runValidation(async () => {
      try {
        await save(next, historyLimit)
      } catch (error) {
        setResponseValidation(!next)
        throw error
      }
      onUpdate()
    }, 'Saved', "Couldn't change this")
  }

  const flipLimit = (on: boolean) => {
    const next = on ? limitWhenOn : 0
    const previous = historyLimit
    setHistoryLimit(next)
    runLimit(async () => {
      try {
        await save(responseValidation, next)
      } catch (error) {
        setHistoryLimit(previous)
        throw error
      }
      onUpdate()
    }, 'Saved', "Couldn't change this")
  }

  // Each save sends both values, so one switch waits while the other is saving
  const saving = validationState.status === 'busy' || limitState.status === 'busy'

  return (
    <div className="rounded-lg border border-dark-border/60 bg-dark-bg-secondary/50 divide-y divide-dark-border/40">
      <div className="flex items-start justify-between gap-4 p-4">
        <div>
          <h4 className="text-sm font-medium text-dark-text-primary">Double-check answers</h4>
          <p className="text-xs text-dark-text-secondary mt-1">
            A second AI call checks each reply for made-up facts. Uses about 3,000 extra tokens
            per message and makes replies slower.
          </p>
          <ErrorStatus state={validationState} />
        </div>
        <Switch size="sm" checked={responseValidation} onChange={flipValidation} label="Double-check answers"
                disabled={saving} />
      </div>

      <div className="flex items-start justify-between gap-4 p-4">
        <div>
          <h4 className="text-sm font-medium text-dark-text-primary">Send only recent messages</h4>
          <p className="text-xs text-dark-text-secondary mt-1">
            Sends the last {limitWhenOn} messages instead of the last {FULL_HISTORY_CAP}. Older relevant
            messages are still found by search and added as context. Saves 10–50K tokens in long chats.
          </p>
          <ErrorStatus state={limitState} />
        </div>
        <Switch size="sm" checked={historyLimit > 0} onChange={flipLimit} label="Send only recent messages"
                disabled={saving} />
      </div>
    </div>
  )
}
