/**
 * First-run onboarding wizard.
 *
 * Three steps:
 * 1. Create your account (name, email, password)
 * 2. Choose an LLM provider (local free or cloud API)
 * 3. Configure the provider (API key or local server URL)
 *
 * After completing all steps, the user is logged in and redirected to the chat.
 */

import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuthStore } from '../stores/authStore'
import { authApi } from '../services/api'
import {
  MessageSquare,
  User,
  Cpu,
  Key,
  ChevronRight,
  ChevronLeft,
  Check,
  Sparkles,
  Globe,
  Monitor,
  Shield,
  AlertTriangle,
} from 'lucide-react'

type Provider = 'lmstudio' | 'ollama' | 'openai' | 'anthropic' | 'skip'

interface ProviderOption {
  id: Provider
  name: string
  description: string
  icon: React.ReactNode
  cost: string
  needsKey: boolean
}

const PROVIDERS: ProviderOption[] = [
  {
    id: 'lmstudio',
    name: 'LM Studio',
    description: 'Run AI models locally on your PC. Free, private, no internet needed.',
    icon: <Monitor size={24} />,
    cost: 'Free (local)',
    needsKey: false,
  },
  {
    id: 'ollama',
    name: 'Ollama',
    description: 'Another great local option. Lightweight and easy to set up.',
    icon: <Cpu size={24} />,
    cost: 'Free (local)',
    needsKey: false,
  },
  {
    id: 'openai',
    name: 'OpenAI',
    description: 'GPT-4o and GPT-4o-mini. Best overall quality. Pay per use.',
    icon: <Sparkles size={24} />,
    cost: 'Pay per token',
    needsKey: true,
  },
  {
    id: 'anthropic',
    name: 'Anthropic',
    description: 'Claude Sonnet and Haiku. Excellent for long conversations.',
    icon: <Globe size={24} />,
    cost: 'Pay per token',
    needsKey: true,
  },
]

export default function SetupPage() {
  const [step, setStep] = useState(1)
  const [error, setError] = useState('')
  const [isLoading, setIsLoading] = useState(false)

  // Step 1: Legal acceptance
  const [acceptedTerms, setAcceptedTerms] = useState(false)

  // Step 2: Account
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')

  // Step 3: Provider
  const [provider, setProvider] = useState<Provider | null>(null)

  // Step 4: Config
  const [apiKey, setApiKey] = useState('')

  const { login } = useAuthStore()
  const navigate = useNavigate()

  /** Step 2: Create account */
  const handleCreateAccount = async () => {
    setError('')
    setIsLoading(true)
    try {
      const data = await authApi.register(email, name, password)
      login(data.access_token, data.user)
      setStep(3)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Registration failed')
    } finally {
      setIsLoading(false)
    }
  }

  /** Step 4: Save provider config and finish */
  const handleFinish = async () => {
    setError('')
    setIsLoading(true)
    try {
      if (provider && provider !== 'skip') {
        // Save the LLM provider settings
        const token = useAuthStore.getState().token
        const headers: Record<string, string> = {
          'Content-Type': 'application/json',
        }
        if (token) headers['Authorization'] = `Bearer ${token}`

        const settings: Record<string, unknown> = {
          providers: {
            [provider]: {
              enabled: true,
              ...(apiKey ? { apiKey } : {}),
            },
          },
          defaultProvider: provider,
        }

        const res = await fetch('/api/settings/llm', {
          method: 'PUT',
          headers,
          body: JSON.stringify(settings),
        })

        if (!res.ok) {
          console.warn('Failed to save LLM settings:', await res.text())
          // Don't block — user can configure later in Settings
        }
      }
      navigate('/')
    } catch (err) {
      // Non-blocking — let them in even if settings save fails
      console.warn('Setup finish error:', err)
      navigate('/')
    } finally {
      setIsLoading(false)
    }
  }

  const selectedProvider = PROVIDERS.find(p => p.id === provider)

  return (
    <div className="min-h-screen bg-dark-bg-primary flex items-center justify-center p-4">
      <div className="w-full max-w-lg">
        {/* Header */}
        <div className="text-center mb-8">
          <div className="inline-flex items-center justify-center w-16 h-16 rounded-2xl
                          bg-indigo-500/20 border border-indigo-500/30 mb-4">
            <MessageSquare size={32} className="text-indigo-400" />
          </div>
          <h1 className="text-3xl font-bold text-dark-text-primary">Welcome to Engram</h1>
          <p className="text-dark-text-secondary mt-2">Let's get you set up in a few quick steps</p>
        </div>

        {/* Progress bar */}
        <div className="flex items-center gap-2 mb-8">
          {[1, 2, 3, 4].map(s => (
            <div key={s} className="flex-1 flex items-center gap-2">
              <div className={`flex-1 h-1.5 rounded-full transition-colors ${
                s <= step ? 'bg-indigo-500' : 'bg-dark-border'
              }`} />
            </div>
          ))}
        </div>

        {/* Step labels */}
        <div className="flex justify-between text-xs text-dark-text-secondary mb-6">
          <span className={step >= 1 ? 'text-indigo-400' : ''}>1. Terms</span>
          <span className={step >= 2 ? 'text-indigo-400' : ''}>2. Account</span>
          <span className={step >= 3 ? 'text-indigo-400' : ''}>3. AI Provider</span>
          <span className={step >= 4 ? 'text-indigo-400' : ''}>4. Configure</span>
        </div>

        {/* Error display */}
        {error && (
          <div className="p-3 bg-red-500/10 border border-red-500/50 rounded-lg text-red-400 text-sm mb-4">
            {error}
          </div>
        )}

        {/* Step 1: Legal Acceptance */}
        {step === 1 && (
          <div className="space-y-4">
            <div className="flex items-center gap-3 mb-4">
              <div className="w-10 h-10 rounded-lg bg-indigo-500/20 flex items-center justify-center">
                <Shield size={20} className="text-indigo-400" />
              </div>
              <div>
                <h2 className="text-lg font-semibold text-dark-text-primary">Terms & Disclosure</h2>
                <p className="text-sm text-dark-text-secondary">Please review before continuing</p>
              </div>
            </div>

            <div className="max-h-72 overflow-y-auto rounded-lg bg-dark-bg-secondary border border-dark-border p-4 text-sm text-dark-text-secondary space-y-4">
              <div>
                <h3 className="text-dark-text-primary font-semibold mb-1 flex items-center gap-1.5">
                  <AlertTriangle size={14} className="text-amber-400" /> Non-Commercial Use Only
                </h3>
                <p>This software is licensed for <strong className="text-dark-text-primary">personal, non-commercial use only</strong>. You may not sell it, use it to provide paid services, or incorporate it into a commercial product.</p>
              </div>

              <div>
                <h3 className="text-dark-text-primary font-semibold mb-1">What This App Does</h3>
                <ul className="list-disc list-inside space-y-1 ml-1">
                  <li>Sends your messages to an AI language model (the provider you choose) to generate responses</li>
                  <li>Stores all conversations, memories, and settings <strong className="text-dark-text-primary">locally on your machine</strong> in a SQLite database</li>
                  <li>Automatically extracts and remembers facts from your conversations (autonomous memory)</li>
                  <li>Builds a knowledge graph of entities and relationships from your conversations (if Neo4j is configured)</li>
                  <li>Searches the web via Brave Search, DuckDuckGo, and Wikipedia when it detects you need current information</li>
                  <li>Fetches and reads web pages to extract relevant information for your queries</li>
                  <li>Stores vector embeddings of your messages and memories for semantic search</li>
                  <li>Can send email notifications if you configure SMTP settings</li>
                </ul>
              </div>

              <div>
                <h3 className="text-dark-text-primary font-semibold mb-1">Data Sent to External Services</h3>
                <ul className="list-disc list-inside space-y-1 ml-1">
                  <li><strong className="text-dark-text-primary">LLM Provider</strong> (OpenAI, Anthropic, etc.): Your messages, conversation context, and retrieved memories are sent to generate responses. Subject to the provider's privacy policy.</li>
                  <li><strong className="text-dark-text-primary">Web Search</strong> (Brave, DuckDuckGo, Wikipedia): Search queries derived from your messages. Personal information (emails, phone numbers, etc.) is automatically scrubbed before searching.</li>
                  <li><strong className="text-dark-text-primary">Web Pages</strong>: The app fetches public web pages to extract information. Your IP address is visible to those websites.</li>
                  <li><strong className="text-dark-text-primary">Neo4j Aura</strong> (optional): Entity and relationship data from conversations, if you configure a cloud Neo4j instance.</li>
                </ul>
              </div>

              <div>
                <h3 className="text-dark-text-primary font-semibold mb-1">Data Stored Locally</h3>
                <ul className="list-disc list-inside space-y-1 ml-1">
                  <li>All conversations and messages</li>
                  <li>Autonomous memories extracted from conversations</li>
                  <li>User account credentials (password is hashed, API keys are encrypted)</li>
                  <li>Vector embeddings for semantic search</li>
                  <li>Uploaded documents and their embeddings</li>
                  <li>Notes, personas, and app settings</li>
                  <li>Cached web pages (24-hour expiry)</li>
                </ul>
                <p className="mt-1">All local data is in the <code className="text-indigo-300 bg-dark-bg-primary px-1 rounded">data/</code> folder. Delete it to erase everything.</p>
              </div>

              <div>
                <h3 className="text-dark-text-primary font-semibold mb-1 flex items-center gap-1.5">
                  <AlertTriangle size={14} className="text-amber-400" /> No Warranty & Limitation of Liability
                </h3>
                <p>This software is provided <strong className="text-dark-text-primary">"as is" without any warranty</strong>. The authors are <strong className="text-dark-text-primary">not responsible</strong> for:</p>
                <ul className="list-disc list-inside space-y-1 ml-1 mt-1">
                  <li>Any data loss, corruption, or unauthorized access</li>
                  <li>Costs incurred from third-party API usage (LLM tokens, search APIs)</li>
                  <li>Content generated by AI models — you are solely responsible for reviewing and using AI output</li>
                  <li>Any actions taken based on information provided by this software</li>
                  <li>Any privacy or security incidents</li>
                  <li>Any violations of third-party terms of service</li>
                </ul>
              </div>

              <div>
                <h3 className="text-dark-text-primary font-semibold mb-1">Your Responsibilities</h3>
                <ul className="list-disc list-inside space-y-1 ml-1">
                  <li>Review and verify all AI-generated content before relying on it</li>
                  <li>Manage your own API keys and understand associated costs</li>
                  <li>Comply with the terms of service of any third-party providers you use</li>
                  <li>Secure your own installation and back up your own data</li>
                  <li>Use this software only for lawful, non-commercial purposes</li>
                </ul>
              </div>
            </div>

            {/* Acceptance checkbox */}
            <label className="flex items-start gap-3 cursor-pointer p-3 rounded-lg border border-dark-border hover:border-indigo-500/50 transition-colors">
              <input
                type="checkbox"
                checked={acceptedTerms}
                onChange={e => setAcceptedTerms(e.target.checked)}
                className="mt-0.5 w-4 h-4 rounded border-dark-border text-indigo-500 focus:ring-indigo-500 bg-dark-bg-secondary"
              />
              <span className="text-sm text-dark-text-secondary">
                I have read and agree to the terms above. I understand this software is provided "as is" with no warranty, is for <strong className="text-dark-text-primary">non-commercial use only</strong>, and that the authors are not liable for any damages.
              </span>
            </label>

            <button
              onClick={() => setStep(2)}
              disabled={!acceptedTerms}
              className="w-full bg-indigo-600 hover:bg-indigo-500 py-2.5 rounded-lg text-white
                         font-medium disabled:opacity-50 disabled:cursor-not-allowed
                         flex items-center justify-center gap-2 transition-colors mt-2"
            >
              I Agree — Continue
              <ChevronRight size={18} />
            </button>
          </div>
        )}

        {/* Step 2: Create Account */}
        {step === 2 && (
          <div className="space-y-4">
            <div className="flex items-center gap-3 mb-6">
              <div className="w-10 h-10 rounded-lg bg-indigo-500/20 flex items-center justify-center">
                <User size={20} className="text-indigo-400" />
              </div>
              <div>
                <h2 className="text-lg font-semibold text-dark-text-primary">Create Your Account</h2>
                <p className="text-sm text-dark-text-secondary">This stays on your machine — no cloud signup</p>
              </div>
            </div>

            <div>
              <label className="block text-sm text-dark-text-secondary mb-1">Your Name</label>
              <input
                type="text"
                value={name}
                onChange={e => setName(e.target.value)}
                placeholder="John"
                required
                className="w-full bg-dark-bg-secondary border border-dark-border rounded-lg
                           px-4 py-2.5 text-dark-text-primary placeholder-dark-text-secondary/50
                           focus:outline-none focus:border-indigo-500 transition-colors"
              />
            </div>

            <div>
              <label className="block text-sm text-dark-text-secondary mb-1">Email</label>
              <input
                type="email"
                value={email}
                onChange={e => setEmail(e.target.value)}
                placeholder="you@example.com"
                required
                className="w-full bg-dark-bg-secondary border border-dark-border rounded-lg
                           px-4 py-2.5 text-dark-text-primary placeholder-dark-text-secondary/50
                           focus:outline-none focus:border-indigo-500 transition-colors"
              />
            </div>

            <div>
              <label className="block text-sm text-dark-text-secondary mb-1">Password</label>
              <input
                type="password"
                value={password}
                onChange={e => setPassword(e.target.value)}
                placeholder="At least 8 characters"
                required
                minLength={8}
                className="w-full bg-dark-bg-secondary border border-dark-border rounded-lg
                           px-4 py-2.5 text-dark-text-primary placeholder-dark-text-secondary/50
                           focus:outline-none focus:border-indigo-500 transition-colors"
              />
            </div>

            <button
              onClick={handleCreateAccount}
              disabled={isLoading || !name || !email || !password || password.length < 8}
              className="w-full bg-indigo-600 hover:bg-indigo-500 py-2.5 rounded-lg text-white
                         font-medium disabled:opacity-50 disabled:cursor-not-allowed
                         flex items-center justify-center gap-2 transition-colors mt-6"
            >
              {isLoading ? 'Creating...' : 'Continue'}
              {!isLoading && <ChevronRight size={18} />}
            </button>
          </div>
        )}

        {/* Step 3: Choose Provider */}
        {step === 3 && (
          <div className="space-y-4">
            <div className="flex items-center gap-3 mb-6">
              <div className="w-10 h-10 rounded-lg bg-indigo-500/20 flex items-center justify-center">
                <Cpu size={20} className="text-indigo-400" />
              </div>
              <div>
                <h2 className="text-lg font-semibold text-dark-text-primary">Choose Your AI</h2>
                <p className="text-sm text-dark-text-secondary">Pick how you want to run AI models</p>
              </div>
            </div>

            <div className="space-y-3">
              {PROVIDERS.map(p => (
                <button
                  key={p.id}
                  onClick={() => setProvider(p.id)}
                  className={`w-full text-left p-4 rounded-lg border transition-all ${
                    provider === p.id
                      ? 'border-indigo-500 bg-indigo-500/10'
                      : 'border-dark-border bg-dark-bg-secondary hover:border-dark-border/80'
                  }`}
                >
                  <div className="flex items-start gap-3">
                    <div className={`mt-0.5 ${provider === p.id ? 'text-indigo-400' : 'text-dark-text-secondary'}`}>
                      {p.icon}
                    </div>
                    <div className="flex-1">
                      <div className="flex items-center justify-between">
                        <span className="font-medium text-dark-text-primary">{p.name}</span>
                        <span className={`text-xs px-2 py-0.5 rounded-full ${
                          p.cost.includes('Free')
                            ? 'bg-green-500/20 text-green-400'
                            : 'bg-amber-500/20 text-amber-400'
                        }`}>
                          {p.cost}
                        </span>
                      </div>
                      <p className="text-sm text-dark-text-secondary mt-1">{p.description}</p>
                    </div>
                    {provider === p.id && (
                      <Check size={20} className="text-indigo-400 mt-0.5" />
                    )}
                  </div>
                </button>
              ))}
            </div>

            <div className="flex gap-3 mt-6">
              <button
                onClick={() => { setProvider('skip'); setStep(4) }}
                className="px-4 py-2.5 rounded-lg text-dark-text-secondary hover:text-dark-text-primary
                           border border-dark-border hover:border-dark-border/80 transition-colors"
              >
                Skip for now
              </button>
              <button
                onClick={() => setStep(4)}
                disabled={!provider}
                className="flex-1 bg-indigo-600 hover:bg-indigo-500 py-2.5 rounded-lg text-white
                           font-medium disabled:opacity-50 disabled:cursor-not-allowed
                           flex items-center justify-center gap-2 transition-colors"
              >
                Continue
                <ChevronRight size={18} />
              </button>
            </div>
          </div>
        )}

        {/* Step 4: Configure */}
        {step === 4 && (
          <div className="space-y-4">
            <div className="flex items-center gap-3 mb-6">
              <div className="w-10 h-10 rounded-lg bg-indigo-500/20 flex items-center justify-center">
                <Key size={20} className="text-indigo-400" />
              </div>
              <div>
                <h2 className="text-lg font-semibold text-dark-text-primary">
                  {provider === 'skip' ? 'All Done!' : `Set Up ${selectedProvider?.name || 'Provider'}`}
                </h2>
                <p className="text-sm text-dark-text-secondary">
                  {provider === 'skip'
                    ? 'You can configure an AI provider later in Settings'
                    : selectedProvider?.needsKey
                      ? 'Enter your API key to get started'
                      : 'Make sure the local server is running'}
                </p>
              </div>
            </div>

            {provider === 'skip' ? (
              <div className="p-4 rounded-lg bg-dark-bg-secondary border border-dark-border">
                <p className="text-dark-text-secondary text-sm">
                  No worries! You can set up an AI provider anytime from the
                  <strong className="text-dark-text-primary"> Settings </strong>
                  page (gear icon in the sidebar).
                </p>
              </div>
            ) : selectedProvider?.needsKey ? (
              <>
                <div className="p-4 rounded-lg bg-dark-bg-secondary border border-dark-border text-sm">
                  {provider === 'openai' && (
                    <p className="text-dark-text-secondary">
                      Get your API key from{' '}
                      <a href="https://platform.openai.com/api-keys" target="_blank" rel="noopener noreferrer"
                         className="text-indigo-400 hover:underline">
                        platform.openai.com/api-keys
                      </a>
                    </p>
                  )}
                  {provider === 'anthropic' && (
                    <p className="text-dark-text-secondary">
                      Get your API key from{' '}
                      <a href="https://console.anthropic.com/settings/keys" target="_blank" rel="noopener noreferrer"
                         className="text-indigo-400 hover:underline">
                        console.anthropic.com
                      </a>
                    </p>
                  )}
                </div>
                <div>
                  <label className="block text-sm text-dark-text-secondary mb-1">API Key</label>
                  <input
                    type="password"
                    value={apiKey}
                    onChange={e => setApiKey(e.target.value)}
                    placeholder={provider === 'openai' ? 'sk-...' : 'sk-ant-...'}
                    className="w-full bg-dark-bg-secondary border border-dark-border rounded-lg
                               px-4 py-2.5 text-dark-text-primary placeholder-dark-text-secondary/50
                               focus:outline-none focus:border-indigo-500 transition-colors font-mono text-sm"
                  />
                </div>
              </>
            ) : (
              <div className="p-4 rounded-lg bg-dark-bg-secondary border border-dark-border text-sm space-y-3">
                {provider === 'lmstudio' && (
                  <>
                    <p className="text-dark-text-secondary">
                      <strong className="text-dark-text-primary">1.</strong> Download LM Studio from{' '}
                      <a href="https://lmstudio.ai" target="_blank" rel="noopener noreferrer"
                         className="text-indigo-400 hover:underline">lmstudio.ai</a>
                    </p>
                    <p className="text-dark-text-secondary">
                      <strong className="text-dark-text-primary">2.</strong> Download a model (e.g. Llama 3.1 8B)
                    </p>
                    <p className="text-dark-text-secondary">
                      <strong className="text-dark-text-primary">3.</strong> Click "Start Server" in LM Studio
                    </p>
                    <p className="text-dark-text-secondary">
                      Engram will connect to <code className="text-indigo-300 bg-dark-bg-primary px-1 rounded">localhost:1234</code> automatically.
                    </p>
                  </>
                )}
                {provider === 'ollama' && (
                  <>
                    <p className="text-dark-text-secondary">
                      <strong className="text-dark-text-primary">1.</strong> Download Ollama from{' '}
                      <a href="https://ollama.com" target="_blank" rel="noopener noreferrer"
                         className="text-indigo-400 hover:underline">ollama.com</a>
                    </p>
                    <p className="text-dark-text-secondary">
                      <strong className="text-dark-text-primary">2.</strong> Run: <code className="text-indigo-300 bg-dark-bg-primary px-1 rounded">ollama pull llama3.1</code>
                    </p>
                    <p className="text-dark-text-secondary">
                      <strong className="text-dark-text-primary">3.</strong> Run: <code className="text-indigo-300 bg-dark-bg-primary px-1 rounded">ollama serve</code>
                    </p>
                    <p className="text-dark-text-secondary">
                      Engram will connect to <code className="text-indigo-300 bg-dark-bg-primary px-1 rounded">localhost:11434</code> automatically.
                    </p>
                  </>
                )}
              </div>
            )}

            <div className="flex gap-3 mt-6">
              <button
                onClick={() => setStep(3)}
                className="px-4 py-2.5 rounded-lg text-dark-text-secondary hover:text-dark-text-primary
                           border border-dark-border hover:border-dark-border/80 transition-colors
                           flex items-center gap-1"
              >
                <ChevronLeft size={18} />
                Back
              </button>
              <button
                onClick={handleFinish}
                disabled={isLoading}
                className="flex-1 bg-indigo-600 hover:bg-indigo-500 py-2.5 rounded-lg text-white
                           font-medium disabled:opacity-50 disabled:cursor-not-allowed
                           flex items-center justify-center gap-2 transition-colors"
              >
                {isLoading ? 'Finishing...' : 'Start Chatting'}
                {!isLoading && <Sparkles size={18} />}
              </button>
            </div>
          </div>
        )}

        {/* Footer */}
        <p className="text-center text-xs text-dark-text-secondary/50 mt-8">
          All data stays on your machine. Non-commercial use only.<br />
          &copy; 2025-2026 Engram Software. See LICENSE for full terms.
        </p>
      </div>
    </div>
  )
}
