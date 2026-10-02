/**
 * Settings > Account > API tokens: personal tokens for agents and tools that
 * use Engram's OpenAI-compatible endpoint. A token acts as you. It is shown
 * once when created (only a hash is stored); revoking it stops agents at once.
 */

import { useEffect, useState } from 'react'
import { Copy, KeyRound } from 'lucide-react'
import { tokensApi, type ApiToken } from '../../services/api'
import {
  ActionButton, ActionRow, ActionStatus, ConfirmButton, ErrorStatus, InfoNote, TextField, errorText, useAction, useDirty,
} from './primitives'

const ENDPOINT = `${window.location.origin}/api/v1/chat/completions`
const date = (iso?: string | null) => (iso ? new Date(iso.endsWith('Z') ? iso : `${iso}Z`).toLocaleDateString() : 'never')

export default function ApiTokensCard() {
  const [tokens, setTokens] = useState<ApiToken[]>([])
  const [loadError, setLoadError] = useState('')
  const [name, setName] = useState('')
  const [created, setCreated] = useState<{ name: string; token: string } | null>(null)
  const [copied, setCopied] = useState(false)
  const [createState, runCreate] = useAction()
  const [revokeState, runRevoke] = useAction()
  useDirty(name !== '')

  const load = async () => {
    try {
      setTokens(await tokensApi.list())
      setLoadError('')
    } catch (e) {
      setLoadError(errorText(e, "Couldn't load API tokens"))
    }
  }
  useEffect(() => { load() }, [])

  const create = () => runCreate(async () => {
    const t = await tokensApi.create(name.trim())
    setCreated({ name: t.name, token: t.token })
    setCopied(false)
    setName('')
    await load()
  }, 'Token created', "Couldn't create the token")

  const revoke = (t: ApiToken) => runRevoke(async () => {
    await tokensApi.revoke(t.id)
    if (created && t.name === created.name) setCreated(null)
    await load()
  }, `${t.name} revoked`, `Couldn't revoke ${t.name}`)

  const copy = async () => {
    if (!created) return
    try {
      await navigator.clipboard.writeText(created.token)
      setCopied(true)
    } catch {
      setCopied(false)
    }
  }

  return (
    <section aria-labelledby="account-tokens" className="rounded-lg border border-dark-border/60 bg-dark-bg-secondary/50 p-4 space-y-3">
      <div>
        <h3 id="account-tokens" className="text-sm font-medium text-dark-text-primary">API tokens</h3>
        <p className="text-xs text-dark-text-secondary mt-0.5">
          For agents and tools that use Engram's OpenAI-compatible API. Use a token as the API key; it acts as you,
          with your memories and models.
        </p>
        <p className="text-xs text-dark-text-secondary mt-1">
          Endpoint: <code className="font-mono text-dark-text-primary break-all">{ENDPOINT}</code>
        </p>
      </div>

      {created && (
        <div role="status" className="rounded-md border border-green-600/40 bg-green-500/10 p-3 space-y-2">
          <p className="text-xs text-dark-text-primary">
            <KeyRound size={12} className="inline mr-1" />
            Copy the token for <span className="font-medium">{created.name}</span> now. It won't be shown again.
          </p>
          <div className="flex items-center gap-2">
            <input
              readOnly
              value={created.token}
              aria-label={`API token for ${created.name}`}
              onFocus={e => e.currentTarget.select()}
              className="flex-1 min-w-0 bg-dark-bg-primary border border-dark-border rounded-md px-3 py-1.5 text-xs font-mono text-dark-text-primary"
            />
            <ActionButton onClick={copy}><Copy size={13} /> {copied ? 'Copied' : 'Copy'}</ActionButton>
          </div>
          <ActionButton onClick={() => setCreated(null)}>Done</ActionButton>
        </div>
      )}

      {loadError ? (
        <div role="alert" className="flex items-center gap-3 text-xs text-red-400 [.light_&]:text-red-700">
          {loadError}
          <ActionButton onClick={load}>Retry</ActionButton>
        </div>
      ) : tokens.length === 0 ? (
        <p className="text-xs text-dark-text-secondary">No tokens yet.</p>
      ) : (
        <ul className="divide-y divide-dark-border/40 rounded-md border border-dark-border/60">
          {tokens.map(t => (
            <li key={t.id} className="flex flex-wrap items-center gap-3 px-3 py-2">
              <div className="flex-1 min-w-0">
                <p className="text-sm text-dark-text-primary truncate">{t.name}</p>
                <p className="text-[11px] text-dark-text-secondary">
                  <span className="font-mono">{t.hint}…</span> · created {date(t.created_at)} · last used {date(t.last_used_at)}
                </p>
              </div>
              <ConfirmButton
                label="Revoke"
                prompt={`Revoke ${t.name}? Agents using it stop working.`}
                confirmLabel="Revoke"
                danger
                busy={revokeState.status === 'busy'}
                onConfirm={() => revoke(t)}
              />
            </li>
          ))}
        </ul>
      )}
      <ErrorStatus state={revokeState} />

      <ActionRow>
        <div className="flex-1 min-w-[12rem]">
          <TextField label="New token name" value={name} onChange={setName} placeholder="e.g. Laptop coding agent" />
        </div>
        <ActionButton variant="primary" onClick={create} busy={createState.status === 'busy'} disabled={name.trim() === ''}>
          Create token
        </ActionButton>
        <ActionStatus state={createState} />
      </ActionRow>
      <InfoNote>
        Anyone with a token can use Engram as you. Revoke tokens you no longer use. Changing your password or
        signing out everywhere revokes all of them.
      </InfoNote>
    </section>
  )
}
