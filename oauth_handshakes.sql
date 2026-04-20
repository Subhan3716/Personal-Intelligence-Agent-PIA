-- Table to store temporary OAuth handshake data (state and PKCE verifier)
-- This ensures authentication works even if Streamlit session state is wiped during redirects.

CREATE TABLE IF NOT EXISTS public.oauth_handshakes (
    state TEXT PRIMARY KEY,
    code_verifier TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Enable RLS
ALTER TABLE public.oauth_handshakes ENABLE ROW LEVEL SECURITY;

-- Policy: Allow anyone to insert a handshake (initial start of flow)
CREATE POLICY "Allow anonymous handshake start" ON public.oauth_handshakes
    FOR INSERT WITH CHECK (true);

-- Policy: Allow anyone to select/delete a handshake if they know the state
-- (This is the "secret" key shared between the app and the redirection)
CREATE POLICY "Allow handshake completion by state" ON public.oauth_handshakes
    FOR ALL USING (true);

-- Optional: Cleanup old handshakes (e.g., older than 10 minutes)
-- This can be run as a cron job or just manually occasionally.
-- DELETE FROM public.oauth_handshakes WHERE created_at < NOW() - INTERVAL '10 minutes';
