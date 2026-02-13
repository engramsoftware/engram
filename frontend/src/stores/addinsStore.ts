/**
 * Addins state management using Zustand.
 * Tracks enabled addins and provides GUI addin tabs for the sidebar.
 */

import { create } from 'zustand'
import { addinsApi } from '../services/api'
import type { Addin } from '../types/addin.types'

interface AddinsState {
  /** All addins from the backend. */
  addins: Addin[]
  /** Whether initial fetch has completed. */
  loaded: boolean
  /** Fetch addins from the API. */
  fetchAddins: () => Promise<void>
  /** Get only enabled GUI/hybrid addins (ones that register sidebar tabs). */
  guiAddins: () => Addin[]
}

export const useAddinsStore = create<AddinsState>((set, get) => ({
  addins: [],
  loaded: false,

  fetchAddins: async () => {
    try {
      const data = await addinsApi.list()
      set({ addins: data, loaded: true })
    } catch {
      set({ loaded: true })
    }
  },

  guiAddins: () => {
    return get().addins.filter(
      (a) => a.enabled && (a.addin_type === 'gui' || a.addin_type === 'hybrid')
    )
  },
}))
