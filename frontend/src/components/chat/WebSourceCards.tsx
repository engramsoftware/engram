/**
 * Perplexity-style web source cards for search results.
 *
 * Displays detailed source cards above the assistant response when
 * web search was used. Each card shows favicon, title, domain,
 * description, and age. Cards are always visible with full detail.
 * Collapsible section shows/hides additional sources beyond the
 * first 3. Follows the "multi-source references" citation pattern
 * from ShapeofAI research.
 *
 * @param sources - Array of web search results from Brave Search API
 */

import { useState } from 'react'
import { ChevronDown, ChevronUp, ExternalLink, Search } from 'lucide-react'
import type { WebSource } from '../../types/chat.types'

interface Props {
  sources: WebSource[]
}

/** Extract domain from a URL for display. */
function getDomain(url: string): string {
  try {
    return new URL(url).hostname.replace('www.', '')
  } catch {
    return url
  }
}

/** Build a Google favicon proxy URL for a domain. */
function getFaviconUrl(url: string): string {
  const domain = getDomain(url)
  return `https://www.google.com/s2/favicons?domain=${domain}&sz=32`
}

export default function WebSourceCards({ sources }: Props) {
  const [isExpanded, setIsExpanded] = useState(false)

  if (!sources || sources.length === 0) return null

  const visible = isExpanded ? sources : sources.slice(0, 3)
  const hasMore = sources.length > 3

  return (
    <div className="mb-4 rounded-xl border border-dark-border/40 bg-dark-bg-secondary/20 overflow-hidden">
      {/* Header bar */}
      <div className="flex items-center gap-2 px-3.5 py-2.5 border-b border-dark-border/30
                      bg-gradient-to-r from-indigo-500/5 to-purple-500/5">
        <div className="flex items-center justify-center w-5 h-5 rounded-md bg-indigo-500/15">
          <Search size={11} className="text-indigo-400" />
        </div>
        <span className="text-xs font-semibold text-dark-text-primary">
          Web Search
        </span>
        <span className="text-[10px] text-dark-text-secondary px-1.5 py-0.5 rounded-full
                         bg-dark-bg-secondary/60 border border-dark-border/30">
          {sources.length} source{sources.length !== 1 ? 's' : ''}
        </span>
      </div>

      {/* Source cards */}
      <div className="divide-y divide-dark-border/20">
        {visible.map((source, idx) => (
          <SourceCard key={idx} source={source} index={idx + 1} />
        ))}
      </div>

      {/* Expand/collapse toggle */}
      {hasMore && (
        <button
          onClick={() => setIsExpanded(!isExpanded)}
          className="w-full flex items-center justify-center gap-1.5 py-2
                     text-xs text-dark-text-secondary hover:text-indigo-400
                     hover:bg-dark-bg-secondary/30 transition-colors
                     border-t border-dark-border/20"
        >
          {isExpanded ? (
            <>
              <ChevronUp size={13} />
              Show fewer sources
            </>
          ) : (
            <>
              <ChevronDown size={13} />
              Show {sources.length - 3} more source{sources.length - 3 !== 1 ? 's' : ''}
            </>
          )}
        </button>
      )}
    </div>
  )
}


/**
 * Individual source card — always shows title, description, domain,
 * favicon, age, and a link to the source. Detailed by default.
 */
function SourceCard({ source, index }: { source: WebSource; index: number }) {
  const domain = getDomain(source.url)

  return (
    <div className="group px-3.5 py-3 hover:bg-dark-bg-secondary/20 transition-colors">
      <div className="flex gap-3">
        {/* Index + favicon column */}
        <div className="flex flex-col items-center gap-1.5 pt-0.5">
          <span className="flex-shrink-0 w-5 h-5 rounded-md bg-indigo-500/15
                           text-indigo-400 text-[10px] font-bold flex items-center
                           justify-center">
            {index}
          </span>
          <img
            src={getFaviconUrl(source.url)}
            alt=""
            className="w-4 h-4 rounded-sm flex-shrink-0"
            onError={(e) => {
              (e.target as HTMLImageElement).style.display = 'none'
            }}
          />
        </div>

        {/* Content column */}
        <div className="flex-1 min-w-0">
          {/* Title row */}
          <a
            href={source.url}
            target="_blank"
            rel="noopener noreferrer"
            className="group/link flex items-start gap-1.5"
          >
            <h4 className="text-sm font-medium text-dark-text-primary leading-snug
                           group-hover/link:text-indigo-400 transition-colors line-clamp-2">
              {source.title || domain}
            </h4>
            <ExternalLink size={11} className="flex-shrink-0 mt-1 text-dark-text-secondary/40
                                                group-hover/link:text-indigo-400 transition-colors" />
          </a>

          {/* Domain + age row */}
          <div className="flex items-center gap-2 mt-1">
            <span className="text-[11px] text-dark-text-secondary/70 truncate">
              {domain}
            </span>
            {source.age && (
              <>
                <span className="text-dark-text-secondary/30">·</span>
                <span className="text-[11px] text-dark-text-secondary/50 flex-shrink-0">
                  {source.age}
                </span>
              </>
            )}
          </div>

          {/* Description */}
          {source.description && (
            <p className="mt-1.5 text-xs text-dark-text-secondary/80 leading-relaxed line-clamp-3">
              {source.description}
            </p>
          )}
        </div>
      </div>
    </div>
  )
}
