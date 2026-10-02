/**
 * Settings > Account: your own profile, password, appearance and sign-out.
 * Profile and password changes go through /users/me and keep the signed-in
 * user (shown in the sidebar) in sync. Changing the password needs the
 * current one and signs out your other sessions; "Sign out everywhere" ends
 * all of them, including this one.
 */

import { useEffect, useState } from 'react'
import { Keyboard, LogOut, Moon, Sun } from 'lucide-react'
import { authApi, usersApi } from '../../services/api'
import { useAuthStore } from '../../stores/authStore'
import { useUIStore } from '../../stores/uiStore'
import {
  ActionButton, ActionRow, ActionStatus, ConfirmButton, ErrorStatus, PasswordField, TextField, UnsavedPill,
  useAction, useDirty,
} from './primitives'

const MIN_PASSWORD = 8

export default function AccountSection() {
  const { user, updateUser, setToken, logout } = useAuthStore()
  const { theme, setTheme, setShowShortcuts, requestLeave } = useUIStore()

  const [name, setName] = useState(user?.name ?? '')
  const [email, setEmail] = useState(user?.email ?? '')
  const [currentPassword, setCurrentPassword] = useState('')
  const [password, setPassword] = useState('')
  const [profileState, runProfile] = useAction()
  const [passwordState, runPassword] = useAction()
  const [everywhereState, runEverywhere] = useAction()

  useEffect(() => { setName(user?.name ?? '') }, [user?.name])
  useEffect(() => { setEmail(user?.email ?? '') }, [user?.email])

  const profileDirty = name !== (user?.name ?? '') || email !== (user?.email ?? '')
  useDirty(profileDirty || password !== '' || currentPassword !== '')

  const saveProfile = () => runProfile(async () => {
    if (!name.trim() || !email.trim()) throw new Error('name and email are required')
    const payload: { name?: string; email?: string } = {}
    if (name !== user?.name) payload.name = name.trim()
    if (email !== user?.email) payload.email = email.trim()
    const updated = await usersApi.updateMe(payload)
    updateUser({ name: updated.name, email: updated.email })
  })

  const tooShort = password.length > 0 && password.length < MIN_PASSWORD
  const changePassword = () => runPassword(async () => {
    const res = await usersApi.updateMe({ password, current_password: currentPassword })
    // Other sessions are signed out; this one continues with the new token
    if (res.access_token) setToken(res.access_token)
    setPassword('')
    setCurrentPassword('')
  }, 'Password changed. Your other sessions were signed out.', "Couldn't change the password")

  const signOut = () => { if (requestLeave()) logout() }
  const signOutEverywhere = () => runEverywhere(async () => {
    await authApi.logoutAll()
    logout()
  }, undefined, "Couldn't sign out everywhere")

  return (
    <div className="space-y-4">
      <section aria-labelledby="account-profile" className="rounded-lg border border-dark-border/60 bg-dark-bg-secondary/50 p-4 space-y-3">
        <div className="flex items-center gap-2">
          <h3 id="account-profile" className="text-sm font-medium text-dark-text-primary">Profile</h3>
          {profileDirty && <UnsavedPill />}
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
          <TextField label="Name" value={name} onChange={setName} autoComplete="name" />
          <TextField label="Email" type="email" value={email} onChange={setEmail} autoComplete="email" />
        </div>
        <ActionRow>
          <ActionButton variant="primary" onClick={saveProfile} busy={profileState.status === 'busy'} disabled={!profileDirty}>
            {profileState.status === 'busy' ? 'Saving…' : 'Save'}
          </ActionButton>
          <ActionStatus state={profileState} />
        </ActionRow>
      </section>

      <section aria-labelledby="account-password" className="rounded-lg border border-dark-border/60 bg-dark-bg-secondary/50 p-4 space-y-3">
        <h3 id="account-password" className="text-sm font-medium text-dark-text-primary">Password</h3>
        <PasswordField
          label="Current password"
          value={currentPassword}
          onChange={setCurrentPassword}
          autoComplete="current-password"
        />
        <PasswordField
          label="New password"
          value={password}
          onChange={setPassword}
          hint={tooShort ? `At least ${MIN_PASSWORD} characters (${password.length} so far).` : `At least ${MIN_PASSWORD} characters.`}
        />
        <ActionRow>
          <ActionButton variant="primary" onClick={changePassword} busy={passwordState.status === 'busy'}
                        disabled={password.length < MIN_PASSWORD || currentPassword === ''}>
            Change password
          </ActionButton>
          <ActionStatus state={passwordState} />
        </ActionRow>
      </section>

      <section aria-labelledby="account-appearance" className="rounded-lg border border-dark-border/60 bg-dark-bg-secondary/50 p-4 space-y-3">
        <div>
          <h3 id="account-appearance" className="text-sm font-medium text-dark-text-primary">Appearance</h3>
          <p className="text-xs text-dark-text-secondary mt-0.5">Saved in this browser only. Ctrl+D or the sun/moon button in the sidebar also switch it.</p>
        </div>
        <div role="radiogroup" aria-label="Theme" className="inline-flex rounded-md border border-dark-border overflow-hidden">
          {(['dark', 'light'] as const).map(t => (
            <button
              key={t}
              type="button"
              role="radio"
              aria-checked={theme === t}
              onClick={() => setTheme(t)}
              className={`inline-flex items-center gap-1.5 px-4 py-2 min-h-[40px] sm:min-h-0 text-xs transition-colors
                          focus:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-dark-accent-primary ${
                theme === t ? 'bg-dark-accent-primary text-white font-medium' : 'text-dark-text-secondary hover:text-dark-text-primary'
              }`}
            >
              {t === 'dark' ? <Moon size={13} /> : <Sun size={13} />}
              {t === 'dark' ? 'Dark' : 'Light'}
            </button>
          ))}
        </div>
      </section>

      <section className="rounded-lg border border-dark-border/60 bg-dark-bg-secondary/50 p-4 flex flex-wrap items-center gap-2">
        <ActionButton onClick={() => setShowShortcuts(true)}><Keyboard size={13} /> Keyboard shortcuts</ActionButton>
        <span className="flex-1" />
        <ConfirmButton
          label="Sign out everywhere"
          prompt="Sign out on every device, including this one?"
          confirmLabel="Sign out everywhere"
          busy={everywhereState.status === 'busy'}
          onConfirm={signOutEverywhere}
        />
        <ActionButton onClick={signOut}><LogOut size={13} /> Sign out</ActionButton>
        <ErrorStatus state={everywhereState} />
      </section>
    </div>
  )
}
