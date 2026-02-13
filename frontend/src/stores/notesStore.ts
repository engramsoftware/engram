/**
 * Notes state management using Zustand.
 * Handles the knowledge base / notes system state.
 */

import { create } from 'zustand'
import type { Note } from '../types/notes.types'
import { notesApi } from '../services/api'

interface NotesState {
  /** All notes fetched from backend (flat list) */
  notes: Note[]
  /** Currently selected/open note */
  activeNote: Note | null
  /** Currently expanded folder IDs in the tree */
  expandedFolders: Set<string>
  /** Loading state */
  isLoading: boolean
  /** Search query for filtering */
  searchQuery: string
  /** Unsaved changes flag */
  isDirty: boolean

  // Actions
  fetchNotes: () => Promise<void>
  setActiveNote: (note: Note | null) => void
  createNote: (data: { title?: string; content?: string; parent_id?: string | null; tags?: string[]; is_folder?: boolean }) => Promise<Note>
  updateNote: (id: string, data: { title?: string; content?: string; tags?: string[]; is_pinned?: boolean }) => Promise<void>
  deleteNote: (id: string) => Promise<void>
  toggleFolder: (folderId: string) => void
  setSearchQuery: (query: string) => void
  setDirty: (dirty: boolean) => void
}

export const useNotesStore = create<NotesState>((set, get) => ({
  notes: [],
  activeNote: null,
  expandedFolders: new Set(),
  isLoading: false,
  searchQuery: '',
  isDirty: false,

  fetchNotes: async () => {
    set({ isLoading: true })
    try {
      const data = await notesApi.listAll()
      set({ notes: data, isLoading: false })
    } catch (error) {
      console.error('Failed to fetch notes:', error)
      set({ isLoading: false })
    }
  },

  setActiveNote: (note) => set({ activeNote: note, isDirty: false }),

  createNote: async (data) => {
    const note = await notesApi.create(data)
    // Refresh the full list to get correct child counts
    await get().fetchNotes()
    set({ activeNote: note })
    // Auto-expand parent folder if creating inside one
    if (data.parent_id) {
      set((state) => {
        const expanded = new Set(state.expandedFolders)
        expanded.add(data.parent_id!)
        return { expandedFolders: expanded }
      })
    }
    return note
  },

  updateNote: async (id, data) => {
    const updated = await notesApi.update(id, data)
    set((state) => ({
      notes: state.notes.map((n) => (n.id === id ? updated : n)),
      activeNote: state.activeNote?.id === id ? updated : state.activeNote,
      isDirty: false,
    }))
  },

  deleteNote: async (id) => {
    await notesApi.delete(id)
    set((state) => ({
      notes: state.notes.filter((n) => n.id !== id),
      activeNote: state.activeNote?.id === id ? null : state.activeNote,
    }))
  },

  toggleFolder: (folderId) =>
    set((state) => {
      const expanded = new Set(state.expandedFolders)
      if (expanded.has(folderId)) {
        expanded.delete(folderId)
      } else {
        expanded.add(folderId)
      }
      return { expandedFolders: expanded }
    }),

  setSearchQuery: (query) => set({ searchQuery: query }),

  setDirty: (dirty) => set({ isDirty: dirty }),
}))
