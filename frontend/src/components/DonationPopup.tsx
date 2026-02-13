/**
 * Donation popup component.
 * Shows every 15 messages unless the user has donated.
 * Includes PayPal donate button.
 *
 * Sticky behavior:
 * - No X close button (must use footer actions)
 * - "Maybe later" button appears after 5 second delay
 * - "I've already donated" only appears after 3 dismissals
 * - Clicking outside does nothing (modal is blocking)
 */

import { useState, useEffect } from 'react'
import { Heart, DollarSign, Clock } from 'lucide-react'
import { useDonationStore } from '../stores/donationStore'

// ============================================================
// CONFIGURE YOUR DONATION LINKS HERE
// Replace these with your actual donation URLs
// ============================================================
const PAYPAL_URL = 'https://www.paypal.com/donate/?hosted_button_id=HAUBQZQAK7QJN'

/** "I've already donated" button is always visible (no dismiss threshold) */
const DISMISS_THRESHOLD = 0

/** Seconds before the "Maybe later" button becomes clickable */
const DISMISS_DELAY_SECONDS = 5

export default function DonationPopup() {
  const { showPopup, messageCount, dismissCount, dismissPopup, markDonated } = useDonationStore()
  const [secondsLeft, setSecondsLeft] = useState(DISMISS_DELAY_SECONDS)

  // Countdown timer for the dismiss button delay
  useEffect(() => {
    if (!showPopup) {
      setSecondsLeft(DISMISS_DELAY_SECONDS)
      return
    }

    if (secondsLeft <= 0) return

    const timer = setTimeout(() => {
      setSecondsLeft(s => s - 1)
    }, 1000)

    return () => clearTimeout(timer)
  }, [showPopup, secondsLeft])

  if (!showPopup) return null

  const canDismiss = secondsLeft <= 0
  const showDonatedButton = dismissCount >= DISMISS_THRESHOLD

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
      <div className="relative mx-4 w-full max-w-md rounded-2xl bg-dark-bg-secondary border border-dark-border shadow-2xl overflow-hidden">
        {/* No X button — must use footer actions */}

        {/* Header with heart icon */}
        <div className="px-6 pt-8 pb-4 text-center">
          <div className="mx-auto mb-4 flex h-16 w-16 items-center justify-center rounded-full bg-gradient-to-br from-pink-500/20 to-red-500/20 border border-pink-500/30">
            <Heart size={32} className="text-pink-400" fill="currentColor" />
          </div>
          <h2 className="text-xl font-bold text-white mb-2">
            Enjoying Engram?
          </h2>
          <p className="text-sm text-gray-400 leading-relaxed">
            You've sent <span className="text-white font-semibold">{messageCount} messages</span> — 
            that's awesome! Engram is free and built with love. If it's been useful, 
            consider supporting development so it can keep getting better.
          </p>
        </div>

        {/* Donation button */}
        <div className="px-6 pb-4 space-y-3">
          <a
            href={PAYPAL_URL}
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center justify-center gap-2.5 w-full py-3.5 px-4 rounded-xl bg-[#0070BA] hover:bg-[#0082DB] text-white font-semibold text-sm transition-colors shadow-lg shadow-blue-500/10"
          >
            <DollarSign size={18} />
            Donate via PayPal
          </a>
        </div>

        {/* Footer actions */}
        <div className="px-6 pb-6 flex items-center justify-between">
          {canDismiss ? (
            <button
              onClick={dismissPopup}
              className="text-xs text-gray-600 hover:text-gray-400 transition-colors"
            >
              Maybe later
            </button>
          ) : (
            <span className="text-xs text-gray-600 flex items-center gap-1">
              <Clock size={12} />
              Continue in {secondsLeft}s...
            </span>
          )}

          {showDonatedButton && (
            <button
              onClick={markDonated}
              className="text-xs text-gray-600 hover:text-gray-400 transition-colors"
            >
              I've already donated
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
