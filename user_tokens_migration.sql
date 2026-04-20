-- Migration: Create user_oauth_tokens table for multi-user support
-- Run this in your Supabase SQL Editor

CREATE TABLE IF NOT EXISTS public.user_oauth_tokens (
    user_id TEXT PRIMARY KEY REFERENCES public.user_profiles(id) ON DELETE CASCADE,
    token_json JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Enable RLS (Row Level Security)
ALTER TABLE public.user_oauth_tokens ENABLE ROW LEVEL SECURITY;

-- Policy: Users can only see/update their own tokens
CREATE POLICY "Users can only manage their own tokens" 
ON public.user_oauth_tokens 
FOR ALL 
USING (auth.uid()::text = user_id);

-- Note: Depending on your Supabase setup, you might need to adjust auth.uid() to match 
-- how your users are authenticated. For Streamlit Cloud + Supabase API Key auth, 
-- simple user_id matching is usually handled in the application layer.
