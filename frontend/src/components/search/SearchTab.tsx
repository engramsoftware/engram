/**
 * Search tab for searching chat history.
 */

import { useState } from 'react'
import { Search } from 'lucide-react'
import { searchApi } from '../../services/api'
import type { SearchResult } from '../../types/addin.types'

export default function SearchTab() {
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<SearchResult[]>([])
  const [isLoading, setIsLoading] = useState(false)

  const handleSearch = async () => {
    if (!query.trim()) return
    setIsLoading(true)
    try {
      const data = await searchApi.search(query)
      setResults(data)
    } catch (error) {
      console.error('Search failed:', error)
    } finally {
      setIsLoading(false)
    }
  }

  return (
    <div className="h-full flex flex-col p-6 max-w-3xl mx-auto">
      <h1 className="text-2xl font-semibold text-dark-text-primary mb-6">Search</h1>
      
      {/* Search input */}
      <div className="flex gap-3 mb-6">
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
          placeholder="Search your chat history..."
          className="flex-1 bg-dark-bg-secondary border border-dark-border rounded-lg
                     px-4 py-2 text-dark-text-primary placeholder-dark-text-secondary
                     focus:outline-none focus:border-dark-accent-primary"
        />
        <button
          onClick={handleSearch}
          disabled={isLoading}
          className="px-4 py-2 bg-dark-accent-primary hover:bg-dark-accent-hover
                     rounded-lg text-white disabled:opacity-50"
        >
          <Search size={20} />
        </button>
      </div>

      {/* Results */}
      <div className="flex-1 overflow-y-auto space-y-3">
        {results.map((result) => (
          <div
            key={result.id}
            className="p-4 bg-dark-bg-secondary rounded-lg border border-dark-border"
          >
            <div className="flex justify-between items-start mb-2">
              <span className="text-sm text-dark-accent-primary">
                {result.conversationTitle || 'Untitled'}
              </span>
              <span className="text-xs text-dark-text-secondary">
                {new Date(result.timestamp).toLocaleDateString()}
              </span>
            </div>
            <p className="text-dark-text-primary text-sm">
              {result.highlight || result.content}
            </p>
            <span className="text-xs text-dark-text-secondary mt-2 inline-block">
              Score: {result.score.toFixed(2)}
            </span>
          </div>
        ))}
        
        {results.length === 0 && query && !isLoading && (
          <p className="text-center text-dark-text-secondary">No results found</p>
        )}
      </div>
    </div>
  )
}
