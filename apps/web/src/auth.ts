// Supabase Auth with email one-time codes. Without Supabase settings, development
// builds accept a pasted API token instead (see README: "Local scorer testing").
import { createClient, type SupabaseClient } from '@supabase/supabase-js'

const url = import.meta.env.VITE_SUPABASE_URL as string | undefined
const anonKey = import.meta.env.VITE_SUPABASE_ANON_KEY as string | undefined
const DEV_TOKEN_KEY = 'campusxi.devToken'

export const supabase: SupabaseClient | null = url && anonKey ? createClient(url, anonKey) : null
export const devTokenMode = !supabase && import.meta.env.DEV

export async function getToken(): Promise<string | null> {
  if (supabase) {
    const { data } = await supabase.auth.getSession()
    return data.session?.access_token ?? null
  }
  return devTokenMode ? localStorage.getItem(DEV_TOKEN_KEY) : null
}

export async function sendCode(email: string): Promise<void> {
  if (!supabase) throw new Error('sign-in is not configured')
  const { error } = await supabase.auth.signInWithOtp({ email })
  if (error) throw error
}

export async function verifyCode(email: string, code: string): Promise<void> {
  if (!supabase) throw new Error('sign-in is not configured')
  const { error } = await supabase.auth.verifyOtp({ email, token: code, type: 'email' })
  if (error) throw error
}

export function setDevToken(token: string): void {
  localStorage.setItem(DEV_TOKEN_KEY, token.trim())
}

export async function signOut(): Promise<void> {
  if (supabase) await supabase.auth.signOut()
  localStorage.removeItem(DEV_TOKEN_KEY)
}
