/**
 * Chat message component — modern full-width layout with syntax highlighting.
 *
 * @param message - The message to display
 * @param isThinking - When true, shows a pulsing indicator while waiting for first stream chunk
 */

import { useState, useCallback } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter'
import { oneDark } from 'react-syntax-highlighter/dist/esm/styles/prism'
import { Copy, Check, ChevronDown, Brain, Globe, BookOpen, Network, Search, AlertTriangle, Eye } from 'lucide-react'
import type { Message } from '../../types/chat.types'
import WebSourceCards from './WebSourceCards'
import NotificationCards from './NotificationCards'
import ArtifactPanel from './ArtifactPanel'

interface Props {
  message: Message
  isThinking?: boolean
}

/** Copy text to clipboard and show a brief checkmark. */
function useCopyToClipboard(): [boolean, (text: string) => void] {
  const [copied, setCopied] = useState(false)
  const copy = useCallback((text: string) => {
    navigator.clipboard.writeText(text)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }, [])
  return [copied, copy]
}

export default function MessageBubble({ message, isThinking = false }: Props) {
  const isUser = message.role === 'user'
  const showThinking = isThinking && !isUser && !message.content
  const [copied, copyToClipboard] = useCopyToClipboard()
  const [contextOpen, setContextOpen] = useState(false)
  const [artifact, setArtifact] = useState<{ code: string; language: string } | null>(null)
  const ctx = message.context_metadata

  /** Languages that can be rendered live in the artifact panel. */
  const RENDERABLE_LANGS = ['html', 'svg', 'mermaid']

  // MongoDB stores UTC timestamps without 'Z' suffix — append it so
  // the browser correctly interprets them as UTC before converting to local.
  const ts = message.timestamp.endsWith('Z') ? message.timestamp : message.timestamp + 'Z'
  const timeStr = new Date(ts).toLocaleTimeString([], {
    hour: '2-digit',
    minute: '2-digit',
  })

  const hasImages = isUser && message.images && message.images.length > 0
  return (
    <div className="group py-2 sm:py-3">
      <div className={`max-w-3xl mx-auto px-3 sm:px-4 flex ${isUser ? 'justify-end' : ''}`}>
        {/* You: a bubble on the right. Engram: plain text across the column, no avatar. */}
        <div
          title={isUser ? timeStr : undefined}
          className={isUser
            ? 'max-w-[85%] min-w-0 rounded-2xl bg-dark-bg-secondary px-4 py-2.5'
            : 'w-full min-w-0'}
        >
          {/* Attached images */}
          {hasImages && (
            <div className="flex gap-2 mb-2 flex-wrap">
              {message.images!.map((img, idx) => (
                <a
                  key={idx}
                  href={`/api${img.url}`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="block rounded-lg overflow-hidden border border-dark-border
                             hover:border-dark-accent-primary transition-colors"
                >
                  <img
                    src={`/api${img.url}`}
                    alt={img.filename || 'Attached image'}
                    className="max-w-[200px] sm:max-w-[280px] max-h-[200px] sm:max-h-[280px]
                               object-cover rounded-lg"
                    loading="lazy"
                  />
                </a>
              ))}
            </div>
          )}

          {/* Web search source cards (Perplexity-style, above response) */}
          {!isUser && message.web_sources && message.web_sources.length > 0 && (
            <WebSourceCards sources={message.web_sources} />
          )}

          {/* Notification confirmation cards (below sources, above body) */}
          {!isUser && message.notifications && message.notifications.length > 0 && (
            <NotificationCards notifications={message.notifications} />
          )}

          {/* Body */}
          {showThinking ? (
            <div className="flex items-center gap-2.5 py-2" role="status" aria-label="Thinking">
              <div className="flex gap-1" aria-hidden>
                <span className="typing-dot" />
                <span className="typing-dot" />
                <span className="typing-dot" />
              </div>
              <span className="text-sm text-dark-text-secondary">Thinking</span>
            </div>
          ) : (
            <div className="md-content">
              <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                components={{
                  img({ src, alt, ...props }) {
                    return (
                      <figure className="my-4">
                        <img
                          src={src}
                          alt={alt || 'Research image'}
                          loading="lazy"
                          referrerPolicy="no-referrer"
                          className="rounded-lg border border-dark-border max-w-full max-h-[350px] object-contain mx-auto shadow-lg"
                          onError={(e) => {
                            const el = e.target as HTMLImageElement
                            el.parentElement!.style.display = 'none'
                          }}
                          {...props}
                        />
                        {alt && alt !== 'Image' && alt !== 'Research image' && (
                          <figcaption className="text-xs text-dark-text-secondary text-center mt-2 italic">
                            {alt}
                          </figcaption>
                        )}
                      </figure>
                    )
                  },
                  pre({ node, children, ...props }) {
                    // Fenced blocks with a language render their own framed container
                    // (see `code` below); skip the <pre> wrapper so they aren't boxed twice.
                    const first = node?.children[0]
                    const cls = first && first.type === 'element' ? first.properties?.className : undefined
                    if (Array.isArray(cls) && cls.some(c => String(c).startsWith('language-'))) {
                      return <>{children}</>
                    }
                    return <pre {...props}>{children}</pre>
                  },
                  code({ node, className, children, ...props }) {  // keep `node` out of the DOM attributes
                    const match = /language-(\w+)/.exec(className || '')
                    const codeStr = String(children).replace(/\n$/, '')

                    // Inline code (no language class)
                    if (!match) {
                      return (
                        <code className={className} {...props}>
                          {children}
                        </code>
                      )
                    }

                    // Code block with syntax highlighting
                    return (
                      <div className="relative group/code rounded-lg overflow-hidden border border-dark-border my-3">
                        {/* Language label + copy button */}
                        <div className="flex items-center justify-between px-4 py-1.5 bg-[#18181b] border-b border-white/10">
                          <span className="text-xs text-gray-400 font-mono">
                            {match[1]}
                          </span>
                          <div className="flex items-center gap-2">
                            {RENDERABLE_LANGS.includes(match[1].toLowerCase()) && (
                              <button
                                onClick={() => setArtifact({ code: codeStr, language: match[1] })}
                                className="flex items-center gap-1 text-xs text-indigo-400
                                           hover:text-indigo-300 transition-colors"
                              >
                                <Eye size={12} />
                                <span>Preview</span>
                              </button>
                            )}
                            <button
                              onClick={() => copyToClipboard(codeStr)}
                              className="flex items-center gap-1 text-xs text-gray-400
                                         hover:text-gray-200 transition-colors"
                            >
                              {copied ? (
                                <>
                                  <Check size={12} className="text-green-400" />
                                  <span className="text-green-400">Copied</span>
                                </>
                              ) : (
                                <>
                                  <Copy size={12} />
                                  <span>Copy</span>
                                </>
                              )}
                            </button>
                          </div>
                        </div>
                        <SyntaxHighlighter
                          style={oneDark}
                          language={match[1]}
                          PreTag="div"
                          // The theme also paints <code> (inline), which drew a box behind every line.
                          // codeTagProps replaces the defaults, so keep the language class too.
                          codeTagProps={{
                            className: `language-${match[1]}`,
                            style: { ...oneDark['code[class*="language-"]'], background: 'transparent' },
                          }}
                          customStyle={{
                            margin: 0,
                            borderRadius: 0,
                            background: '#18181b',
                            fontSize: '0.85rem',
                          }}
                        >
                          {codeStr}
                        </SyntaxHighlighter>
                      </div>
                    )
                  },
                }}
              >
                {message.content}
              </ReactMarkdown>
            </div>
          )}

          {/* Action buttons (visible on hover) */}
          {!isUser && message.content && (
            <div className="flex items-center gap-1 mt-2 opacity-0 group-hover:opacity-100 transition-opacity">
              <button
                onClick={() => copyToClipboard(message.content)}
                className="flex items-center gap-1 px-2 py-1 text-xs text-dark-text-secondary
                           hover:text-dark-text-primary hover:bg-dark-bg-secondary
                           rounded transition-colors"
              >
                {copied ? (
                  <Check size={12} className="text-green-400" />
                ) : (
                  <Copy size={12} />
                )}
                <span>{copied ? 'Copied' : 'Copy'}</span>
              </button>
              <span className="px-1 text-[11px] text-dark-text-secondary">{timeStr}</span>
            </div>
          )}

          {/* Context transparency panel — collapsible, shows what was retrieved */}
          {!isUser && ctx && Object.keys(ctx).length > 0 && (
            <div className="mt-2">
              <button
                onClick={() => setContextOpen(!contextOpen)}
                className="flex items-center gap-1.5 text-[11px] text-dark-text-secondary
                           hover:text-dark-text-primary transition-colors"
              >
                <ChevronDown
                  size={12}
                  className={`transition-transform ${contextOpen ? 'rotate-0' : '-rotate-90'}`}
                />
                <span>Context used</span>
                <span className="text-dark-text-secondary">
                  ({Object.keys(ctx).length} source{Object.keys(ctx).length !== 1 ? 's' : ''})
                </span>
              </button>
              {contextOpen && (
                <div className="mt-1.5 pl-3 border-l-2 border-dark-border space-y-1.5 text-[11px] text-dark-text-secondary">
                  {ctx.memories && ctx.memories.length > 0 && (
                    <div className="flex items-start gap-1.5">
                      <Brain size={11} className="text-purple-400 mt-0.5 flex-shrink-0" />
                      <div>
                        <span className="text-purple-400 font-medium">Memories</span>
                        <span className="ml-1">({ctx.memories.length})</span>
                        <ul className="mt-0.5 space-y-0.5 text-dark-text-secondary">
                          {ctx.memories.map((m, i) => (
                            <li key={i} className="truncate max-w-[400px]">{m}</li>
                          ))}
                        </ul>
                      </div>
                    </div>
                  )}
                  {ctx.graph && (
                    <div className="flex items-start gap-1.5">
                      <Network size={11} className="text-cyan-400 mt-0.5 flex-shrink-0" />
                      <div>
                        <span className="text-cyan-400 font-medium">Knowledge graph</span>
                        <p className="mt-0.5 text-dark-text-secondary truncate max-w-[400px]">
                          {ctx.graph}
                        </p>
                      </div>
                    </div>
                  )}
                  {ctx.notes !== undefined && ctx.notes > 0 && (
                    <div className="flex items-center gap-1.5">
                      <BookOpen size={11} className="text-amber-400 flex-shrink-0" />
                      <span className="text-amber-400 font-medium">Notes</span>
                      <span>({ctx.notes})</span>
                    </div>
                  )}
                  {ctx.search_results !== undefined && ctx.search_results > 0 && (
                    <div className="flex items-center gap-1.5">
                      <Search size={11} className="text-blue-400 flex-shrink-0" />
                      <span className="text-blue-400 font-medium">Past messages</span>
                      <span>({ctx.search_results} matched)</span>
                    </div>
                  )}
                  {ctx.web_search && (
                    <div className="flex items-center gap-1.5">
                      <Globe size={11} className="text-green-400 flex-shrink-0" />
                      <span className="text-green-400 font-medium">Web search</span>
                    </div>
                  )}
                  {ctx.warnings !== undefined && ctx.warnings > 0 && (
                    <div className="flex items-center gap-1.5">
                      <AlertTriangle size={11} className="text-orange-400 flex-shrink-0" />
                      <span className="text-orange-400 font-medium">Warnings</span>
                      <span>({ctx.warnings} past failure{ctx.warnings !== 1 ? 's' : ''} matched)</span>
                    </div>
                  )}
                  {ctx.continuity && (
                    <div className="flex items-center gap-1.5">
                      <Brain size={11} className="text-indigo-400 flex-shrink-0" />
                      <span className="text-indigo-400 font-medium">Related conversation detected</span>
                    </div>
                  )}
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      {/* Artifact preview side panel */}
      {artifact && (
        <ArtifactPanel
          code={artifact.code}
          language={artifact.language}
          onClose={() => setArtifact(null)}
        />
      )}
    </div>
  )
}
