/**
 * Knowledge Graph viewer and editor tab.
 *
 * Displays graph statistics, searchable node list, node neighborhood
 * visualization, and allows deleting nodes/edges.
 */

import { useState, useEffect, useCallback } from 'react'
import {
  Search, Loader2, Trash2, GitBranch, ArrowRight,
  ChevronRight, X, RefreshCw, Database, Link2, Tag
} from 'lucide-react'
import { graphApi } from '../../services/api'

// ============================================================
// Types
// ============================================================

interface GraphStats {
  total_nodes: number
  total_relationships: number
  node_types: Record<string, number>
  relationship_types: Record<string, number>
}

interface GraphNode {
  name: string
  node_type: string
  label: string
  created_at?: string
  last_seen?: string
  properties: Record<string, unknown>
  connection_count: number
}

interface GraphEdge {
  from_node: string
  to_node: string
  rel_type: string
  confidence?: number
  created_at?: string
}

interface Neighborhood {
  center: GraphNode
  nodes: GraphNode[]
  edges: GraphEdge[]
}

// ============================================================
// Color map for node types
// ============================================================

const TYPE_COLORS: Record<string, string> = {
  technology: 'bg-blue-500/20 text-blue-400 border-blue-500/30',
  framework: 'bg-purple-500/20 text-purple-400 border-purple-500/30',
  programming_language: 'bg-green-500/20 text-green-400 border-green-500/30',
  tool: 'bg-orange-500/20 text-orange-400 border-orange-500/30',
  person: 'bg-pink-500/20 text-pink-400 border-pink-500/30',
  project: 'bg-cyan-500/20 text-cyan-400 border-cyan-500/30',
  concept: 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30',
  error_type: 'bg-red-500/20 text-red-400 border-red-500/30',
  decision: 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30',
  organization: 'bg-indigo-500/20 text-indigo-400 border-indigo-500/30',
}

const DEFAULT_TYPE_COLOR = 'bg-dark-bg-primary text-dark-text-secondary border-dark-border/50'

function typeColor(nodeType: string): string {
  return TYPE_COLORS[nodeType] || DEFAULT_TYPE_COLOR
}

function formatDate(dateStr?: string): string {
  if (!dateStr) return '—'
  try {
    const d = new Date(dateStr)
    if (isNaN(d.getTime())) return dateStr
    return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
  } catch {
    return dateStr
  }
}

// ============================================================
// Main Component
// ============================================================

export default function KnowledgeGraphTab() {
  const [stats, setStats] = useState<GraphStats | null>(null)
  const [nodes, setNodes] = useState<GraphNode[]>([])
  const [searchQuery, setSearchQuery] = useState('')
  const [typeFilter, setTypeFilter] = useState<string>('')
  const [isLoading, setIsLoading] = useState(true)
  const [isLoadingNodes, setIsLoadingNodes] = useState(false)
  const [selectedNode, setSelectedNode] = useState<string | null>(null)
  const [neighborhood, setNeighborhood] = useState<Neighborhood | null>(null)
  const [isLoadingNeighborhood, setIsLoadingNeighborhood] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [deleteConfirm, setDeleteConfirm] = useState<string | null>(null)

  // Fetch stats on mount
  useEffect(() => {
    fetchStats()
    fetchNodes()
  }, [])

  const fetchStats = async () => {
    try {
      const data = await graphApi.getStats()
      setStats(data)
      setError(null)
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to connect to Neo4j'
      setError(msg)
    } finally {
      setIsLoading(false)
    }
  }

  const fetchNodes = useCallback(async (search?: string, nodeType?: string) => {
    setIsLoadingNodes(true)
    try {
      const data = await graphApi.listNodes({
        search: search || undefined,
        node_type: nodeType || undefined,
        limit: 50,
      })
      setNodes(data)
      setError(null)
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to fetch nodes'
      setError(msg)
    } finally {
      setIsLoadingNodes(false)
    }
  }, [])

  // Debounced search
  useEffect(() => {
    const timer = setTimeout(() => {
      fetchNodes(searchQuery, typeFilter)
    }, 300)
    return () => clearTimeout(timer)
  }, [searchQuery, typeFilter, fetchNodes])

  const handleSelectNode = async (nodeName: string) => {
    if (selectedNode === nodeName) {
      setSelectedNode(null)
      setNeighborhood(null)
      return
    }
    setSelectedNode(nodeName)
    setIsLoadingNeighborhood(true)
    try {
      const data = await graphApi.getNeighborhood(nodeName, 1)
      setNeighborhood(data)
    } catch {
      setNeighborhood(null)
    } finally {
      setIsLoadingNeighborhood(false)
    }
  }

  const handleDeleteNode = async (nodeName: string) => {
    try {
      await graphApi.deleteNode(nodeName)
      // Refresh
      setSelectedNode(null)
      setNeighborhood(null)
      setDeleteConfirm(null)
      await Promise.all([fetchStats(), fetchNodes(searchQuery, typeFilter)])
    } catch (err: unknown) {
      console.error('Failed to delete node:', err)
    }
  }

  const handleDeleteEdge = async (from: string, to: string) => {
    try {
      await graphApi.deleteEdge(from, to)
      // Refresh neighborhood
      if (selectedNode) {
        const data = await graphApi.getNeighborhood(selectedNode, 1)
        setNeighborhood(data)
      }
      await fetchStats()
    } catch (err: unknown) {
      console.error('Failed to delete edge:', err)
    }
  }

  if (isLoading) {
    return (
      <div className="h-full flex items-center justify-center">
        <div className="flex flex-col items-center gap-3">
          <Loader2 size={20} className="animate-spin text-dark-accent-primary" />
          <p className="text-sm text-dark-text-secondary">Loading knowledge graph...</p>
        </div>
      </div>
    )
  }

  if (error && !stats) {
    return (
      <div className="h-full flex items-center justify-center">
        <div className="text-center max-w-md px-6">
          <GitBranch size={32} className="text-dark-text-secondary/30 mx-auto mb-3" />
          <h2 className="text-lg font-medium text-dark-text-primary mb-2">Knowledge Graph Unavailable</h2>
          <p className="text-sm text-dark-text-secondary">{error}</p>
          <p className="text-xs text-dark-text-secondary/60 mt-2">
            Configure Neo4j in Settings → Knowledge Graph
          </p>
        </div>
      </div>
    )
  }

  return (
    <div className="h-full overflow-y-auto">
      <div className="max-w-4xl mx-auto px-6 py-8">
        {/* Header */}
        <div className="flex items-center gap-3 mb-6">
          <div className="p-2 rounded-lg bg-dark-accent-primary/10">
            <GitBranch size={20} className="text-dark-accent-primary" />
          </div>
          <div className="flex-1">
            <h1 className="text-xl font-semibold text-dark-text-primary">Knowledge Graph</h1>
            <p className="text-sm text-dark-text-secondary">
              Browse and manage entities extracted from your conversations
            </p>
          </div>
          <button
            onClick={() => { fetchStats(); fetchNodes(searchQuery, typeFilter) }}
            className="p-2 rounded-lg hover:bg-dark-bg-secondary text-dark-text-secondary
                       hover:text-dark-text-primary transition-colors"
            title="Refresh"
          >
            <RefreshCw size={16} />
          </button>
        </div>

        {/* Stats cards */}
        {stats && (
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-6">
            <StatCard icon={<Database size={14} />} label="Nodes" value={stats.total_nodes} />
            <StatCard icon={<Link2 size={14} />} label="Relationships" value={stats.total_relationships} />
            <StatCard icon={<Tag size={14} />} label="Node Types" value={Object.keys(stats.node_types).length} />
            <StatCard icon={<ArrowRight size={14} />} label="Edge Types" value={Object.keys(stats.relationship_types).length} />
          </div>
        )}

        {/* Type breakdown */}
        {stats && Object.keys(stats.node_types).length > 0 && (
          <div className="flex flex-wrap gap-1.5 mb-6">
            <button
              onClick={() => setTypeFilter('')}
              className={`text-[11px] px-2.5 py-1 rounded-full border transition-colors ${
                !typeFilter
                  ? 'bg-dark-accent-primary/20 text-dark-accent-primary border-dark-accent-primary/30'
                  : 'bg-dark-bg-secondary border-dark-border/50 text-dark-text-secondary hover:text-dark-text-primary'
              }`}
            >
              All ({stats.total_nodes})
            </button>
            {Object.entries(stats.node_types)
              .sort(([, a], [, b]) => b - a)
              .map(([type, count]) => (
                <button
                  key={type}
                  onClick={() => setTypeFilter(type === typeFilter ? '' : type)}
                  className={`text-[11px] px-2.5 py-1 rounded-full border transition-colors ${
                    type === typeFilter
                      ? typeColor(type)
                      : 'bg-dark-bg-secondary border-dark-border/50 text-dark-text-secondary hover:text-dark-text-primary'
                  }`}
                >
                  {type.replace(/_/g, ' ')} ({count})
                </button>
              ))}
          </div>
        )}

        {/* Search */}
        <div className="relative mb-4">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-dark-text-secondary" />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search entities..."
            className="w-full pl-9 pr-4 py-2 bg-dark-bg-secondary border border-dark-border rounded-lg
                       text-sm text-dark-text-primary placeholder:text-dark-text-secondary/40
                       focus:outline-none focus:border-dark-accent-primary/50 transition-colors"
          />
          {isLoadingNodes && (
            <Loader2 size={14} className="absolute right-3 top-1/2 -translate-y-1/2 animate-spin text-dark-text-secondary" />
          )}
        </div>

        {/* Node list + detail split */}
        <div className="flex gap-4">
          {/* Node list */}
          <div className={`space-y-1 ${selectedNode ? 'w-1/2' : 'w-full'} transition-all`}>
            {nodes.length === 0 && !isLoadingNodes && (
              <p className="text-sm text-dark-text-secondary/60 italic py-4 text-center">
                {searchQuery || typeFilter ? 'No matching entities found' : 'No entities in the graph yet'}
              </p>
            )}
            {nodes.map((node) => (
              <button
                key={node.name}
                onClick={() => handleSelectNode(node.name)}
                className={`w-full text-left px-3 py-2.5 rounded-lg border transition-all ${
                  selectedNode === node.name
                    ? 'bg-dark-accent-primary/10 border-dark-accent-primary/30'
                    : 'bg-dark-bg-secondary/50 border-transparent hover:bg-dark-bg-secondary hover:border-dark-border/30'
                }`}
              >
                <div className="flex items-center gap-2">
                  <ChevronRight
                    size={12}
                    className={`text-dark-text-secondary flex-shrink-0 transition-transform ${
                      selectedNode === node.name ? 'rotate-90' : ''
                    }`}
                  />
                  <span className="text-sm font-medium text-dark-text-primary truncate flex-1">
                    {node.name}
                  </span>
                  <span className={`text-[10px] px-1.5 py-0.5 rounded border flex-shrink-0 ${typeColor(node.node_type)}`}>
                    {node.node_type.replace(/_/g, ' ')}
                  </span>
                  {node.connection_count > 0 && (
                    <span className="text-[10px] text-dark-text-secondary/50 flex-shrink-0">
                      {node.connection_count} conn
                    </span>
                  )}
                </div>
                <div className="flex items-center gap-3 mt-1 ml-5">
                  <span className="text-[10px] text-dark-text-secondary/50">
                    Last seen: {formatDate(node.last_seen)}
                  </span>
                </div>
              </button>
            ))}
          </div>

          {/* Node detail panel */}
          {selectedNode && (
            <div className="w-1/2 sticky top-0">
              <div className="rounded-lg border border-dark-border bg-dark-bg-secondary p-4">
                {isLoadingNeighborhood ? (
                  <div className="flex items-center justify-center py-8">
                    <Loader2 size={16} className="animate-spin text-dark-accent-primary" />
                  </div>
                ) : neighborhood ? (
                  <>
                    {/* Center node header */}
                    <div className="flex items-start justify-between mb-4">
                      <div className="flex-1 min-w-0">
                        <h3 className="text-base font-semibold text-dark-text-primary truncate">
                          {neighborhood.center.name}
                        </h3>
                        <div className="flex items-center gap-2 mt-1">
                          <span className={`text-[10px] px-1.5 py-0.5 rounded border ${typeColor(neighborhood.center.node_type)}`}>
                            {neighborhood.center.node_type.replace(/_/g, ' ')}
                          </span>
                          <span className="text-[10px] text-dark-text-secondary/50">
                            {neighborhood.center.connection_count} connections
                          </span>
                        </div>
                        <div className="text-[10px] text-dark-text-secondary/50 mt-1">
                          Created: {formatDate(neighborhood.center.created_at)} · Last seen: {formatDate(neighborhood.center.last_seen)}
                        </div>
                      </div>
                      <div className="flex items-center gap-1 flex-shrink-0">
                        {deleteConfirm === selectedNode ? (
                          <div className="flex items-center gap-1">
                            <button
                              onClick={() => handleDeleteNode(selectedNode)}
                              className="text-[10px] px-2 py-1 bg-red-500/20 text-red-400 rounded hover:bg-red-500/30 transition-colors"
                            >
                              Confirm
                            </button>
                            <button
                              onClick={() => setDeleteConfirm(null)}
                              className="p-1 text-dark-text-secondary hover:text-dark-text-primary"
                            >
                              <X size={12} />
                            </button>
                          </div>
                        ) : (
                          <button
                            onClick={() => setDeleteConfirm(selectedNode)}
                            className="p-1.5 rounded text-dark-text-secondary hover:text-red-400 hover:bg-red-500/10 transition-colors"
                            title="Delete this node"
                          >
                            <Trash2 size={14} />
                          </button>
                        )}
                        <button
                          onClick={() => { setSelectedNode(null); setNeighborhood(null) }}
                          className="p-1.5 rounded text-dark-text-secondary hover:text-dark-text-primary hover:bg-dark-bg-primary transition-colors"
                        >
                          <X size={14} />
                        </button>
                      </div>
                    </div>

                    {/* Relationships */}
                    {neighborhood.edges.length > 0 && (
                      <div className="mb-4">
                        <h4 className="text-xs font-semibold text-dark-text-secondary uppercase tracking-wider mb-2">
                          Relationships ({neighborhood.edges.length})
                        </h4>
                        <div className="space-y-1 max-h-48 overflow-y-auto">
                          {neighborhood.edges.map((edge, i) => (
                            <div
                              key={`${edge.from_node}-${edge.rel_type}-${edge.to_node}-${i}`}
                              className="flex items-center gap-2 text-xs px-2 py-1.5 rounded bg-dark-bg-primary/50 group"
                            >
                              <button
                                onClick={() => handleSelectNode(edge.from_node)}
                                className={`truncate hover:text-dark-accent-primary transition-colors ${
                                  edge.from_node === selectedNode ? 'text-dark-accent-primary font-medium' : 'text-dark-text-primary'
                                }`}
                              >
                                {edge.from_node}
                              </button>
                              <span className="text-[10px] text-dark-text-secondary/60 bg-dark-bg-secondary px-1.5 py-0.5 rounded flex-shrink-0">
                                {edge.rel_type}
                              </span>
                              <ArrowRight size={10} className="text-dark-text-secondary/30 flex-shrink-0" />
                              <button
                                onClick={() => handleSelectNode(edge.to_node)}
                                className={`truncate hover:text-dark-accent-primary transition-colors ${
                                  edge.to_node === selectedNode ? 'text-dark-accent-primary font-medium' : 'text-dark-text-primary'
                                }`}
                              >
                                {edge.to_node}
                              </button>
                              <button
                                onClick={() => handleDeleteEdge(edge.from_node, edge.to_node)}
                                className="p-0.5 rounded text-dark-text-secondary/30 hover:text-red-400
                                           opacity-0 group-hover:opacity-100 transition-all flex-shrink-0"
                                title="Delete this relationship"
                              >
                                <Trash2 size={10} />
                              </button>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}

                    {/* Connected nodes */}
                    {neighborhood.nodes.length > 0 && (
                      <div>
                        <h4 className="text-xs font-semibold text-dark-text-secondary uppercase tracking-wider mb-2">
                          Connected Nodes ({neighborhood.nodes.length})
                        </h4>
                        <div className="flex flex-wrap gap-1.5">
                          {neighborhood.nodes.map((node) => (
                            <button
                              key={node.name}
                              onClick={() => handleSelectNode(node.name)}
                              className={`text-[11px] px-2 py-1 rounded border transition-colors
                                         hover:bg-dark-accent-primary/10 hover:border-dark-accent-primary/30
                                         ${typeColor(node.node_type)}`}
                              title={`${node.node_type} · ${node.connection_count} connections`}
                            >
                              {node.name}
                            </button>
                          ))}
                        </div>
                      </div>
                    )}

                    {neighborhood.edges.length === 0 && neighborhood.nodes.length === 0 && (
                      <p className="text-xs text-dark-text-secondary/50 italic">
                        No connections found for this node
                      </p>
                    )}
                  </>
                ) : (
                  <p className="text-sm text-dark-text-secondary/50 italic py-4 text-center">
                    Failed to load node details
                  </p>
                )}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

// ============================================================
// Sub-components
// ============================================================

function StatCard({ icon, label, value }: { icon: React.ReactNode; label: string; value: number }) {
  return (
    <div className="rounded-lg border border-dark-border/50 bg-dark-bg-secondary/50 px-3 py-2.5">
      <div className="flex items-center gap-1.5 text-dark-text-secondary mb-1">
        {icon}
        <span className="text-[10px] uppercase tracking-wider font-medium">{label}</span>
      </div>
      <p className="text-lg font-semibold text-dark-text-primary">{value.toLocaleString()}</p>
    </div>
  )
}
