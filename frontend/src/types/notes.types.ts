/**
 * TypeScript types for the Notes / Knowledge Base system.
 */

export interface Note {
  id: string
  user_id: string
  title: string
  content: string
  folder: string | null
  parent_id: string | null
  tags: string[]
  is_folder: boolean
  is_pinned: boolean
  created_at: string
  updated_at: string
  last_edited_by: string
  child_count: number
}
