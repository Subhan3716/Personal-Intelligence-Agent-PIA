# Personal Intelligence Agent (PIA) Setup Guide

## 1) Install Python dependencies
```bash
python -m venv .venv
.venv\Scripts\activate
pip install --upgrade pip
pip install -r requirements.txt
```

## 2) Provision Supabase memory schema
1. Open your Supabase project SQL editor.
2. Run the following scripts in order:
   - [supabase_schema.sql](supabase_schema.sql) (Core tables + pgvector)
   - [oauth_handshakes.sql](oauth_handshakes.sql) (PKCE Auth support)
   - [user_tokens_migration.sql](user_tokens_migration.sql) (Google Token storage)

## 3) Configure `.env`
Required:
```env
LLAMA_API_KEY=...
LLAMA_MODEL=Llama-3.3-70B-Instruct
LLAMA_COMPAT_BASE_URL=https://api.llama.com/compat/v1/

GROQ_API_KEY=...
SUPABASE_URL=...
SUPABASE_KEY=...
TAVILY_API_KEY=...
```

Optional Google Workspace tool-calling:
```env
GOOGLE_AUTH_CREDENTIALS_PATH=credentials.json
GOOGLE_OAUTH_CLIENT_ID=...
GOOGLE_OAUTH_CLIENT_SECRET=...
GOOGLE_OAUTH_REFRESH_TOKEN=...
GOOGLE_OAUTH_ACCESS_TOKEN=
GOOGLE_OAUTH_TOKEN_JSON=google_oauth_token.json
```

If you are using `credentials.json` client-secrets flow, generate the token file once:
```bash
python google_token_setup.py
```
If Google tools were already authorized before the Gmail/Calendar read scopes were added, run `python google_token_setup.py` again so the token includes inbox summary and agenda access.
For inbox reading and summaries, ensure token scopes include at least one of: `https://www.googleapis.com/auth/gmail.readonly` or `https://www.googleapis.com/auth/gmail.modify`.

## 4) Run PIA
```bash
streamlit run app.py --server.address 0.0.0.0 --server.port 8501
```

## 5) Validate integrations
Inside the app sidebar, click **Refresh Connectivity**.  
PIA will verify Llama, Groq, Supabase, Tavily, and Google Workspace access.
