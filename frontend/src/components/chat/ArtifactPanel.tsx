/**
 * Artifact preview panel — renders live previews of code, HTML, SVG, and Mermaid
 * diagrams extracted from assistant messages.
 *
 * Renders in a slide-out side panel when the user clicks a "Preview" button
 * on a code block. Supports:
 * - HTML: rendered in a sandboxed iframe
 * - SVG: rendered inline
 * - Mermaid: rendered via mermaid.js CDN
 * - React/JSX: shown as syntax-highlighted code (no live eval for security)
 */

import { useState, useEffect, useRef } from 'react'
import { X, Maximize2, Minimize2, Code2, Eye } from 'lucide-react'

interface ArtifactPanelProps {
  code: string
  language: string
  onClose: () => void
}

/** Detect if code is renderable (HTML, SVG, Mermaid) vs display-only. */
function isRenderable(language: string, code: string): boolean {
  const lang = language.toLowerCase()
  if (['html', 'svg', 'mermaid'].includes(lang)) return true
  // Auto-detect HTML/SVG from content even if language tag is wrong
  if (code.trim().startsWith('<!DOCTYPE') || code.trim().startsWith('<html')) return true
  if (code.trim().startsWith('<svg')) return true
  return false
}

/** Build a sandboxed HTML document for iframe rendering. */
function buildIframeDoc(code: string, language: string): string {
  const lang = language.toLowerCase()

  if (lang === 'mermaid') {
    return `<!DOCTYPE html>
<html><head>
<script src="https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.min.js"></script>
<style>body{background:#1e1e2e;display:flex;justify-content:center;padding:20px;margin:0}</style>
</head><body>
<pre class="mermaid">${code}</pre>
<script>mermaid.initialize({startOnLoad:true,theme:'dark'})</script>
</body></html>`
  }

  if (lang === 'svg' || code.trim().startsWith('<svg')) {
    return `<!DOCTYPE html>
<html><head>
<style>body{background:#1e1e2e;display:flex;justify-content:center;align-items:center;min-height:100vh;margin:0}</style>
</head><body>${code}</body></html>`
  }

  // HTML — inject as-is but add dark background if no body style
  if (!code.includes('<body') && !code.includes('<!DOCTYPE')) {
    return `<!DOCTYPE html>
<html><head>
<style>body{background:#1e1e2e;color:#cdd6f4;font-family:system-ui,sans-serif;padding:20px;margin:0}</style>
</head><body>${code}</body></html>`
  }

  return code
}

export default function ArtifactPanel({ code, language, onClose }: ArtifactPanelProps) {
  const [showCode, setShowCode] = useState(false)
  const [expanded, setExpanded] = useState(false)
  const iframeRef = useRef<HTMLIFrameElement>(null)
  const renderable = isRenderable(language, code)

  // Write content to iframe when code changes
  useEffect(() => {
    if (!renderable || showCode) return
    const iframe = iframeRef.current
    if (!iframe) return

    const doc = buildIframeDoc(code, language)
    // Use srcdoc for sandboxed rendering
    iframe.srcdoc = doc
  }, [code, language, renderable, showCode])

  const panelWidth = expanded ? 'w-[70vw]' : 'w-[40vw] min-w-[360px]'

  return (
    <div
      className={`fixed top-0 right-0 h-full ${panelWidth} bg-dark-bg-primary
                  border-l border-dark-border shadow-2xl z-50
                  flex flex-col transition-all duration-200`}
    >
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-2.5 border-b border-dark-border bg-dark-bg-secondary">
        <div className="flex items-center gap-2">
          <span className="text-xs font-mono text-indigo-400 bg-indigo-500/10 px-2 py-0.5 rounded">
            {language}
          </span>
          <span className="text-sm text-dark-text-secondary">Artifact Preview</span>
        </div>
        <div className="flex items-center gap-1">
          {renderable && (
            <button
              onClick={() => setShowCode(!showCode)}
              className="p-1.5 text-dark-text-secondary hover:text-dark-text-primary
                         hover:bg-dark-bg-primary rounded transition-colors"
              title={showCode ? 'Show preview' : 'Show code'}
            >
              {showCode ? <Eye size={14} /> : <Code2 size={14} />}
            </button>
          )}
          <button
            onClick={() => setExpanded(!expanded)}
            className="p-1.5 text-dark-text-secondary hover:text-dark-text-primary
                       hover:bg-dark-bg-primary rounded transition-colors"
            title={expanded ? 'Shrink' : 'Expand'}
          >
            {expanded ? <Minimize2 size={14} /> : <Maximize2 size={14} />}
          </button>
          <button
            onClick={onClose}
            className="p-1.5 text-dark-text-secondary hover:text-red-400
                       hover:bg-dark-bg-primary rounded transition-colors"
            title="Close"
          >
            <X size={14} />
          </button>
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-auto">
        {renderable && !showCode ? (
          <iframe
            ref={iframeRef}
            className="w-full h-full border-0"
            sandbox="allow-scripts allow-same-origin"
            title="Artifact preview"
          />
        ) : (
          <pre className="p-4 text-sm font-mono text-dark-text-primary whitespace-pre-wrap overflow-auto h-full bg-[#1e1e2e]">
            {code}
          </pre>
        )}
      </div>
    </div>
  )
}
