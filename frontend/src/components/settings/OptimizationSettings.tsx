/**
 * Optimization settings panel.
 * Controls response validation and conversation history limit.
 */

import { useState, useEffect, useRef } from 'react'
import { settingsApi } from '../../services/api'
import type { OptimizationConfig } from '../../types/chat.types'
import { ActionButton, ActionStatus, Switch, useAction } from './primitives'

interface Props {
  config?: OptimizationConfig
  onUpdate: () => void
}

export default function OptimizationSettings({ config, onUpdate }: Props) {
  const savedValidation = config?.response_validation ?? true
  const savedLimit = config?.history_limit ?? 0
  const [responseValidation, setResponseValidation] = useState(savedValidation)
  const [historyLimit, setHistoryLimit] = useState(savedLimit)
  const [saveState, runSave] = useAction()

  useEffect(() => { setResponseValidation(savedValidation) }, [savedValidation])
  useEffect(() => { setHistoryLimit(savedLimit) }, [savedLimit])

  const hasChanges = responseValidation !== savedValidation || historyLimit !== savedLimit
  // The backend accepts any N; keep a saved value other than 3 (also across off/on)
  const lastLimit = useRef(savedLimit > 0 ? savedLimit : 3)
  if (savedLimit > 0) lastLimit.current = savedLimit
  const limitWhenOn = lastLimit.current
  // With the limit off, chat sends the last 25 messages (backend/routers/messages.py)
  const FULL_HISTORY_CAP = 25

  const save = () => runSave(async () => {
    await settingsApi.updateLLMSettings({
      optimization: {
        response_validation: responseValidation,
        history_limit: historyLimit,
      },
    })
    onUpdate()
  })

  return (
    <div className="rounded-lg border border-dark-border/60 bg-dark-bg-secondary/50 divide-y divide-dark-border/40">
      <div className="flex items-start justify-between gap-4 p-4">
        <div>
          <h3 className="text-sm font-medium text-dark-text-primary">Response validation</h3>
          <p className="text-xs text-dark-text-secondary mt-1">
            Run an extra LLM call after each response to check for hallucinations.
            Costs ~3K extra tokens per message. Disable to save tokens and speed up responses.
          </p>
        </div>
        <Switch size="sm" checked={responseValidation} onChange={setResponseValidation} label="Response validation" />
      </div>

      <div className="flex items-start justify-between gap-4 p-4">
        <div>
          <h3 className="text-sm font-medium text-dark-text-primary">Limit conversation history</h3>
          <p className="text-xs text-dark-text-secondary mt-1">
            Send only the last {limitWhenOn} messages instead of the last {FULL_HISTORY_CAP}.
            Relevant older messages are still found by search and added as context.
            Saves 10-50K tokens on long conversations.
          </p>
        </div>
        <Switch
          size="sm"
          checked={historyLimit > 0}
          onChange={(on) => setHistoryLimit(on ? limitWhenOn : 0)}
          label="Limit conversation history"
        />
      </div>

      {(hasChanges || saveState.status !== 'idle') && (
        <div className="flex items-center justify-end gap-2 p-3">
          <ActionStatus state={saveState} />
          {hasChanges && (
            <ActionButton variant="primary" onClick={save} busy={saveState.status === 'busy'}>
              {saveState.status === 'busy' ? 'Saving…' : 'Save'}
            </ActionButton>
          )}
        </div>
      )}
    </div>
  )
}
