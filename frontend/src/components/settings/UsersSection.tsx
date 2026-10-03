/**
 * Settings > Users (admins only): everyone who can sign in to this Engram.
 * Admins add, edit and delete accounts and grant admin rights; the server
 * keeps at least one admin. Risky changes ask first. Your own profile is
 * edited in Settings > Account.
 */

import { useEffect, useState } from 'react'
import { UserPlus } from 'lucide-react'
import { usersApi } from '../../services/api'
import { useAuthStore } from '../../stores/authStore'
import { useUIStore } from '../../stores/uiStore'
import {
  ActionButton, ActionRow, ActionStatus, Badge, ConfirmButton, ErrorStatus, PasswordField, TextField,
  errorText, useAction, useDirty,
} from './primitives'

interface UserRow {
  id: string
  email: string
  name: string
  created_at: string
  is_admin?: boolean
}

const MIN_PASSWORD = 8
const ADMIN_HINT = 'Admins add and manage accounts and can see server logs.'

function AdminCheckbox({ checked, onChange, disabled }: { checked: boolean; onChange: (v: boolean) => void; disabled?: boolean }) {
  return (
    <label className="flex items-start gap-2 text-sm text-dark-text-primary cursor-pointer">
      <input type="checkbox" checked={checked} onChange={e => onChange(e.target.checked)} disabled={disabled}
             className="mt-0.5 w-4 h-4 accent-dark-accent-primary" />
      <span>
        Admin
        <span className="block text-xs text-dark-text-secondary">{ADMIN_HINT}</span>
      </span>
    </label>
  )
}

export default function UsersSection({ active, onCount }: { active: boolean; onCount?: (n: number) => void }) {
  const currentUser = useAuthStore(s => s.user)
  const setSettingsSection = useUIStore(s => s.setSettingsSection)
  const [users, setUsers] = useState<UserRow[]>([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState('')
  const [editingId, setEditingId] = useState<string | null>(null)
  const [creating, setCreating] = useState(false)
  const [deleteState, runDelete] = useAction()

  const fetchUsers = async () => {
    setLoadError('')
    try {
      const data: UserRow[] = await usersApi.list()
      setUsers(data)
      onCount?.(data.length)
    } catch (e) {
      setLoadError(errorText(e, "Couldn't load users"))
    } finally {
      setLoading(false)
    }
  }

  // Re-read every time the section is opened (e.g. after renaming yourself in Account)
  useEffect(() => { if (active) fetchUsers() }, [active])

  const remove = (u: UserRow) => runDelete(async () => {
    await usersApi.delete(u.id)
    await fetchUsers()
  }, `${u.name}'s account deleted`, `Couldn't delete ${u.name}'s account`)

  return (
    <div className="space-y-3">
      {!creating && (
        <ActionButton variant="primary" onClick={() => setCreating(true)}><UserPlus size={13} /> Add user</ActionButton>
      )}
      {creating && <NewUserForm onDone={(added) => { setCreating(false); if (added) fetchUsers() }} />}

      {loadError && (
        <div role="alert" className="flex items-center gap-3 text-xs text-red-400 [.light_&]:text-red-700">
          {loadError}
          <ActionButton onClick={fetchUsers}>Retry</ActionButton>
        </div>
      )}
      <ErrorStatus state={deleteState} />

      {loading ? (
        <p className="text-xs text-dark-text-secondary">Loading users…</p>
      ) : (
        <ul className="space-y-2">
          {users.map(u => {
            const isMe = u.id === currentUser?.id
            return (
              <li key={u.id} className={`rounded-lg border p-3 ${
                isMe ? 'border-dark-accent-primary/40 bg-dark-accent-primary/5' : 'border-dark-border/60 bg-dark-bg-secondary/50'
              }`}>
                {editingId === u.id ? (
                  <EditUserForm user={u} onDone={(saved) => { setEditingId(null); if (saved) fetchUsers() }} />
                ) : (
                  <div className="flex items-center gap-3 flex-wrap">
                    <div aria-hidden className="w-9 h-9 rounded-full flex items-center justify-center flex-shrink-0 text-sm font-bold text-white bg-dark-accent-primary">
                      {u.name.charAt(0).toUpperCase()}
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium text-dark-text-primary truncate flex items-center gap-2">
                        {u.name} {isMe && <Badge tone="blue">You</Badge>} {u.is_admin && <Badge>Admin</Badge>}
                      </p>
                      <p className="text-xs text-dark-text-secondary truncate">{u.email}</p>
                    </div>
                    {isMe ? (
                      <ActionButton onClick={() => setSettingsSection('account')}>Edit in Account</ActionButton>
                    ) : (
                      <div className="flex items-center gap-2 flex-wrap">
                        <ActionButton onClick={() => setEditingId(u.id)}>Edit</ActionButton>
                        <ConfirmButton
                          label="Delete"
                          prompt={`Delete ${u.name}'s account? This can't be undone.`}
                          confirmLabel="Delete account"
                          danger
                          busy={deleteState.status === 'busy'}
                          onConfirm={() => remove(u)}
                        />
                      </div>
                    )}
                  </div>
                )}
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}

function NewUserForm({ onDone }: { onDone: (added: boolean) => void }) {
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [isAdmin, setIsAdmin] = useState(false)
  const [state, run] = useAction()
  useDirty(name !== '' || email !== '' || password !== '' || isAdmin)

  const valid = name.trim() !== '' && email.trim() !== '' && password.length >= MIN_PASSWORD
  const create = () => run(async () => {
    await usersApi.create({ name: name.trim(), email: email.trim(), password, is_admin: isAdmin })
    onDone(true)
  }, 'User added', "Couldn't add the user")

  return (
    <div className="rounded-lg border border-dark-border/60 bg-dark-bg-secondary/50 p-4 space-y-3">
      <h3 className="text-sm font-medium text-dark-text-primary">Add a user</h3>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
        <TextField label="Name" value={name} onChange={setName} />
        <TextField label="Email" type="email" value={email} onChange={setEmail} />
      </div>
      <PasswordField label="Password" value={password} onChange={setPassword} hint={`At least ${MIN_PASSWORD} characters. Give it to them; they can change it in Settings › Account.`} />
      <AdminCheckbox checked={isAdmin} onChange={setIsAdmin} />
      <ActionRow>
        <ActionButton onClick={() => onDone(false)}>Cancel</ActionButton>
        <ActionButton variant="primary" onClick={create} busy={state.status === 'busy'} disabled={!valid}>Add user</ActionButton>
        <ActionStatus state={state} />
      </ActionRow>
    </div>
  )
}

function EditUserForm({ user, onDone }: { user: UserRow; onDone: (saved: boolean) => void }) {
  const [name, setName] = useState(user.name)
  const [email, setEmail] = useState(user.email)
  const [password, setPassword] = useState('')
  const [isAdmin, setIsAdmin] = useState(!!user.is_admin)
  const [state, run] = useAction()
  const dirty = name !== user.name || email !== user.email || password !== '' || isAdmin !== !!user.is_admin
  useDirty(dirty)

  const tooShort = password.length > 0 && password.length < MIN_PASSWORD
  const save = () => run(async () => {
    const payload: { name?: string; email?: string; password?: string; is_admin?: boolean } = {}
    if (name.trim() && name !== user.name) payload.name = name.trim()
    if (email.trim() && email !== user.email) payload.email = email.trim()
    if (password) payload.password = password
    if (isAdmin !== !!user.is_admin) payload.is_admin = isAdmin
    await usersApi.update(user.id, payload)
    onDone(true)
  })

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
        <TextField label="Name" value={name} onChange={setName} />
        <TextField label="Email" type="email" value={email} onChange={setEmail} />
      </div>
      <PasswordField
        label="New password"
        value={password}
        onChange={setPassword}
        placeholder="Leave empty to keep their password"
        hint={tooShort ? `At least ${MIN_PASSWORD} characters.` : undefined}
      />
      <AdminCheckbox checked={isAdmin} onChange={setIsAdmin} />
      <ActionRow>
        <ActionButton onClick={() => onDone(false)}>Cancel</ActionButton>
        {/* Changing someone else's password signs them out everywhere, so it asks first */}
        <ConfirmButton
          label="Save"
          variant="primary"
          needsConfirm={password !== ''}
          prompt={`Change ${user.name}'s password? They'll be signed out everywhere and need the new one to sign in.`}
          confirmLabel="Change password"
          busy={state.status === 'busy'}
          disabled={!dirty || tooShort}
          onConfirm={save}
        />
        <ActionStatus state={state} />
      </ActionRow>
    </div>
  )
}
