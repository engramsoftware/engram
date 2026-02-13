/**
 * Documents management tab for RAG.
 * Upload, view, and delete documents that Engram can reference in conversations.
 */

import { useState, useEffect, useCallback, useRef } from 'react'
import {
  Upload,
  FileText,
  Trash2,
  RefreshCw,
  AlertCircle,
  CheckCircle,
  Loader2,
  File as FileIcon,
} from 'lucide-react'
import { documentsApi } from '../../services/api'

interface Document {
  id: string
  filename: string
  file_type: string
  file_size: number
  chunk_count: number
  status: 'processing' | 'ready' | 'error'
  error?: string
  tags: string[]
  created_at: string
}

/** Format bytes to human-readable size. */
function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

export default function DocumentsTab() {
  const [documents, setDocuments] = useState<Document[]>([])
  const [loading, setLoading] = useState(true)
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [dragOver, setDragOver] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)

  /** Fetch documents from the API. */
  const fetchDocuments = useCallback(async () => {
    try {
      setLoading(true)
      const data = await documentsApi.list()
      setDocuments(data)
      setError(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load documents')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchDocuments()
  }, [fetchDocuments])

  // Poll for processing documents to update their status
  useEffect(() => {
    const hasProcessing = documents.some((d) => d.status === 'processing')
    if (!hasProcessing) return

    const interval = setInterval(fetchDocuments, 3000)
    return () => clearInterval(interval)
  }, [documents, fetchDocuments])

  /** Upload a file. */
  async function handleUpload(file: File) {
    setUploading(true)
    setError(null)
    try {
      await documentsApi.upload(file)
      await fetchDocuments()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Upload failed')
    } finally {
      setUploading(false)
    }
  }

  /** Delete a document. */
  async function handleDelete(id: string, filename: string) {
    if (!confirm(`Delete "${filename}"? This will remove it from Engram's knowledge.`)) return
    try {
      await documentsApi.delete(id)
      setDocuments((prev) => prev.filter((d) => d.id !== id))
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Delete failed')
    }
  }

  /** Handle file input change. */
  function onFileSelect(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (file) handleUpload(file)
    if (fileInputRef.current) fileInputRef.current.value = ''
  }

  /** Handle drag-and-drop. */
  function onDrop(e: React.DragEvent) {
    e.preventDefault()
    setDragOver(false)
    const file = e.dataTransfer.files?.[0]
    if (file) handleUpload(file)
  }

  /** Status badge for a document. */
  function StatusBadge({ doc }: { doc: Document }) {
    if (doc.status === 'processing') {
      return (
        <span className="flex items-center gap-1 text-xs text-yellow-400">
          <Loader2 size={12} className="animate-spin" /> Processing...
        </span>
      )
    }
    if (doc.status === 'error') {
      return (
        <span className="flex items-center gap-1 text-xs text-red-400" title={doc.error}>
          <AlertCircle size={12} /> Error
        </span>
      )
    }
    return (
      <span className="flex items-center gap-1 text-xs text-green-400">
        <CheckCircle size={12} /> {doc.chunk_count} chunks
      </span>
    )
  }

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="border-b border-dark-border px-4 sm:px-6 py-3 sm:py-4">
        <div className="flex items-center justify-between gap-2">
          <div className="min-w-0">
            <h1 className="text-base sm:text-lg font-semibold text-dark-text-primary">Documents</h1>
            <p className="text-xs sm:text-sm text-dark-text-secondary mt-0.5 line-clamp-2">
              Upload files for Engram to reference. Only relevant content is retrieved.
            </p>
          </div>
          <button
            onClick={fetchDocuments}
            className="p-2 text-dark-text-secondary hover:text-dark-text-primary
                       hover:bg-dark-bg-secondary rounded-lg transition-colors flex-shrink-0"
            title="Refresh"
          >
            <RefreshCw size={16} />
          </button>
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-4 sm:p-6">
        {/* Upload zone */}
        <div
          onDragOver={(e) => { e.preventDefault(); setDragOver(true) }}
          onDragLeave={() => setDragOver(false)}
          onDrop={onDrop}
          onClick={() => fileInputRef.current?.click()}
          className={`border-2 border-dashed rounded-xl p-8 text-center cursor-pointer
                      transition-colors mb-6
                      ${dragOver
                        ? 'border-dark-accent-primary bg-dark-accent-primary/10'
                        : 'border-dark-border hover:border-dark-text-secondary'
                      }
                      ${uploading ? 'opacity-50 pointer-events-none' : ''}`}
        >
          <input
            ref={fileInputRef}
            type="file"
            onChange={onFileSelect}
            accept=".txt,.md,.pdf,.docx,.csv,.json,.yaml,.yml,.log,.rst"
            className="hidden"
          />
          {uploading ? (
            <div className="flex flex-col items-center gap-2">
              <Loader2 size={32} className="text-dark-accent-primary animate-spin" />
              <p className="text-sm text-dark-text-secondary">Uploading & processing...</p>
            </div>
          ) : (
            <div className="flex flex-col items-center gap-2">
              <Upload size={32} className="text-dark-text-secondary" />
              <p className="text-sm text-dark-text-primary font-medium">
                Drop a file here or click to upload
              </p>
              <p className="text-xs text-dark-text-secondary">
                PDF, TXT, Markdown, DOCX, CSV, JSON, YAML — up to 20 MB
              </p>
            </div>
          )}
        </div>

        {/* Error banner */}
        {error && (
          <div className="flex items-center gap-2 px-4 py-3 mb-4 rounded-lg
                          bg-red-500/10 border border-red-500/30 text-red-400 text-sm">
            <AlertCircle size={16} />
            <span>{error}</span>
            <button onClick={() => setError(null)} className="ml-auto text-xs hover:text-red-300">
              Dismiss
            </button>
          </div>
        )}

        {/* Document list */}
        {loading && documents.length === 0 ? (
          <div className="flex items-center justify-center py-12 text-dark-text-secondary">
            <Loader2 size={20} className="animate-spin mr-2" />
            Loading documents...
          </div>
        ) : documents.length === 0 ? (
          <div className="text-center py-12 text-dark-text-secondary">
            <FileText size={40} className="mx-auto mb-3 opacity-40" />
            <p className="text-sm">No documents yet.</p>
            <p className="text-xs mt-1">Upload files to give Engram knowledge to reference.</p>
          </div>
        ) : (
          <div className="space-y-2">
            {documents.map((doc) => (
              <div
                key={doc.id}
                className="flex items-center gap-3 px-4 py-3 rounded-lg
                           bg-dark-bg-secondary border border-dark-border
                           hover:border-dark-text-secondary/30 transition-colors"
              >
                {/* Icon */}
                <div className="w-9 h-9 rounded-lg bg-dark-bg-primary flex items-center justify-center flex-shrink-0">
                  <FileIcon size={18} className="text-dark-accent-primary" />
                </div>

                {/* Info */}
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium text-dark-text-primary truncate">
                    {doc.filename}
                  </p>
                  <div className="flex items-center gap-3 mt-0.5">
                    <span className="text-xs text-dark-text-secondary">
                      {formatSize(doc.file_size)}
                    </span>
                    <span className="text-xs text-dark-text-secondary uppercase">
                      {doc.file_type}
                    </span>
                    <StatusBadge doc={doc} />
                  </div>
                </div>

                {/* Delete */}
                <button
                  onClick={() => handleDelete(doc.id, doc.filename)}
                  className="p-2 text-dark-text-secondary hover:text-red-400
                             hover:bg-red-500/10 rounded-lg transition-colors"
                  title="Delete document"
                >
                  <Trash2 size={16} />
                </button>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
