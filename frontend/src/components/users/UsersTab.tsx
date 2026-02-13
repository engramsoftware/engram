/**
 * Users management tab.
 * Lists all users, allows editing profiles (name, email, password),
 * creating new users, and deleting accounts.
 *
 * The current user's card is highlighted and uses the /me endpoint
 * so the auth store stays in sync.
 */

import { useState, useEffect } from 'react'
import {
  Users, UserPlus, Pencil, Trash2, Check, X, Loader2, Eye, EyeOff,
} from 'lucide-react'
import { usersApi } from '../../services/api'
import { useAuthStore } from '../../stores/authStore'

interface UserRow {
  id: string
  email: string
  name: string
  created_at: string
}

export default function UsersTab() {
  const { user: currentUser, updateUser } = useAuthStore()

  const [users, setUsers] = useState<UserRow[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  // Edit state
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editName, setEditName] = useState('')
  const [editEmail, setEditEmail] = useState('')
  const [editPassword, setEditPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [saving, setSaving] = useState(false)
  const [editError, setEditError] = useState('')

  // Create state
  const [showCreate, setShowCreate] = useState(false)
  const [newName, setNewName] = useState('')
  const [newEmail, setNewEmail] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [creating, setCreating] = useState(false)
  const [createError, setCreateError] = useState('')

  // Delete state
  const [deletingId, setDeletingId] = useState<string | null>(null)

  /** Fetch all users. */
  async function fetchUsers() {
    setLoading(true)
    setError('')
    try {
      const data = await usersApi.list()
      setUsers(data)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load users')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { fetchUsers() }, [])

  /** Start editing a user row. */
  function startEdit(u: UserRow) {
    setEditingId(u.id)
    setEditName(u.name)
    setEditEmail(u.email)
    setEditPassword('')
    setShowPassword(false)
    setEditError('')
  }

  /** Cancel editing. */
  function cancelEdit() {
    setEditingId(null)
    setEditError('')
  }

  /** Save edits for a user. */
  async function saveEdit() {
    if (!editingId) return
    setSaving(true)
    setEditError('')

    const payload: Record<string, string> = {}
    const original = users.find((u) => u.id === editingId)
    if (editName && editName !== original?.name) payload.name = editName
    if (editEmail && editEmail !== original?.email) payload.email = editEmail
    if (editPassword) payload.password = editPassword

    if (Object.keys(payload).length === 0) {
      cancelEdit()
      setSaving(false)
      return
    }

    try {
      const isMe = editingId === currentUser?.id
      if (isMe) {
        const updated = await usersApi.updateMe(payload)
        // Keep auth store in sync
        updateUser({ name: updated.name, email: updated.email })
      } else {
        await usersApi.update(editingId, payload)
      }
      await fetchUsers()
      setEditingId(null)
    } catch (e) {
      setEditError(e instanceof Error ? e.message : 'Save failed')
    } finally {
      setSaving(false)
    }
  }

  /** Create a new user. */
  async function handleCreate() {
    setCreating(true)
    setCreateError('')
    try {
      await usersApi.create({ name: newName, email: newEmail, password: newPassword })
      setShowCreate(false)
      setNewName('')
      setNewEmail('')
      setNewPassword('')
      await fetchUsers()
    } catch (e) {
      setCreateError(e instanceof Error ? e.message : 'Create failed')
    } finally {
      setCreating(false)
    }
  }

  /** Delete a user (with confirmation). */
  async function handleDelete(userId: string) {
    try {
      await usersApi.delete(userId)
      setDeletingId(null)
      await fetchUsers()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Delete failed')
      setDeletingId(null)
    }
  }

  return (
    <div className="flex-1 overflow-y-auto p-4 sm:p-6 max-w-3xl mx-auto w-full">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-indigo-500 to-purple-600
                          flex items-center justify-center">
            <Users size={20} className="text-white" />
          </div>
          <div>
            <h1 className="text-lg font-bold text-dark-text-primary">Users</h1>
            <p className="text-xs text-dark-text-secondary">
              Manage accounts — {users.length} user{users.length !== 1 ? 's' : ''}
            </p>
          </div>
        </div>

        <button
          onClick={() => { setShowCreate(true); setCreateError('') }}
          className="flex items-center gap-1.5 px-3 py-2 rounded-lg text-sm font-medium
                     bg-dark-accent-primary hover:bg-dark-accent-hover text-white transition-colors"
        >
          <UserPlus size={16} />
          New User
        </button>
      </div>

      {/* Error banner */}
      {error && (
        <div className="mb-4 px-3 py-2 rounded-lg bg-red-500/10 border border-red-500/30
                        text-sm text-red-400">
          {error}
        </div>
      )}

      {/* Create user form */}
      {showCreate && (
        <div className="mb-4 p-4 rounded-xl border border-dark-border bg-dark-bg-secondary/50">
          <h3 className="text-sm font-semibold text-dark-text-primary mb-3">Create New User</h3>
          <div className="space-y-2.5">
            <input
              type="text"
              placeholder="Name"
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              className="w-full bg-dark-bg-primary border border-dark-border rounded-lg
                         px-3 py-2 text-sm text-dark-text-primary placeholder:text-dark-text-secondary/40
                         focus:outline-none focus:border-dark-accent-primary"
            />
            <input
              type="email"
              placeholder="Email"
              value={newEmail}
              onChange={(e) => setNewEmail(e.target.value)}
              className="w-full bg-dark-bg-primary border border-dark-border rounded-lg
                         px-3 py-2 text-sm text-dark-text-primary placeholder:text-dark-text-secondary/40
                         focus:outline-none focus:border-dark-accent-primary"
            />
            <input
              type="password"
              placeholder="Password (min 8 chars)"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              className="w-full bg-dark-bg-primary border border-dark-border rounded-lg
                         px-3 py-2 text-sm text-dark-text-primary placeholder:text-dark-text-secondary/40
                         focus:outline-none focus:border-dark-accent-primary"
            />
            {createError && (
              <p className="text-xs text-red-400">{createError}</p>
            )}
            <div className="flex gap-2 pt-1">
              <button
                onClick={handleCreate}
                disabled={creating || !newName || !newEmail || newPassword.length < 8}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-medium
                           bg-dark-accent-primary hover:bg-dark-accent-hover text-white
                           disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
              >
                {creating ? <Loader2 size={14} className="animate-spin" /> : <Check size={14} />}
                Create
              </button>
              <button
                onClick={() => setShowCreate(false)}
                className="px-3 py-1.5 rounded-lg text-sm text-dark-text-secondary
                           hover:bg-dark-bg-secondary transition-colors"
              >
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Loading */}
      {loading && (
        <div className="flex items-center justify-center py-12">
          <Loader2 size={24} className="animate-spin text-dark-text-secondary" />
        </div>
      )}

      {/* User list */}
      {!loading && (
        <div className="space-y-2">
          {users.map((u) => {
            const isMe = u.id === currentUser?.id
            const isEditing = editingId === u.id
            const isDeleting = deletingId === u.id

            return (
              <div
                key={u.id}
                className={`rounded-xl border p-4 transition-colors ${
                  isMe
                    ? 'border-dark-accent-primary/40 bg-dark-accent-primary/5'
                    : 'border-dark-border bg-dark-bg-secondary/30'
                }`}
              >
                {isEditing ? (
                  /* ── Edit mode ── */
                  <div className="space-y-2.5">
                    <div className="flex gap-2">
                      <input
                        type="text"
                        value={editName}
                        onChange={(e) => setEditName(e.target.value)}
                        placeholder="Name"
                        className="flex-1 bg-dark-bg-primary border border-dark-border rounded-lg
                                   px-3 py-1.5 text-sm text-dark-text-primary
                                   focus:outline-none focus:border-dark-accent-primary"
                      />
                      <input
                        type="email"
                        value={editEmail}
                        onChange={(e) => setEditEmail(e.target.value)}
                        placeholder="Email"
                        className="flex-1 bg-dark-bg-primary border border-dark-border rounded-lg
                                   px-3 py-1.5 text-sm text-dark-text-primary
                                   focus:outline-none focus:border-dark-accent-primary"
                      />
                    </div>
                    <div className="relative">
                      <input
                        type={showPassword ? 'text' : 'password'}
                        value={editPassword}
                        onChange={(e) => setEditPassword(e.target.value)}
                        placeholder="New password (leave empty to keep current)"
                        className="w-full bg-dark-bg-primary border border-dark-border rounded-lg
                                   px-3 py-1.5 pr-9 text-sm text-dark-text-primary
                                   focus:outline-none focus:border-dark-accent-primary"
                      />
                      <button
                        type="button"
                        onClick={() => setShowPassword(!showPassword)}
                        className="absolute right-2.5 top-1/2 -translate-y-1/2 text-dark-text-secondary
                                   hover:text-dark-text-primary"
                      >
                        {showPassword ? <EyeOff size={14} /> : <Eye size={14} />}
                      </button>
                    </div>
                    {editError && (
                      <p className="text-xs text-red-400">{editError}</p>
                    )}
                    <div className="flex gap-2">
                      <button
                        onClick={saveEdit}
                        disabled={saving}
                        className="flex items-center gap-1 px-3 py-1.5 rounded-lg text-sm font-medium
                                   bg-dark-accent-primary hover:bg-dark-accent-hover text-white
                                   disabled:opacity-40 transition-colors"
                      >
                        {saving ? <Loader2 size={14} className="animate-spin" /> : <Check size={14} />}
                        Save
                      </button>
                      <button
                        onClick={cancelEdit}
                        className="flex items-center gap-1 px-3 py-1.5 rounded-lg text-sm
                                   text-dark-text-secondary hover:bg-dark-bg-secondary transition-colors"
                      >
                        <X size={14} />
                        Cancel
                      </button>
                    </div>
                  </div>
                ) : (
                  /* ── Display mode ── */
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-3 min-w-0">
                      {/* Avatar */}
                      <div className={`w-9 h-9 rounded-full flex items-center justify-center
                                       flex-shrink-0 text-sm font-bold text-white ${
                        isMe
                          ? 'bg-gradient-to-br from-indigo-500 to-purple-600'
                          : 'bg-dark-border'
                      }`}>
                        {u.name.charAt(0).toUpperCase()}
                      </div>
                      <div className="min-w-0">
                        <div className="flex items-center gap-2">
                          <p className="text-sm font-medium text-dark-text-primary truncate">
                            {u.name}
                          </p>
                          {isMe && (
                            <span className="text-[10px] px-1.5 py-0.5 rounded-full
                                             bg-dark-accent-primary/20 text-indigo-400 font-medium">
                              You
                            </span>
                          )}
                        </div>
                        <p className="text-xs text-dark-text-secondary truncate">{u.email}</p>
                      </div>
                    </div>

                    {/* Actions */}
                    <div className="flex items-center gap-1 flex-shrink-0">
                      <button
                        onClick={() => startEdit(u)}
                        className="p-2 rounded-lg text-dark-text-secondary
                                   hover:text-dark-text-primary hover:bg-dark-bg-secondary
                                   transition-colors"
                        title="Edit"
                      >
                        <Pencil size={14} />
                      </button>
                      {!isMe && (
                        isDeleting ? (
                          <div className="flex items-center gap-1">
                            <button
                              onClick={() => handleDelete(u.id)}
                              className="p-2 rounded-lg text-red-400 hover:bg-red-500/10 transition-colors"
                              title="Confirm delete"
                            >
                              <Check size={14} />
                            </button>
                            <button
                              onClick={() => setDeletingId(null)}
                              className="p-2 rounded-lg text-dark-text-secondary
                                         hover:bg-dark-bg-secondary transition-colors"
                              title="Cancel"
                            >
                              <X size={14} />
                            </button>
                          </div>
                        ) : (
                          <button
                            onClick={() => setDeletingId(u.id)}
                            className="p-2 rounded-lg text-dark-text-secondary
                                       hover:text-red-400 hover:bg-red-500/10 transition-colors"
                            title="Delete"
                          >
                            <Trash2 size={14} />
                          </button>
                        )
                      )}
                    </div>
                  </div>
                )}
              </div>
            )
          })}

          {users.length === 0 && !loading && (
            <p className="text-center text-sm text-dark-text-secondary py-8">
              No users found.
            </p>
          )}
        </div>
      )}
    </div>
  )
}
