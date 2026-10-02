/**
 * Settings > Data & logs.
 * - Your data: export (first) and ChatGPT import (asks before importing)
 * - Diagnostics (admins only): server-wide log levels and the live log viewer, collapsed.
 *   The viewer stays mounted while hidden so pause and filters survive, but it
 *   only fetches and streams while it is on screen.
 */

import { useRef, useState } from 'react'
import { Check, Download, Upload } from 'lucide-react'
import { useAuthStore } from '../../stores/authStore'
import LoggingSettings from './LoggingSettings'
import LogViewer from './LogViewer'
import { ActionButton, ActionStatus, Disclosure, useAction } from './primitives'

export default function DataSection({ active }: { active: boolean }) {
  const [diagnosticsOpen, setDiagnosticsOpen] = useState(false)
  const [logsOpen, setLogsOpen] = useState(false)
  const isAdmin = useAuthStore(s => !!s.user?.is_admin)

  return (
    <div className="space-y-6">
      <section aria-labelledby="data-yours" className="space-y-3">
        <h3 id="data-yours" className="text-[10px] font-semibold uppercase tracking-wider text-dark-text-secondary">Your data</h3>
        <YourData />
      </section>

      {isAdmin && <section aria-labelledby="data-diagnostics" className="space-y-3">
        <div>
          <h3 id="data-diagnostics" className="text-[10px] font-semibold uppercase tracking-wider text-dark-text-secondary">
            Diagnostics
          </h3>
          <p className="text-xs text-dark-text-secondary mt-0.5">
            Server-wide: log levels and logs affect and show activity from everyone on this Engram. Levels reset when the server restarts.
          </p>
        </div>
        <div className="rounded-lg border border-dark-border/60 bg-dark-bg-secondary/50 p-4 space-y-4">
          <Disclosure summary="Log levels" open={diagnosticsOpen} onOpenChange={setDiagnosticsOpen}>
            <LoggingSettings />
          </Disclosure>
          <Disclosure summary="Live logs" open={logsOpen} onOpenChange={setLogsOpen} keepMounted>
            <LogViewer active={active && logsOpen} />
          </Disclosure>
        </div>
      </section>}
    </div>
  )
}

/** Export and ChatGPT import. */
function YourData() {
  const fileRef = useRef<HTMLInputElement>(null)
  const [pendingFile, setPendingFile] = useState<File | null>(null)
  const [importing, setImporting] = useState(false)
  const [importResult, setImportResult] = useState<string | null>(null)
  const [importError, setImportError] = useState<string | null>(null)
  const [exportState, runExport] = useAction()

  const token = useAuthStore.getState().token

  const resetInput = () => { if (fileRef.current) fileRef.current.value = '' }

  /** Importing adds conversations; it asks first so a second click can't duplicate them by accident */
  const chooseFile = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    setImportResult(null)
    setImportError(null)
    setPendingFile(file ?? null)
  }

  const runImport = async () => {
    const file = pendingFile
    if (!file) return
    setPendingFile(null)
    setImporting(true)
    try {
      const formData = new FormData()
      formData.append('file', file)
      const res = await fetch('/api/data/import/chatgpt', {
        method: 'POST',
        headers: token ? { Authorization: `Bearer ${token}` } : {},
        body: formData,
      })
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: 'Import failed' }))
        throw new Error(typeof err.detail === 'string' ? err.detail : 'Import failed')
      }
      const data = await res.json()
      setImportResult(
        `Imported ${data.imported.conversations} conversations with ${data.imported.messages} messages` +
        (data.skipped > 0 ? ` (${data.skipped} empty skipped)` : '')
      )
    } catch (err) {
      setImportError(err instanceof Error ? err.message : 'Import failed')
    } finally {
      setImporting(false)
      resetInput()
    }
  }

  /** Download the export as a ZIP */
  const handleExport = () => runExport(async () => {
    const res = await fetch('/api/data/export', {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    })
    if (!res.ok) throw new Error(`server returned ${res.status}`)

    const blob = await res.blob()
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = res.headers.get('content-disposition')?.match(/filename="(.+)"/)?.[1] || 'engram_export.zip'
    document.body.appendChild(a)
    a.click()
    a.remove()
    URL.revokeObjectURL(url)
  }, 'Export downloaded', 'Export failed')

  return (
    <div className="rounded-lg border border-dark-border/60 bg-dark-bg-secondary/50 divide-y divide-dark-border/40">
      <div className="p-4 flex items-start justify-between gap-3 flex-wrap">
        <div className="min-w-0 flex-1">
          <h4 className="text-sm font-medium text-dark-text-primary">Export your data</h4>
          <p className="text-xs text-dark-text-secondary mt-1">
            A ZIP of your conversations, notes, personas, settings and the memories you added. Not included:
            auto-learned memories, budget, schedule, documents and notifications. API keys and passwords are removed.
          </p>
          <div className="mt-1"><ActionStatus state={exportState} /></div>
        </div>
        <ActionButton onClick={handleExport} busy={exportState.status === 'busy'}>
          {exportState.status !== 'busy' && <Download size={13} />}
          {exportState.status === 'busy' ? 'Exporting…' : 'Export'}
        </ActionButton>
      </div>

      <div className="p-4 space-y-3">
        <div className="flex items-start justify-between gap-3 flex-wrap">
          <div className="min-w-0 flex-1">
            <h4 className="text-sm font-medium text-dark-text-primary">Import from ChatGPT</h4>
            <p className="text-xs text-dark-text-secondary mt-1">Your ChatGPT export (the ZIP, or its conversations.json).</p>
          </div>
          <input ref={fileRef} type="file" accept=".zip,.json" onChange={chooseFile} className="sr-only" id="chatgpt-import"
                 disabled={importing} />
          <label
            htmlFor="chatgpt-import"
            className={`inline-flex items-center justify-center gap-1.5 px-3 py-1.5 min-h-[40px] sm:min-h-0 rounded-md text-xs font-medium
                        border border-dark-border bg-dark-bg-primary text-dark-text-primary hover:border-dark-accent-primary
                        cursor-pointer transition-colors focus-within:ring-2 focus-within:ring-dark-accent-primary
                        ${importing ? 'opacity-50 cursor-wait' : ''}`}
          >
            <Upload size={13} />
            {importing ? 'Importing…' : 'Choose file…'}
          </label>
        </div>

        {pendingFile && (
          <div role="group" aria-label="Confirm import"
               className="flex flex-wrap items-center gap-2 rounded-md border border-dark-border bg-dark-bg-primary/60 px-3 py-2">
            <span className="text-xs text-dark-text-primary">
              Import “{pendingFile.name}”? Its conversations are added to yours; importing the same file twice creates duplicates.
            </span>
            <ActionButton onClick={() => { setPendingFile(null); resetInput() }}>Cancel</ActionButton>
            <ActionButton variant="primary" onClick={runImport}>Import</ActionButton>
          </div>
        )}
        {importResult && (
          <div role="status" className="p-2 rounded bg-green-500/10 border border-green-500/30 text-green-400 [.light_&]:text-green-700 text-xs flex items-center gap-2">
            <Check size={14} />
            {importResult}
          </div>
        )}
        {importError && (
          <div role="alert" className="p-2 rounded bg-red-500/10 border border-red-500/30 text-red-400 [.light_&]:text-red-700 text-xs">
            {importError}
          </div>
        )}
      </div>
    </div>
  )
}
