/**
 * Notes tab — Obsidian-like knowledge base.
 * Split-pane layout: folder tree (left) + markdown editor (right).
 * Both the user and the LLM (Engram) can create and edit notes.
 */

import { useEffect, useState } from 'react'
import {
  FolderPlus,
  FilePlus,
  Search,
  Save,
  Trash2,
  Pin,
  PinOff,
  ChevronRight,
  ChevronDown,
  ChevronLeft,
  Folder,
  FolderOpen,
  FileText,
  Tag,
  Bot,
  User,
  Loader2,
} from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import { useNotesStore } from '../../stores/notesStore'
import type { Note } from '../../types/notes.types'

export default function NotesTab() {
  const {
    notes,
    activeNote,
    expandedFolders,
    isLoading,
    searchQuery,
    isDirty,
    fetchNotes,
    setActiveNote,
    createNote,
    updateNote,
    deleteNote,
    toggleFolder,
    setSearchQuery,
    setDirty,
  } = useNotesStore()

  const [editTitle, setEditTitle] = useState('')
  const [editContent, setEditContent] = useState('')
  const [editTags, setEditTags] = useState('')
  const [isPreview, setIsPreview] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null)
  // Mobile: show list or editor (not both). True = show editor panel.
  const [mobileShowEditor, setMobileShowEditor] = useState(false)

  // Fetch notes on mount
  useEffect(() => {
    fetchNotes()
  }, [fetchNotes])

  // Sync editor state when active note changes
  useEffect(() => {
    if (activeNote) {
      setEditTitle(activeNote.title)
      setEditContent(activeNote.content)
      setEditTags(activeNote.tags.join(', '))
      setIsPreview(false)
    }
  }, [activeNote?.id])

  // Filter notes by search query
  const filteredNotes = searchQuery
    ? notes.filter(
        (n) =>
          n.title.toLowerCase().includes(searchQuery.toLowerCase()) ||
          n.content.toLowerCase().includes(searchQuery.toLowerCase()) ||
          n.tags.some((t) => t.toLowerCase().includes(searchQuery.toLowerCase()))
      )
    : notes

  // Build tree structure: root notes have no parent_id
  const rootNotes = filteredNotes.filter((n) => !n.parent_id)
  const getChildren = (parentId: string) =>
    filteredNotes.filter((n) => n.parent_id === parentId)

  /** Save the current note edits to the backend. */
  async function handleSave() {
    if (!activeNote) return
    const tags = editTags
      .split(',')
      .map((t) => t.trim())
      .filter(Boolean)
    await updateNote(activeNote.id, {
      title: editTitle,
      content: editContent,
      tags,
    })
  }

  /** Create a new note at root or inside the active folder. */
  async function handleNewNote() {
    const parentId =
      activeNote?.is_folder ? activeNote.id : activeNote?.parent_id || null
    await createNote({ title: 'Untitled', content: '', parent_id: parentId })
  }

  /** Create a new folder at root or inside the active folder. */
  async function handleNewFolder() {
    const parentId =
      activeNote?.is_folder ? activeNote.id : activeNote?.parent_id || null
    await createNote({
      title: 'New Folder',
      content: '',
      parent_id: parentId,
      is_folder: true,
    })
  }

  /** Delete with confirmation. */
  async function handleDelete(noteId: string) {
    if (confirmDelete === noteId) {
      await deleteNote(noteId)
      setConfirmDelete(null)
    } else {
      setConfirmDelete(noteId)
      // Auto-cancel after 3 seconds
      setTimeout(() => setConfirmDelete(null), 3000)
    }
  }

  /** Render a single tree node (note or folder). */
  function TreeNode({ note, depth = 0 }: { note: Note; depth?: number }) {
    const isExpanded = expandedFolders.has(note.id)
    const children = getChildren(note.id)
    const isActive = activeNote?.id === note.id

    return (
      <div>
        <button
          onClick={() => {
            if (note.is_folder) {
              toggleFolder(note.id)
            }
            setActiveNote(note)
            // On mobile, switch to editor view when a note is tapped
            if (!note.is_folder) setMobileShowEditor(true)
          }}
          className={`w-full flex items-center gap-1.5 px-2 py-1.5 text-sm rounded-md
                     transition-colors group
                     ${isActive
                       ? 'bg-dark-accent-primary/20 text-dark-text-primary'
                       : 'text-dark-text-secondary hover:bg-dark-bg-secondary hover:text-dark-text-primary'
                     }`}
          style={{ paddingLeft: `${depth * 16 + 8}px` }}
        >
          {/* Expand/collapse icon for folders */}
          {note.is_folder ? (
            <span className="w-4 flex-shrink-0">
              {isExpanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
            </span>
          ) : (
            <span className="w-4 flex-shrink-0" />
          )}

          {/* Icon */}
          {note.is_folder ? (
            isExpanded ? (
              <FolderOpen size={15} className="text-yellow-500 flex-shrink-0" />
            ) : (
              <Folder size={15} className="text-yellow-500 flex-shrink-0" />
            )
          ) : (
            <FileText size={15} className="text-dark-text-secondary flex-shrink-0" />
          )}

          {/* Title */}
          <span className="truncate flex-1 text-left">{note.title}</span>

          {/* Indicators */}
          {note.is_pinned && <Pin size={12} className="text-dark-accent-primary flex-shrink-0" />}
          {note.last_edited_by === 'assistant' && (
            <span title="Edited by Engram"><Bot size={12} className="text-blue-400 flex-shrink-0" /></span>
          )}
        </button>

        {/* Children (if folder is expanded) */}
        {note.is_folder && isExpanded && children.length > 0 && (
          <div>
            {children.map((child) => (
              <TreeNode key={child.id} note={child} depth={depth + 1} />
            ))}
          </div>
        )}
      </div>
    )
  }

  return (
    <div className="flex h-full">
      {/* ============================================ */}
      {/* Left Panel: Folder Tree */}
      {/* On mobile: hidden when editor is open */}
      {/* ============================================ */}
      <div className={`w-full md:w-64 flex-shrink-0 border-r border-dark-border flex flex-col bg-dark-bg-tertiary
                       ${mobileShowEditor ? 'hidden md:flex' : 'flex'}`}>
        {/* Toolbar */}
        <div className="p-2 border-b border-dark-border flex items-center gap-1">
          <button
            onClick={handleNewNote}
            className="p-1.5 rounded hover:bg-dark-bg-secondary text-dark-text-secondary
                       hover:text-dark-text-primary transition-colors"
            title="New Note"
          >
            <FilePlus size={16} />
          </button>
          <button
            onClick={handleNewFolder}
            className="p-1.5 rounded hover:bg-dark-bg-secondary text-dark-text-secondary
                       hover:text-dark-text-primary transition-colors"
            title="New Folder"
          >
            <FolderPlus size={16} />
          </button>
        </div>

        {/* Search */}
        <div className="p-2 border-b border-dark-border">
          <div className="relative">
            <Search size={14} className="absolute left-2 top-1/2 -translate-y-1/2 text-dark-text-secondary" />
            <input
              type="text"
              placeholder="Search notes..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full pl-7 pr-2 py-1.5 text-sm bg-dark-bg-primary border border-dark-border
                         rounded text-dark-text-primary placeholder-dark-text-secondary
                         focus:outline-none focus:border-dark-accent-primary"
            />
          </div>
        </div>

        {/* Tree */}
        <div className="flex-1 overflow-y-auto p-1">
          {isLoading ? (
            <div className="flex items-center justify-center py-8">
              <Loader2 size={20} className="animate-spin text-dark-text-secondary" />
            </div>
          ) : rootNotes.length === 0 ? (
            <div className="text-center py-8 text-dark-text-secondary text-sm">
              <FileText size={32} className="mx-auto mb-2 opacity-50" />
              <p>No notes yet</p>
              <p className="text-xs mt-1">Create one to get started</p>
            </div>
          ) : (
            rootNotes.map((note) => <TreeNode key={note.id} note={note} />)
          )}
        </div>
      </div>

      {/* ============================================ */}
      {/* Right Panel: Editor / Preview */}
      {/* On mobile: hidden when list is showing */}
      {/* ============================================ */}
      <div className={`flex-1 flex flex-col overflow-hidden
                       ${mobileShowEditor ? 'flex' : 'hidden md:flex'}`}>
        {activeNote ? (
          <>
            {/* Editor Toolbar */}
            <div className="flex items-center justify-between px-2 sm:px-4 py-2 border-b border-dark-border bg-dark-bg-secondary">
              <div className="flex items-center gap-1 sm:gap-2">
                {/* Mobile back button — return to notes list */}
                <button
                  onClick={() => setMobileShowEditor(false)}
                  className="md:hidden p-1.5 rounded hover:bg-dark-bg-primary text-dark-text-secondary
                             hover:text-dark-text-primary transition-colors"
                  title="Back to list"
                >
                  <ChevronLeft size={18} />
                </button>
                {/* Edit / Preview toggle */}
                <button
                  onClick={() => setIsPreview(false)}
                  className={`px-3 py-1 text-sm rounded transition-colors
                             ${!isPreview
                               ? 'bg-dark-accent-primary text-white'
                               : 'text-dark-text-secondary hover:text-dark-text-primary'
                             }`}
                >
                  Edit
                </button>
                <button
                  onClick={() => setIsPreview(true)}
                  className={`px-3 py-1 text-sm rounded transition-colors
                             ${isPreview
                               ? 'bg-dark-accent-primary text-white'
                               : 'text-dark-text-secondary hover:text-dark-text-primary'
                             }`}
                >
                  Preview
                </button>

                {isDirty && (
                  <span className="text-xs text-yellow-500 ml-2">Unsaved changes</span>
                )}

                {/* Who last edited */}
                <span className="flex items-center gap-1 text-xs text-dark-text-secondary ml-2">
                  {activeNote.last_edited_by === 'assistant' ? (
                    <>
                      <Bot size={12} className="text-blue-400" />
                      Engram
                    </>
                  ) : (
                    <>
                      <User size={12} />
                      You
                    </>
                  )}
                </span>
              </div>

              <div className="flex items-center gap-1">
                {/* Pin */}
                <button
                  onClick={() =>
                    updateNote(activeNote.id, { is_pinned: !activeNote.is_pinned })
                  }
                  className="p-1.5 rounded hover:bg-dark-bg-primary text-dark-text-secondary
                             hover:text-dark-text-primary transition-colors"
                  title={activeNote.is_pinned ? 'Unpin' : 'Pin'}
                >
                  {activeNote.is_pinned ? <PinOff size={16} /> : <Pin size={16} />}
                </button>

                {/* Save */}
                <button
                  onClick={handleSave}
                  disabled={!isDirty}
                  className={`p-1.5 rounded transition-colors
                             ${isDirty
                               ? 'text-dark-accent-primary hover:bg-dark-bg-primary'
                               : 'text-dark-text-secondary/30 cursor-not-allowed'
                             }`}
                  title="Save (Ctrl+S)"
                >
                  <Save size={16} />
                </button>

                {/* Delete */}
                <button
                  onClick={() => handleDelete(activeNote.id)}
                  className={`p-1.5 rounded transition-colors
                             ${confirmDelete === activeNote.id
                               ? 'text-red-500 bg-red-500/10'
                               : 'text-dark-text-secondary hover:bg-dark-bg-primary hover:text-red-400'
                             }`}
                  title={confirmDelete === activeNote.id ? 'Click again to confirm' : 'Delete'}
                >
                  <Trash2 size={16} />
                </button>
              </div>
            </div>

            {/* Title */}
            <div className="px-4 pt-4">
              {isPreview ? (
                <h1 className="text-2xl font-bold text-dark-text-primary">{editTitle}</h1>
              ) : (
                <input
                  type="text"
                  value={editTitle}
                  onChange={(e) => {
                    setEditTitle(e.target.value)
                    setDirty(true)
                  }}
                  className="w-full text-2xl font-bold bg-transparent text-dark-text-primary
                             border-none outline-none placeholder-dark-text-secondary"
                  placeholder="Note title..."
                />
              )}
            </div>

            {/* Tags */}
            <div className="px-4 py-2 flex items-center gap-2">
              <Tag size={14} className="text-dark-text-secondary flex-shrink-0" />
              {isPreview ? (
                <div className="flex flex-wrap gap-1">
                  {activeNote.tags.length > 0 ? (
                    activeNote.tags.map((tag) => (
                      <span
                        key={tag}
                        className="px-2 py-0.5 text-xs rounded-full bg-dark-accent-primary/20
                                   text-dark-accent-primary"
                      >
                        {tag}
                      </span>
                    ))
                  ) : (
                    <span className="text-xs text-dark-text-secondary italic">No tags</span>
                  )}
                </div>
              ) : (
                <input
                  type="text"
                  value={editTags}
                  onChange={(e) => {
                    setEditTags(e.target.value)
                    setDirty(true)
                  }}
                  className="flex-1 text-sm bg-transparent text-dark-text-primary
                             border-none outline-none placeholder-dark-text-secondary"
                  placeholder="Tags (comma separated)..."
                />
              )}
            </div>

            {/* Content */}
            <div className="flex-1 overflow-y-auto px-4 pb-4">
              {isPreview ? (
                <div className="prose prose-invert prose-sm max-w-none">
                  <ReactMarkdown>{editContent || '*Empty note*'}</ReactMarkdown>
                </div>
              ) : (
                <textarea
                  value={editContent}
                  onChange={(e) => {
                    setEditContent(e.target.value)
                    setDirty(true)
                  }}
                  onKeyDown={(e) => {
                    // Ctrl+S to save
                    if (e.ctrlKey && e.key === 's') {
                      e.preventDefault()
                      handleSave()
                    }
                  }}
                  className="w-full h-full min-h-[300px] bg-transparent text-dark-text-primary
                             text-sm font-mono leading-relaxed resize-none
                             border-none outline-none placeholder-dark-text-secondary"
                  placeholder="Write your note in Markdown..."
                />
              )}
            </div>
          </>
        ) : (
          /* Empty state */
          <div className="flex-1 flex items-center justify-center">
            <div className="text-center text-dark-text-secondary">
              <FileText size={48} className="mx-auto mb-4 opacity-30" />
              <p className="text-lg font-medium">Select a note or create one</p>
              <p className="text-sm mt-1 opacity-70">
                Your personal knowledge base — you and Engram can both edit
              </p>
              <div className="flex gap-2 justify-center mt-4">
                <button
                  onClick={handleNewNote}
                  className="flex items-center gap-1.5 px-3 py-2 rounded-lg
                             bg-dark-accent-primary hover:bg-dark-accent-hover
                             text-white text-sm transition-colors"
                >
                  <FilePlus size={16} />
                  New Note
                </button>
                <button
                  onClick={handleNewFolder}
                  className="flex items-center gap-1.5 px-3 py-2 rounded-lg
                             bg-dark-bg-secondary hover:bg-dark-bg-tertiary
                             text-dark-text-primary text-sm border border-dark-border
                             transition-colors"
                >
                  <FolderPlus size={16} />
                  New Folder
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
