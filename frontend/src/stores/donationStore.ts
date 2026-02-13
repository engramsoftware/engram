/**
 * Donation tracking store using Zustand.
 * Tracks message count and donation status to show a donation
 * popup every 50 messages unless the user has donated.
 * Persisted to localStorage so it survives page reloads.
 */

import { create } from 'zustand'
import { persist } from 'zustand/middleware'

interface DonationState {
  /** Total messages sent since install */
  messageCount: number
  /** Whether the user has marked themselves as a donor */
  hasDonated: boolean
  /** Whether the donation popup is currently visible */
  showPopup: boolean
  /** Timestamp of last popup dismissal (to avoid spamming) */
  lastDismissed: number | null
  /** How many times the user has dismissed the popup */
  dismissCount: number

  // Actions
  /** Increment message count and check if popup should show */
  incrementMessages: () => void
  /** Mark user as donor — hides popup permanently */
  markDonated: () => void
  /** Dismiss the popup (will show again after 15 more messages) */
  dismissPopup: () => void
}

/** Show donation popup every N messages */
const DONATION_INTERVAL = 15

export const useDonationStore = create<DonationState>()(
  persist(
    (set, get) => ({
      messageCount: 0,
      hasDonated: false,
      showPopup: false,
      lastDismissed: null,
      dismissCount: 0,

      incrementMessages: () => {
        const state = get()
        if (state.hasDonated) return

        const newCount = state.messageCount + 1
        const shouldShow = newCount > 0 && newCount % DONATION_INTERVAL === 0

        set({
          messageCount: newCount,
          showPopup: shouldShow,
        })
      },

      markDonated: () => set({
        hasDonated: true,
        showPopup: false,
      }),

      dismissPopup: () => set((state) => ({
        showPopup: false,
        lastDismissed: Date.now(),
        dismissCount: state.dismissCount + 1,
      })),
    }),
    {
      name: 'donation-storage',
      partialize: (state) => ({
        messageCount: state.messageCount,
        hasDonated: state.hasDonated,
        lastDismissed: state.lastDismissed,
        dismissCount: state.dismissCount,
      }),
    }
  )
)
