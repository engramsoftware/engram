/**
 * Message input component with send button, image attach, and slash command hints.
 * Supports /note, /search commands with autocomplete suggestions.
 * Mobile responsive — stacks controls on small screens.
 */

import { useState, useRef, useEffect, KeyboardEvent } from 'react'
import { Send, Paperclip, X, Loader2, FileText, FileSpreadsheet, File as FileIcon } from 'lucide-react'
import { uploadsApi } from '../../services/api'
import type { ImageAttachment } from '../../types/chat.types'

/** Slash commands shown when user types "/" */
const SLASH_COMMANDS = [
  { cmd: '/note save', desc: 'Save last response as a note', usage: '/note save <title>' },
  { cmd: '/note list', desc: 'List your recent notes', usage: '/note list' },
  { cmd: '/note search', desc: 'Search your notes', usage: '/note search <query>' },
  { cmd: '/digest', desc: 'Daily summary of conversations', usage: '/digest' },
  { cmd: '/budget summary', desc: 'View spending summary', usage: '/budget summary' },
  { cmd: '/budget add', desc: 'Track an expense', usage: '/budget add $50 groceries lunch' },
  { cmd: '/email', desc: 'List recent emails', usage: '/email' },
  { cmd: '/email search', desc: 'Search your emails', usage: '/email search from:amazon' },
]

interface Props {
  onSend: (content: string, images?: ImageAttachment[]) => void
  disabled?: boolean
}

export default function MessageInput({ onSend, disabled }: Props) {
  const [content, setContent] = useState('')
  const [showSlashHints, setShowSlashHints] = useState(false)
  const [pendingImages, setPendingImages] = useState<ImageAttachment[]>([])
  const [uploading, setUploading] = useState(false)
  const [dragOver, setDragOver] = useState(false)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  // Auto-resize textarea as user types (up to 6 rows)
  useEffect(() => {
    const el = textareaRef.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = Math.min(el.scrollHeight, 160) + 'px'
  }, [content])

  // Show slash command hints when input starts with "/"
  useEffect(() => {
    setShowSlashHints(content.startsWith('/') && content.length < 20)
  }, [content])

  const handleSend = () => {
    if ((!content.trim() && pendingImages.length === 0) || disabled) return
    onSend(content || '(image)', pendingImages.length > 0 ? pendingImages : undefined)
    setContent('')
    setPendingImages([])
    setShowSlashHints(false)
  }

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
    if (e.key === 'Escape') {
      setShowSlashHints(false)
    }
  }

  /** Insert a slash command into the input field. */
  function selectCommand(usage: string) {
    setContent(usage)
    setShowSlashHints(false)
    textareaRef.current?.focus()
  }

  /** Upload a file and add to pending attachments. */
  async function handleFileSelect(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file) return
    if (fileInputRef.current) fileInputRef.current.value = ''

    setUploading(true)
    try {
      const result = await uploadsApi.uploadImage(file)
      setPendingImages((prev) => [
        ...prev,
        { url: result.url, filename: result.filename, content_type: result.content_type },
      ])
    } catch (err) {
      console.error('File upload failed:', err)
    } finally {
      setUploading(false)
    }
  }

  /** Remove a pending image before sending. */
  function removeImage(idx: number) {
    setPendingImages((prev) => prev.filter((_, i) => i !== idx))
  }

  /** Handle paste — auto-upload pasted images. */
  function handlePaste(e: React.ClipboardEvent) {
    const items = e.clipboardData?.items
    if (!items) return
    for (const item of items) {
      if (item.type.startsWith('image/')) {
        e.preventDefault()
        const file = item.getAsFile()
        if (file) {
          setUploading(true)
          uploadsApi.uploadImage(file)
            .then((result) => {
              setPendingImages((prev) => [
                ...prev,
                { url: result.url, filename: result.filename, content_type: result.content_type },
              ])
            })
            .catch((err) => console.error('Paste image upload failed:', err))
            .finally(() => setUploading(false))
        }
        break
      }
    }
  }

  /** Handle drag-and-drop — upload dropped images/files. */
  function handleDrop(e: React.DragEvent) {
    e.preventDefault()
    setDragOver(false)
    const files = Array.from(e.dataTransfer.files)
    for (const file of files) {
      setUploading(true)
      uploadsApi.uploadImage(file)
        .then((result) => {
          setPendingImages((prev) => [
            ...prev,
            { url: result.url, filename: result.filename, content_type: result.content_type },
          ])
        })
        .catch((err) => console.error('Drop upload failed:', err))
        .finally(() => setUploading(false))
    }
  }

  function handleDragOver(e: React.DragEvent) {
    e.preventDefault()
    setDragOver(true)
  }

  function handleDragLeave(e: React.DragEvent) {
    e.preventDefault()
    setDragOver(false)
  }

  const filteredCommands = SLASH_COMMANDS.filter((c) =>
    c.cmd.startsWith(content.trim().toLowerCase()) || content.trim() === '/'
  )

  return (
    <div
      className={`relative max-w-3xl mx-auto ${dragOver ? 'ring-2 ring-indigo-500/50 rounded-xl' : ''}`}
      onDrop={handleDrop}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
    >
      {/* Slash command hints popup */}
      {showSlashHints && filteredCommands.length > 0 && (
        <div className="absolute bottom-full left-0 mb-2 w-full sm:w-80 bg-dark-bg-secondary
                        border border-dark-border rounded-lg shadow-lg z-50 overflow-hidden">
          <div className="px-3 py-1.5 text-xs text-dark-text-secondary border-b border-dark-border">
            Commands
          </div>
          {filteredCommands.map((c) => (
            <button
              key={c.cmd}
              onClick={() => selectCommand(c.usage)}
              className="w-full flex items-center justify-between px-3 py-2 text-sm
                         hover:bg-dark-bg-primary transition-colors text-left"
            >
              <span className="font-mono text-dark-accent-primary">{c.cmd}</span>
              <span className="text-dark-text-secondary text-xs hidden sm:inline">{c.desc}</span>
            </button>
          ))}
        </div>
      )}

      {/* Pending file previews */}
      {pendingImages.length > 0 && (
        <div className="flex gap-2 mb-2 flex-wrap">
          {pendingImages.map((img, idx) => {
            const isImage = img.content_type?.startsWith('image/')
            const isPdf = img.content_type === 'application/pdf' || img.filename?.endsWith('.pdf')
            const isSpreadsheet = img.content_type?.includes('spreadsheet') || img.content_type?.includes('excel') || img.filename?.endsWith('.csv') || img.filename?.endsWith('.xlsx')
            return (
              <div
                key={img.url}
                className="relative group rounded-lg overflow-hidden
                           border border-dark-border bg-dark-bg-secondary flex-shrink-0"
              >
                {isImage ? (
                  <img
                    src={`/api${img.url}`}
                    alt={img.filename}
                    className="w-16 h-16 sm:w-20 sm:h-20 object-cover"
                  />
                ) : (
                  <div className="w-auto h-16 sm:h-20 px-3 flex items-center gap-2">
                    {isPdf ? (
                      <FileText size={20} className="text-red-400 flex-shrink-0" />
                    ) : isSpreadsheet ? (
                      <FileSpreadsheet size={20} className="text-green-400 flex-shrink-0" />
                    ) : (
                      <FileIcon size={20} className="text-blue-400 flex-shrink-0" />
                    )}
                    <span className="text-xs text-dark-text-secondary truncate max-w-[120px]">
                      {img.filename || 'File'}
                    </span>
                  </div>
                )}
                <button
                  onClick={() => removeImage(idx)}
                  className="absolute top-0.5 right-0.5 w-5 h-5 bg-black/70 rounded-full
                             flex items-center justify-center text-white
                             opacity-0 group-hover:opacity-100 sm:opacity-0 sm:group-hover:opacity-100
                             transition-opacity"
                  style={{ opacity: 1 }}
                >
                  <X size={12} />
                </button>
              </div>
            )
          })}
          {uploading && (
            <div className="w-16 h-16 sm:w-20 sm:h-20 rounded-lg border border-dark-border
                            bg-dark-bg-secondary flex items-center justify-center">
              <Loader2 size={16} className="animate-spin text-dark-text-secondary" />
            </div>
          )}
        </div>
      )}

      {/* Input row */}
      <div className="flex gap-1.5 sm:gap-2 items-end">
        {/* File attach button */}
        <button
          onClick={() => fileInputRef.current?.click()}
          disabled={disabled || uploading}
          className="p-2 sm:p-3 text-dark-text-secondary hover:text-dark-accent-primary
                     hover:bg-dark-bg-secondary rounded-xl transition-colors
                     disabled:opacity-50 flex-shrink-0"
          title="Attach file"
        >
          {uploading ? (
            <Loader2 size={20} className="animate-spin" />
          ) : (
            <Paperclip size={20} />
          )}
        </button>
        <input
          ref={fileInputRef}
          type="file"
          accept="image/jpeg,image/png,image/gif,image/webp,.pdf,.doc,.docx,.xls,.xlsx,.csv,.txt,.md,.py,.js,.ts,.json,.xml,.html,.yaml,.yml,.ppt,.pptx,.zip"
          onChange={handleFileSelect}
          className="hidden"
        />

        <textarea
          ref={textareaRef}
          value={content}
          onChange={(e) => setContent(e.target.value)}
          onKeyDown={handleKeyDown}
          onPaste={handlePaste}
          placeholder="Type a message... (/ for commands)"
          disabled={disabled}
          rows={1}
          className="flex-1 bg-dark-bg-secondary border border-dark-border rounded-xl
                     px-3 py-2.5 sm:px-4 sm:py-3 text-base
                     text-dark-text-primary placeholder-dark-text-secondary
                     resize-none focus:outline-none focus:border-dark-accent-primary
                     disabled:opacity-50"
        />
        <button
          onClick={handleSend}
          disabled={disabled || (!content.trim() && pendingImages.length === 0)}
          className="p-2.5 sm:p-3 bg-dark-accent-primary hover:bg-dark-accent-hover
                     rounded-xl text-white disabled:opacity-50 disabled:cursor-not-allowed
                     transition-colors flex-shrink-0"
        >
          <Send size={20} />
        </button>
      </div>
    </div>
  )
}
