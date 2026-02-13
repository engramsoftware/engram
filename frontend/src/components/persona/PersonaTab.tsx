/**
 * Persona tab for managing AI personas/system prompts.
 */

import { useState, useEffect } from 'react'
import { Plus, Trash2, Star } from 'lucide-react'
import { personasApi } from '../../services/api'
import type { Persona } from '../../types/addin.types'

export default function PersonaTab() {
  const [personas, setPersonas] = useState<Persona[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [newPersona, setNewPersona] = useState({ name: '', description: '', systemPrompt: '' })

  useEffect(() => {
    fetchPersonas()
  }, [])

  async function fetchPersonas() {
    try {
      const data = await personasApi.list()
      // API returns snake_case; our Persona type matches snake_case, so set directly
      setPersonas(data)
    } catch (error) {
      console.error('Failed to fetch personas:', error)
    } finally {
      setIsLoading(false)
    }
  }

  const handleCreate = async () => {
    if (!newPersona.name || !newPersona.systemPrompt) return
    try {
      await personasApi.create({
        name: newPersona.name,
        description: newPersona.description,
        systemPrompt: newPersona.systemPrompt,
      })
      setNewPersona({ name: '', description: '', systemPrompt: '' })
      fetchPersonas()
    } catch (error) {
      console.error('Failed to create persona:', error)
    }
  }

  const handleSetDefault = async (id: string) => {
    try {
      await personasApi.update(id, { isDefault: true })
      fetchPersonas()
    } catch (error) {
      console.error('Failed to set default:', error)
    }
  }

  const handleDelete = async (id: string) => {
    if (!confirm('Delete this persona?')) return
    try {
      await personasApi.delete(id)
      fetchPersonas()
    } catch (error) {
      console.error('Failed to delete persona:', error)
    }
  }

  if (isLoading) {
    return (
      <div className="h-full flex items-center justify-center">
        <p className="text-dark-text-secondary">Loading personas...</p>
      </div>
    )
  }

  return (
    <div className="h-full overflow-y-auto p-6 max-w-3xl mx-auto">
      <h1 className="text-2xl font-semibold text-dark-text-primary mb-6">Personas</h1>
      
      {/* Create new persona */}
      <div className="bg-dark-bg-secondary rounded-lg border border-dark-border p-4 mb-6">
        <h3 className="text-lg font-medium text-dark-text-primary mb-3">Create New Persona</h3>
        <div className="space-y-3">
          <input
            type="text"
            value={newPersona.name}
            onChange={(e) => setNewPersona({ ...newPersona, name: e.target.value })}
            placeholder="Persona name"
            className="w-full bg-dark-bg-primary border border-dark-border rounded
                       px-3 py-2 text-sm text-dark-text-primary"
          />
          <input
            type="text"
            value={newPersona.description}
            onChange={(e) => setNewPersona({ ...newPersona, description: e.target.value })}
            placeholder="Description (optional)"
            className="w-full bg-dark-bg-primary border border-dark-border rounded
                       px-3 py-2 text-sm text-dark-text-primary"
          />
          <textarea
            value={newPersona.systemPrompt}
            onChange={(e) => setNewPersona({ ...newPersona, systemPrompt: e.target.value })}
            placeholder="System prompt..."
            rows={4}
            className="w-full bg-dark-bg-primary border border-dark-border rounded
                       px-3 py-2 text-sm text-dark-text-primary resize-none"
          />
          <button
            onClick={handleCreate}
            className="flex items-center gap-2 px-4 py-2 bg-dark-accent-primary
                       hover:bg-dark-accent-hover rounded text-white text-sm"
          >
            <Plus size={16} /> Create Persona
          </button>
        </div>
      </div>

      {/* Existing personas */}
      <div className="space-y-4">
        {personas.map((persona) => (
          <div
            key={persona.id}
            className="bg-dark-bg-secondary rounded-lg border border-dark-border p-4"
          >
            <div className="flex items-center justify-between mb-2">
              <div className="flex items-center gap-2">
                <h3 className="text-lg font-medium text-dark-text-primary">{persona.name}</h3>
                {persona.is_default && (
                  <Star size={16} className="text-yellow-400 fill-yellow-400" />
                )}
              </div>
              <div className="flex gap-2">
                {!persona.is_default && (
                  <button
                    onClick={() => handleSetDefault(persona.id)}
                    className="text-dark-text-secondary hover:text-dark-accent-primary"
                    title="Set as default"
                  >
                    <Star size={16} />
                  </button>
                )}
                <button
                  onClick={() => handleDelete(persona.id)}
                  className="text-dark-text-secondary hover:text-red-400"
                >
                  <Trash2 size={16} />
                </button>
              </div>
            </div>
            {persona.description && (
              <p className="text-sm text-dark-text-secondary mb-2">{persona.description}</p>
            )}
            <pre className="text-xs text-dark-text-secondary bg-dark-bg-primary
                           rounded p-2 overflow-x-auto whitespace-pre-wrap">
              {persona.system_prompt}
            </pre>
          </div>
        ))}
      </div>
    </div>
  )
}
