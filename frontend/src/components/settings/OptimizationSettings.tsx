/**
 * Optimization settings panel.
 * Controls response validation and conversation history limit.
 */

import { useState } from 'react'
import { Loader2 } from 'lucide-react'
import { settingsApi } from '../../services/api'
import type { OptimizationConfig } from '../../types/chat.types'

interface Props {
  config?: OptimizationConfig
  onUpdate: () => void
}

export default function OptimizationSettings({ config, onUpdate }: Props) {
  const [saving, setSaving] = useState(false)
  const [responseValidation, setResponseValidation] = useState(
    config?.response_validation ?? true
  )
  const [historyLimit, setHistoryLimit] = useState(
    config?.history_limit ?? 0
  )

  const save = async () => {
    setSaving(true)
    try {
      await settingsApi.updateLLMSettings({
        optimization: {
          response_validation: responseValidation,
          history_limit: historyLimit,
        },
      })
      onUpdate()
    } catch (err) {
      console.error('Failed to save optimization settings:', err)
    } finally {
      setSaving(false)
    }
  }

  const hasChanges =
    responseValidation !== (config?.response_validation ?? true) ||
    historyLimit !== (config?.history_limit ?? 0)

  return (
    <div className="rounded-lg border border-dark-border bg-dark-bg-secondary p-4 space-y-4">
      {/* Response Validation Toggle */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <h3 className="text-sm font-medium text-dark-text-primary">
            Response Validation
          </h3>
          <p className="text-xs text-dark-text-secondary mt-1">
            Run an extra LLM call after each response to check for hallucinations.
            Costs ~3K extra tokens per message. Disable to save tokens and speed up responses.
          </p>
        </div>
        <button
          type="button"
          role="switch"
          aria-checked={responseValidation}
          onClick={() => setResponseValidation(!responseValidation)}
          className={`relative inline-flex h-5 w-9 flex-shrink-0 cursor-pointer rounded-full
                     border-2 border-transparent transition-colors duration-200 ease-in-out
                     ${responseValidation ? 'bg-dark-accent-primary' : 'bg-dark-border'}`}
        >
          <span
            className={`pointer-events-none inline-block h-4 w-4 transform rounded-full
                       bg-white shadow ring-0 transition duration-200 ease-in-out
                       ${responseValidation ? 'translate-x-4' : 'translate-x-0'}`}
          />
        </button>
      </div>

      {/* History Limit Toggle */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <h3 className="text-sm font-medium text-dark-text-primary">
            Limit Conversation History
          </h3>
          <p className="text-xs text-dark-text-secondary mt-1">
            Send only the last 3 messages instead of full history.
            Relevant older context is still injected via hybrid search.
            Saves 10-50K tokens on long conversations.
          </p>
        </div>
        <button
          type="button"
          role="switch"
          aria-checked={historyLimit > 0}
          onClick={() => setHistoryLimit(historyLimit > 0 ? 0 : 3)}
          className={`relative inline-flex h-5 w-9 flex-shrink-0 cursor-pointer rounded-full
                     border-2 border-transparent transition-colors duration-200 ease-in-out
                     ${historyLimit > 0 ? 'bg-dark-accent-primary' : 'bg-dark-border'}`}
        >
          <span
            className={`pointer-events-none inline-block h-4 w-4 transform rounded-full
                       bg-white shadow ring-0 transition duration-200 ease-in-out
                       ${historyLimit > 0 ? 'translate-x-4' : 'translate-x-0'}`}
          />
        </button>
      </div>

      {/* Save button */}
      {hasChanges && (
        <div className="flex justify-end pt-1">
          <button
            onClick={save}
            disabled={saving}
            className="inline-flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm font-medium
                       bg-dark-accent-primary hover:bg-dark-accent-primary/80 text-white
                       disabled:opacity-50 transition-colors"
          >
            {saving && <Loader2 size={14} className="animate-spin" />}
            {saving ? 'Saving...' : 'Save'}
          </button>
        </div>
      )}
    </div>
  )
}
