/**
 * Personas page: how Engram talks to you.
 * The default persona's instructions are added to every chat. Pick the
 * default with the radio (saves at once); create, edit and delete personas.
 */

import { useState, useEffect } from 'react'
import { Plus } from 'lucide-react'
import { personasApi } from '../../services/api'
import type { Persona } from '../../types/addin.types'
import {
  ActionButton, ActionRow, ActionStatus, ConfirmButton, Disclosure, ErrorStatus, StatusPill, TextArea, TextField,
  errorText, useAction,
} from '../settings/primitives'

interface Draft { name: string; description: string; systemPrompt: string }
const EMPTY: Draft = { name: '', description: '', systemPrompt: '' }

export default function PersonaTab() {
  const [personas, setPersonas] = useState<Persona[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [loadError, setLoadError] = useState('')
  const [creating, setCreating] = useState(false)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [defaultState, runDefault] = useAction()
  const [deleteState, runDelete] = useAction()

  useEffect(() => { fetchPersonas() }, [])

  async function fetchPersonas() {
    try {
      const data = await personasApi.list()
      setPersonas(data)
      setLoadError('')
    } catch (error) {
      setLoadError(errorText(error, "Couldn't load personas"))
    } finally {
      setIsLoading(false)
    }
  }

  const setDefault = (p: Persona) => runDefault(async () => {
    await personasApi.update(p.id, { isDefault: true })
    await fetchPersonas()
  }, `${p.name} is now the default`, "Couldn't change the default")

  const remove = (p: Persona) => runDelete(async () => {
    await personasApi.delete(p.id)
    await fetchPersonas()
  }, `${p.name} deleted`, `Couldn't delete ${p.name}`)

  return (
    <div className="h-full overflow-y-auto">
      <div className="max-w-3xl mx-auto px-4 sm:px-6 py-4 md:py-8 space-y-5">
        <div className="flex items-start justify-between gap-3 flex-wrap">
          <div>
            <h1 className="text-xl font-semibold text-dark-text-primary">Personas</h1>
            <p className="text-sm text-dark-text-secondary mt-0.5">
              How Engram talks to you. The default persona's instructions are used in every chat.
            </p>
          </div>
          {!creating && (
            <ActionButton variant="primary" onClick={() => setCreating(true)}><Plus size={14} /> New persona</ActionButton>
          )}
        </div>

        {creating && (
          <PersonaForm
            title="New persona"
            initial={EMPTY}
            submitLabel="Create persona"
            onCancel={() => setCreating(false)}
            onSubmit={async (d) => {
              await personasApi.create({ name: d.name, description: d.description, systemPrompt: d.systemPrompt })
              setCreating(false)
              await fetchPersonas()
            }}
          />
        )}

        {loadError && (
          <div role="alert" className="flex items-center gap-3 text-xs text-red-400 [.light_&]:text-red-700">
            {loadError}
            <ActionButton onClick={fetchPersonas}>Retry</ActionButton>
          </div>
        )}
        <ErrorStatus state={defaultState} />
        <ErrorStatus state={deleteState} />

        {isLoading ? (
          <p className="text-sm text-dark-text-secondary">Loading personas…</p>
        ) : personas.length === 0 && !loadError ? (
          <p className="text-sm text-dark-text-secondary">No personas yet. Create one to give Engram standing instructions.</p>
        ) : (
          <fieldset className="space-y-3">
            <legend className="sr-only">Default persona</legend>
            {personas.map(p => (
              <div key={p.id} className={`rounded-lg border p-4 space-y-2 ${
                p.is_default ? 'border-dark-accent-primary/40 bg-dark-bg-secondary' : 'border-dark-border/60 bg-dark-bg-secondary/50'
              }`}>
                {editingId === p.id ? (
                  <PersonaForm
                    title={`Edit ${p.name}`}
                    initial={{ name: p.name, description: p.description ?? '', systemPrompt: p.system_prompt }}
                    submitLabel="Save"
                    onCancel={() => setEditingId(null)}
                    onSubmit={async (d) => {
                      // is_default is left out, so editing never changes the default
                      await personasApi.update(p.id, { name: d.name, description: d.description, systemPrompt: d.systemPrompt })
                      setEditingId(null)
                      await fetchPersonas()
                    }}
                  />
                ) : (
                  <>
                    <div className="flex items-start gap-3">
                      <label className="flex-1 min-w-0 flex items-start gap-3 cursor-pointer">
                        <input
                          type="radio"
                          name="default-persona"
                          checked={p.is_default}
                          onChange={() => setDefault(p)}
                          disabled={defaultState.status === 'busy'}
                          className="mt-1 w-4 h-4 flex-shrink-0 accent-dark-accent-primary cursor-pointer"
                        />
                        <span className="min-w-0">
                          <span className="flex items-center gap-2 flex-wrap">
                            <span className="text-sm font-medium text-dark-text-primary">{p.name}</span>
                            {p.is_default && <StatusPill status="default" />}
                          </span>
                          {p.description && <span className="block text-xs text-dark-text-secondary">{p.description}</span>}
                          <span className="block text-xs text-dark-text-secondary/90 truncate mt-1">“{p.system_prompt}”</span>
                        </span>
                      </label>
                    </div>
                    <Disclosure summary="Show full instructions">
                      <pre className="text-xs text-dark-text-secondary bg-dark-bg-primary rounded p-2 overflow-x-auto whitespace-pre-wrap">
                        {p.system_prompt}
                      </pre>
                    </Disclosure>
                    <div className="flex items-center gap-2 flex-wrap">
                      <ActionButton onClick={() => setEditingId(p.id)}>Edit</ActionButton>
                      <ConfirmButton
                        label="Delete"
                        prompt={`Delete ${p.name}?${p.is_default ? ' It is your default, so chats will have no persona.' : ''}`}
                        confirmLabel="Delete persona"
                        danger
                        busy={deleteState.status === 'busy'}
                        onConfirm={() => remove(p)}
                      />
                    </div>
                  </>
                )}
              </div>
            ))}
          </fieldset>
        )}
      </div>
    </div>
  )
}

function PersonaForm({ title, initial, submitLabel, onCancel, onSubmit }: {
  title: string; initial: Draft; submitLabel: string; onCancel: () => void; onSubmit: (d: Draft) => Promise<void>
}) {
  const [draft, setDraft] = useState<Draft>(initial)
  const [state, run] = useAction()
  const valid = draft.name.trim() !== '' && draft.systemPrompt.trim() !== ''
  const set = (k: keyof Draft) => (v: string) => setDraft(d => ({ ...d, [k]: v }))

  return (
    <div className="rounded-lg border border-dark-border/60 bg-dark-bg-secondary/50 p-4 space-y-3">
      <h2 className="text-sm font-medium text-dark-text-primary">{title}</h2>
      <TextField label="Name" value={draft.name} onChange={set('name')} placeholder="e.g. Code reviewer" />
      <TextField label="Description (optional)" value={draft.description} onChange={set('description')} placeholder="One line about it" />
      <TextArea label="Instructions" value={draft.systemPrompt} onChange={set('systemPrompt')} rows={5}
                placeholder="You are a senior engineer. Review code for…"
                hint="Added to every chat while this persona is the default." />
      <ActionRow>
        <ActionButton onClick={onCancel}>Cancel</ActionButton>
        <ActionButton variant="primary" disabled={!valid} busy={state.status === 'busy'}
                      onClick={() => run(() => onSubmit({ name: draft.name.trim(), description: draft.description.trim(), systemPrompt: draft.systemPrompt }))}>
          {submitLabel}
        </ActionButton>
        <ActionStatus state={state} />
        {!valid && <span className="text-[11px] text-dark-text-secondary">Name and instructions are required.</span>}
      </ActionRow>
    </div>
  )
}
