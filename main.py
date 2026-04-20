from __future__ import annotations

import os
# [Scope Patch] Relax token scope validation to prevent 'Scope has changed' errors
os.environ['OAUTHLIB_RELAX_TOKEN_SCOPE'] = '1'

import hmac
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple


import streamlit as st

from brain import PIAEngine
from config import (
    APP_NAME,
    APP_SHORT_NAME,
    CHAT_HISTORY_LIMIT,
    GOOGLE_AUTH_CREDENTIALS_PATH,
    GOOGLE_COOKIE_KEY,
    GOOGLE_COOKIE_NAME,
    GOOGLE_OAUTH_CLIENT_ID,
    GOOGLE_OAUTH_CLIENT_SECRET,
    GOOGLE_OAUTH_SCOPES,
    GOOGLE_REDIRECT_URI,
    SUPABASE_KEY,

    SUPABASE_MATCH_RPC,
    SUPABASE_URL,
    ensure_data_dirs,
)
from database import SupabaseVectorDatabase
from ui_styles import apply_obsidian_glass_css, configure_page



def init_session_state() -> None:
    defaults: Dict[str, Any] = {
        "auth_user": None,
        "active_chat_id": "",
        "loaded_chat_id": "",
        "chat_messages": [],
        "chat_sessions": [],
        "composer_nonce": 0,
        "composer_tools_open": False,
        "connectivity_report": {},
        "connectivity_checked_at": 0.0,
        "history_filter": "",
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


@st.cache_resource(show_spinner=False)
def get_store() -> SupabaseVectorDatabase:
    return SupabaseVectorDatabase(url=SUPABASE_URL, key=SUPABASE_KEY, match_rpc=SUPABASE_MATCH_RPC)


def get_engine(user_id: str | None = None) -> PIAEngine:
    """Provides a cached PIAEngine instance isolated for the given user_id."""

    @st.cache_resource(show_spinner=False)
    def _get_user_engine(uid: str | None) -> PIAEngine:
        return PIAEngine(store=get_store(), user_id=uid)

    return _get_user_engine(user_id)



def _fallback_local_login() -> Dict[str, str] | None:
    expected_username = os.getenv("APP_USERNAME", "admin")
    expected_password = os.getenv("APP_PASSWORD", "change-me")

    st.markdown("### Local Access")
    st.caption("Google OAuth is not configured. Using local fallback login.")

    with st.form("local-login"):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Sign in", use_container_width=True)

    if not submitted:
        return None

    valid_username = hmac.compare_digest(username.strip(), expected_username)
    valid_password = hmac.compare_digest(password, expected_password)
    if valid_username and valid_password:
        safe_id = re.sub(r"[^a-zA-Z0-9._-]", "-", username.strip().lower())
        email = f"{username.strip()}@local.pia"
        return {
            "id": safe_id,
            "email": email,
            "name": username.strip(),
            "picture": "",
        }

    st.error("Invalid credentials.")
    return None


def _google_oauth_login() -> Dict[str, str] | None:
    try:
        from google_auth_oauthlib.flow import Flow
        from google.oauth2 import id_token
        from google.auth.transport import requests as google_requests
    except ImportError:
        st.error("Missing Google Auth libraries. Please run: pip install google-auth-oauthlib google-auth")
        return None

    # Determine redirect URI dynamically
    redirect_uri = GOOGLE_REDIRECT_URI
    try:
        if hasattr(st, "context") and hasattr(st.context, "headers"):
            origin = st.context.headers.get("Origin") or st.context.headers.get("origin")
            if origin:
                redirect_uri = origin.rstrip("/")
    except Exception:
        pass

    # Determine credentials path (non-blocking)
    candidates = [Path(GOOGLE_AUTH_CREDENTIALS_PATH), Path("credentials.json"), Path("google_credentials.json")]
    credentials_path = next((p for p in candidates if p.exists()), Path(GOOGLE_AUTH_CREDENTIALS_PATH))

    # Access the database store
    store = get_store()



    # 1. Check for Callback First (Handle Redirect)
    query_params = st.query_params
    url_code = query_params.get("code")
    url_state = query_params.get("state")
    
    if url_code and url_state:
        # [Database Handshake] Retrieve verifier from Supabase instead of session state
        code_verifier = store.get_oauth_handshake(url_state)
        
        # Debug Prints (Commented for Production)
        # print(f"\n[PIA-DEBUG] OAuth Callback (DB Handshake):")
        # print(f"  - URL State: {url_state}")
        # print(f"  - Verifier Found in DB: {bool(code_verifier)}")


        if not code_verifier:
            st.error("(invalid_grant) Could not find code verifier in database. Request may have expired.")
            return None

        try:
            # Check if we should use file or config dictionary (Production fallback)
            if credentials_path.exists():
                flow = Flow.from_client_secrets_file(
                    str(credentials_path),
                    scopes=GOOGLE_OAUTH_SCOPES,
                    redirect_uri=redirect_uri
                )
            elif GOOGLE_OAUTH_CLIENT_ID and GOOGLE_OAUTH_CLIENT_SECRET:
                client_config = {
                    "web": {
                        "client_id": GOOGLE_OAUTH_CLIENT_ID,
                        "client_secret": GOOGLE_OAUTH_CLIENT_SECRET,
                        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                        "token_uri": "https://oauth2.googleapis.com/token",
                    }
                }
                flow = Flow.from_client_config(
                    client_config,
                    scopes=GOOGLE_OAUTH_SCOPES,
                    redirect_uri=redirect_uri
                )
            else:
                st.error("Google OAuth credentials not found in Secrets or file.")
                return None

            # Use the retrieved verifier for fetch_token
            flow.fetch_token(code=url_code, code_verifier=code_verifier)
            
            # Verify and decode ID token with a bit of clock leeway
            credentials = flow.credentials
            info = id_token.verify_oauth2_token(
                credentials.id_token,
                google_requests.Request(),
                flow.client_config['client_id'],
                clock_skew_in_seconds=10
            )

            # [Fix] Save the persistent OAuth tokens to Supabase for this user
            user_id = str(info.get("id") or info.get("sub") or info.get("email", "pia-user"))
            store.save_user_oauth_token(user_id, credentials.to_json())
            
            # Cleanup DB and session on SUCCESS
            store.delete_oauth_handshake(url_state)
            to_clear = ["oauth_state", "code_verifier", "auth_url"]
            for key in to_clear:
                if key in st.session_state:
                    del st.session_state[key]
            st.query_params.clear()
            
            return {
                "id": user_id,
                "email": str(info.get("email", "user@pia.local")),
                "name": str(info.get("name") or info.get("email") or "PIA User"),
                "picture": str(info.get("picture", "")),
            }

        except Exception as e:
            st.error(f"Error exchanging code for token: {str(e)}")
            return None

    # 2. Render Login Button (Start Flow)
    # Check if we already have an active handshake in session OR DB
    stored_state = st.session_state.get("oauth_state")
    if not stored_state or "auth_url" not in st.session_state:
        try:
            # Check if we should use file or config dictionary (Production fallback)
            if credentials_path.exists():
                flow = Flow.from_client_secrets_file(
                    str(credentials_path),
                    scopes=GOOGLE_OAUTH_SCOPES,
                    redirect_uri=redirect_uri
                )
            elif GOOGLE_OAUTH_CLIENT_ID and GOOGLE_OAUTH_CLIENT_SECRET:
                client_config = {
                    "web": {
                        "client_id": GOOGLE_OAUTH_CLIENT_ID,
                        "client_secret": GOOGLE_OAUTH_CLIENT_SECRET,
                        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                        "token_uri": "https://oauth2.googleapis.com/token",
                    }
                }
                flow = Flow.from_client_config(
                    client_config,
                    scopes=GOOGLE_OAUTH_SCOPES,
                    redirect_uri=redirect_uri
                )
            else:
                st.error("Google OAuth credentials not found in Secrets or file.")
                return None

            auth_url, state = flow.authorization_url(
                access_type='offline',
                include_granted_scopes='true',
                prompt='consent'
            )
            # [Database Handshake] Persist to DB
            if store.save_oauth_handshake(state, flow.code_verifier):
                st.session_state.auth_url = auth_url
                st.session_state.oauth_state = state
                st.session_state.code_verifier = flow.code_verifier
            else:
                st.error("Failed to save session data to Supabase. This usually means the Secret Key is not yet active or the tables are missing. Please REBOOT the app from the Streamlit Dashboard.")
                return None
        except Exception as e:
            st.error(f"Error generating auth URL: {str(e)}")
            return None

    st.link_button("Sign in with Google", st.session_state.auth_url, type="primary", use_container_width=True)
    return None







def authenticate_user() -> Dict[str, str]:
    existing = st.session_state.get("auth_user")
    if existing:
        return existing

    st.markdown(
        "<h1 style='text-align: center; margin-bottom: 0.5rem;'>Personal Intelligence Agent</h1>",
        unsafe_allow_html=True,
    )
    st.markdown(
        "<p style='text-align: center; color: var(--text-muted); opacity: 0.8;'>Secure multi-user workspace.</p>",
        unsafe_allow_html=True,
    )

    user = _google_oauth_login()
    if user:
        st.session_state.auth_user = user
        st.session_state.user_email = user.get("email") # Strictly for multi-user isolation
        st.rerun()

    # If we are here, nobody is logged in yet
    st.stop()
    return {} # Never reached





def _new_chat_title() -> str:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    return f"New Chat ({timestamp})"


def _short_title(prompt: str) -> str:
    clean = re.sub(r"\s+", " ", prompt).strip()
    if len(clean) <= 58:
        return clean
    return clean[:55].rstrip() + "..."


def _user_initial(user: Dict[str, str]) -> str:
    name = str(user.get("name") or user.get("email") or "P").strip()
    return name[:1].upper() or "P"


def _switch_chat(chat_id: str) -> None:
    if not chat_id:
        return
    st.session_state.active_chat_id = chat_id
    st.session_state.loaded_chat_id = ""
    st.rerun()


def _delete_chat(user_id: str, store: SupabaseVectorDatabase, chat_id: str) -> None:
    if not chat_id:
        return
    ok = store.delete_chat_session(user_id=user_id, chat_id=chat_id)
    if not ok:
        st.warning("Unable to delete this chat right now.")
        return

    st.session_state.chat_sessions = [s for s in st.session_state.get("chat_sessions", []) if s.get("id") != chat_id]
    st.session_state.chat_messages = []
    st.session_state.loaded_chat_id = ""
    remaining = st.session_state.chat_sessions
    st.session_state.active_chat_id = str(remaining[0].get("id", "")) if remaining else ""
    if not remaining:
        created = store.create_chat_session(user_id=user_id, title=_new_chat_title())
        st.session_state.chat_sessions = [created]
        st.session_state.active_chat_id = created["id"]
    st.rerun()


def _start_new_chat(user_id: str, store: SupabaseVectorDatabase) -> None:
    created = store.create_chat_session(user_id=user_id, title=_new_chat_title())
    st.session_state.active_chat_id = created["id"]
    st.session_state.loaded_chat_id = ""
    st.session_state.chat_messages = []
    st.rerun()


def _update_session_title(chat_id: str, title: str) -> None:
    sessions = list(st.session_state.get("chat_sessions") or [])
    for session in sessions:
        if session.get("id") == chat_id:
            session["title"] = title
            session["updated_at"] = datetime.now().isoformat()
            break
    st.session_state.chat_sessions = sessions

def _parse_iso_datetime(raw: str) -> datetime | None:
    value = str(raw or "").strip()
    if not value:
        return None
    try:
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        return datetime.fromisoformat(value)
    except Exception:
        return None


def _history_buckets(sessions: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    buckets: Dict[str, List[Dict[str, Any]]] = {
        "Today": [],
        "Yesterday": [],
        "This Week": [],
        "Older": [],
    }

    now = datetime.now().date()
    for session in sessions:
        stamp = _parse_iso_datetime(str(session.get("updated_at") or session.get("created_at") or ""))
        if stamp is None:
            buckets["Older"].append(session)
            continue

        age = (now - stamp.date()).days
        if age <= 0:
            buckets["Today"].append(session)
        elif age == 1:
            buckets["Yesterday"].append(session)
        elif age <= 7:
            buckets["This Week"].append(session)
        else:
            buckets["Older"].append(session)

    return buckets


def ensure_chat_context(store: SupabaseVectorDatabase, user_id: str) -> None:
    sessions = store.list_chat_sessions(user_id=user_id, limit=80)
    if not sessions:
        created = store.create_chat_session(user_id=user_id, title=_new_chat_title())
        sessions = [created]

    st.session_state.chat_sessions = sessions
    known_ids = {session.get("id") for session in sessions}

    if not st.session_state.active_chat_id or st.session_state.active_chat_id not in known_ids:
        st.session_state.active_chat_id = sessions[0]["id"]

    active_chat_id = st.session_state.active_chat_id
    if st.session_state.loaded_chat_id == active_chat_id:
        return

    loaded = store.load_chat_messages(chat_id=active_chat_id, limit=CHAT_HISTORY_LIMIT)
    st.session_state.chat_messages = [
        {
            "role": row.get("role", "assistant"),
            "content": row.get("content", ""),
            "metadata": row.get("metadata", {}),
            "created_at": row.get("created_at", ""),
        }
        for row in loaded
        if row.get("content")
    ]
    st.session_state.loaded_chat_id = active_chat_id

    if st.session_state.chat_messages:
        return

    welcome = (
        f"Welcome to **{APP_SHORT_NAME}**. Upload docs, images, data, or voice input and I will "
        "reason over them with cloud memory."
    )
    store.save_chat_message(
        chat_id=active_chat_id,
        user_id=user_id,
        role="assistant",
        content=welcome,
        metadata={"kind": "welcome"},
    )
    st.session_state.chat_messages.append({"role": "assistant", "content": welcome, "metadata": {}})


def _refresh_connectivity(engine: PIAEngine, max_age_seconds: int = 90) -> None:
    now = time.time()
    last = float(st.session_state.get("connectivity_checked_at") or 0.0)
    if not st.session_state.connectivity_report or now - last > max_age_seconds:
        st.session_state.connectivity_report = engine.run_connectivity_validation()
        st.session_state.connectivity_checked_at = now


def _status_css(status: str) -> str:
    normalized = str(status).strip().upper()
    if normalized.startswith("OK"):
        return "pia-status-ok"
    if normalized.startswith("PARTIAL"):
        return "pia-status-warn"
    return "pia-status-fail"


def render_sidebar(user: Dict[str, str], store: SupabaseVectorDatabase, engine: PIAEngine) -> None:
    with st.sidebar:
        st.markdown(
            f"""
            <div class="pia-sidebar-header">
                <div class="pia-sidebar-brand-row">
                    <div class="pia-sidebar-logo">{APP_SHORT_NAME[:1]}</div>
                    <div>
                        <div class="pia-sidebar-title">{APP_SHORT_NAME}</div>
                        <div class="pia-sidebar-subtitle">Personal Intelligence Agent</div>
                    </div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.markdown(
            f"<div class='pia-user-pill'><strong>{user['name']}</strong><br/><span>{user['email']}</span></div>",
            unsafe_allow_html=True,
        )

        st.markdown("<div class='pia-sidebar-section-title'>Workspace</div>", unsafe_allow_html=True)
        history_filter = st.text_input(
            "Search chats",
            key="history_filter",
            placeholder="Search chat history",
            label_visibility="collapsed",
        )

        if st.button("New Chat", use_container_width=True, type="primary"):
            _start_new_chat(user_id=user["id"], store=store)

        st.markdown("<div class='pia-sidebar-section-title'>Chat History</div>", unsafe_allow_html=True)
        buckets = _history_buckets(st.session_state.chat_sessions)
        filter_text = history_filter.strip().lower()
        for bucket_name, entries in buckets.items():
            filtered_entries = []
            for session in entries:
                title = str(session.get("title") or "Untitled")
                if filter_text and filter_text not in title.lower():
                    continue
                filtered_entries.append(session)
            if not filtered_entries:
                continue
            st.markdown(f"<div class='pia-history-label'>{bucket_name}</div>", unsafe_allow_html=True)
            for session in filtered_entries:
                chat_id = str(session.get("id", ""))
                title = str(session.get("title") or "Untitled")
                if len(title) > 42:
                    title = title[:39].rstrip() + "..."
                selected = chat_id == st.session_state.active_chat_id
                row_left, row_right = st.columns([0.85, 0.15], gap="small")
                with row_left:
                    if st.button(
                        title,
                        key=f"chat_{chat_id}",
                        use_container_width=True,
                        type="primary" if selected else "secondary",
                    ):
                        _switch_chat(chat_id)
                with row_right:
                    if st.button("⋮", key=f"chat_menu_{chat_id}", use_container_width=True):
                        st.session_state[f"delete_chat_confirm_{chat_id}"] = not bool(
                            st.session_state.get(f"delete_chat_confirm_{chat_id}")
                        )

                if st.session_state.get(f"delete_chat_confirm_{chat_id}"):
                    confirm_left, confirm_right = st.columns([0.6, 0.4], gap="small")
                    with confirm_left:
                        if st.button("Delete", key=f"delete_chat_{chat_id}", use_container_width=True):
                            _delete_chat(user_id=user["id"], store=store, chat_id=chat_id)
                    with confirm_right:
                        if st.button("Cancel", key=f"cancel_delete_chat_{chat_id}", use_container_width=True):
                            st.session_state[f"delete_chat_confirm_{chat_id}"] = False
                            st.rerun()

        st.markdown("<div class='pia-sidebar-section-title'>API Connectivity</div>", unsafe_allow_html=True)
        stamp = float(st.session_state.get("connectivity_checked_at") or 0.0)
        if stamp > 0:
            check_time = datetime.fromtimestamp(stamp).strftime("%H:%M:%S")
            st.caption(f"Last checked: {check_time}")

        if st.button("Refresh Connectivity", use_container_width=True):
            st.session_state.connectivity_report = engine.run_connectivity_validation()
            st.session_state.connectivity_checked_at = time.time()

        report = st.session_state.connectivity_report or {}
        for service in [
            "Llama",
            "Llama Engine",
            "Llama Model",
            "Groq",
            "Supabase",
            "Tavily",
            "Google Workspace",
        ]:
            status = str(report.get(service, "Unknown"))
            css = _status_css(status)
            dot = "&#9679;"
            st.markdown(
                f"<div class='pia-connect-row'><span class='{css}'>{dot}</span><strong>{service}</strong><span>{status}</span></div>",
                unsafe_allow_html=True,
            )

        if st.button("Sign out", use_container_width=True):
            auth = st.session_state.get("google_authenticator")
            if auth is not None and hasattr(auth, "logout"):
                try:
                    auth.logout()
                except Exception:
                    pass
            st.session_state.auth_user = None
            st.session_state.active_chat_id = ""
            st.session_state.loaded_chat_id = ""
            st.session_state.chat_messages = []
            st.session_state.chat_sessions = []
            st.rerun()


def _active_chat_title() -> str:
    for session in st.session_state.chat_sessions:
        if session.get("id") == st.session_state.active_chat_id:
            return str(session.get("title") or "")
    return ""


def render_topbar(user: Dict[str, str], store: SupabaseVectorDatabase, engine: PIAEngine) -> None:
    title = _active_chat_title() or "New chat"
    st.markdown("<div class='pia-topbar-shell'>", unsafe_allow_html=True)
    left, center, right = st.columns([1.2, 2.3, 1.5], gap="small")
    with left:
        st.markdown(
            """
            <div class="pia-brand-lockup">
                <div class="pia-brand-mark">P</div>
                <div>
                    <div class="pia-brand-name">PIA</div>
                    <div class="pia-brand-subtitle">Personal Intelligence Agent</div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with center:
        st.markdown(
            f"""
            <div class="pia-active-chat-shell">
                <div class="pia-active-chat-title">{title}</div>
                <div class="pia-active-chat-subtitle">Subhan_Fiveerr Chat Client</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with right:
        action_left, action_mid, action_right = st.columns([1.65, 0.8, 0.75], gap="small")
        with action_left:
            if st.button("Upgrade", key="topbar_upgrade", use_container_width=True, type="primary"):
                st.toast("Upgrade action placeholder.")
        with action_mid:
            if st.button("+", key="topbar_new_chat", use_container_width=True):
                _start_new_chat(user_id=user["id"], store=store)
        with action_right:
            if st.button(_user_initial(user), key="topbar_user_badge", use_container_width=True):
                st.toast(user["email"])
    st.markdown("</div>", unsafe_allow_html=True)


def render_workspace_controls(user: Dict[str, str], store: SupabaseVectorDatabase, engine: PIAEngine) -> None:
    sessions = st.session_state.chat_sessions
    session_ids = [str(session.get("id", "")) for session in sessions if session.get("id")]
    if not session_ids:
        return

    active_chat_id = st.session_state.active_chat_id if st.session_state.active_chat_id in session_ids else session_ids[0]
    label_map = {str(session.get("id", "")): str(session.get("title") or "Untitled") for session in sessions}

    st.markdown("<div class='pia-workspace-card'>", unsafe_allow_html=True)
    st.markdown("<div class='pia-section-label'>Conversation</div>", unsafe_allow_html=True)
    left, middle, right = st.columns([2.6, 1.0, 1.0], gap="small")
    with left:
        selected_chat = st.selectbox(
            "Conversation",
            session_ids,
            index=session_ids.index(active_chat_id),
            format_func=lambda chat_id: label_map.get(chat_id, "Untitled"),
            label_visibility="collapsed",
            key="workspace_chat_picker",
        )
    with middle:
        if st.button("Refresh", key="workspace_refresh_connectivity", use_container_width=True):
            st.session_state.connectivity_report = engine.run_connectivity_validation()
            st.session_state.connectivity_checked_at = time.time()
            st.rerun()
    with right:
        if st.button("History", key="workspace_history_hint", use_container_width=True):
            st.toast("Use the left sidebar or this conversation picker to switch chats.")

    st.markdown(
        f"<div class='pia-history-meta'>{len(session_ids)} chats available. Sidebar history and main chat switching are both enabled.</div>",
        unsafe_allow_html=True,
    )
    st.markdown("</div>", unsafe_allow_html=True)

    if selected_chat != active_chat_id:
        _switch_chat(selected_chat)


def render_hero() -> None:
    title = _active_chat_title() or "New Chat"
    st.markdown(
        f"""
        <div class="pia-hero">
            <div class="pia-kicker">Gemini-style Workspace</div>
            <div class="pia-title">Ask, Upload, Summarize, Schedule</div>
            <p class="pia-subtitle">{title}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

def mount_copy_buttons() -> None:
    st.html(
        """
        <script>
        (function () {
          const parentDoc = window.parent && window.parent.document;
          if (!parentDoc) return;

          function attachButtons() {
            const blocks = parentDoc.querySelectorAll('.stMarkdown pre');
            blocks.forEach((pre) => {
              if (pre.dataset.piaCopyReady === '1') return;
              pre.dataset.piaCopyReady = '1';

              pre.style.position = 'relative';
              const button = parentDoc.createElement('button');
              button.type = 'button';
              button.innerHTML = '&#9776;';
              button.className = 'pia-copy-btn';
              button.textContent = 'Copy';

              button.addEventListener('click', async () => {
                const text = pre.innerText || '';
                try {
                  await navigator.clipboard.writeText(text);
                  button.textContent = 'Copied';
                } catch (err) {
                  button.textContent = 'Failed';
                }
                setTimeout(() => { button.textContent = 'Copy'; }, 1200);
              });

              pre.appendChild(button);
            });
          }

          attachButtons();
          if (!window.parent.__piaCopyObserver) {
            const observer = new MutationObserver(() => attachButtons());
            observer.observe(parentDoc.body, { childList: true, subtree: true });
            window.parent.__piaCopyObserver = observer;
          }
        })();
        </script>
        """,
        unsafe_allow_javascript=True,
    )


def mount_sidebar_toggle() -> None:
    st.html(
        """
        <script>
        (function () {
          const parentDoc = window.parent && window.parent.document;
          if (!parentDoc) return;

          function isVisible(el) {
            if (!el) return false;
            const style = window.getComputedStyle(el);
            return style.display !== 'none' && style.visibility !== 'hidden' && style.opacity !== '0';
          }

          function findControl(selectorList) {
            for (const selector of selectorList) {
              const found = parentDoc.querySelector(selector);
              if (found) return found;
            }
            return null;
          }

          function toggleSidebar() {
            const sidebar = parentDoc.querySelector('[data-testid="stSidebar"]');
            const sidebarRect = sidebar ? sidebar.getBoundingClientRect() : null;
            const sidebarOpen = !!(sidebarRect && sidebarRect.width > 90 && sidebarRect.left > -40);
            const collapseBtn = findControl([
              'button[title="Collapse sidebar"]',
              'button[aria-label="Collapse sidebar"]',
              '[data-testid="stSidebarCollapseButton"] button',
            ]);
            const expandBtn = findControl([
              'button[title="Expand sidebar"]',
              'button[aria-label="Expand sidebar"]',
              '[data-testid="stSidebarCollapsedControl"] button',
            ]);

            if (sidebarOpen && collapseBtn) {
              collapseBtn.click();
              return;
            }
            if (!sidebarOpen && expandBtn) {
              expandBtn.click();
              return;
            }
            if (collapseBtn) {
              collapseBtn.click();
              return;
            }
            if (expandBtn) {
              expandBtn.click();
            }
          }

          function ensureButton() {
            let button = parentDoc.getElementById('pia-sidebar-toggle');
            if (!button) {
              button = parentDoc.createElement('button');
              button.id = 'pia-sidebar-toggle';
              button.type = 'button';
              button.innerHTML = '&#9776;';
              Object.assign(button.style, {
                position: 'fixed',
                top: '16px',
                left: '14px',
                width: '42px',
                height: '42px',
                borderRadius: '14px',
                border: '1px solid rgba(86, 124, 188, 0.35)',
                background: '#1f2024',
                color: '#d9e8ff',
                fontSize: '21px',
                lineHeight: '1',
                zIndex: '999999',
                cursor: 'pointer',
                boxShadow: '0 10px 24px rgba(0,0,0,0.28)',
                fontWeight: '700',
              });
              parentDoc.body.appendChild(button);
            }

            button.setAttribute('aria-label', 'Toggle sidebar');
            button.title = 'Toggle sidebar';
            button.onclick = toggleSidebar;
          }

          ensureButton();
          if (!window.parent.__piaSidebarObserver) {
            const observer = new MutationObserver(() => ensureButton());
            observer.observe(parentDoc.body, { childList: true, subtree: true });
            window.parent.__piaSidebarObserver = observer;
          }
        })();
        </script>
        """,
        unsafe_allow_javascript=True,
    )


def render_messages() -> None:
    for item in st.session_state.chat_messages:
        role = item.get("role", "assistant")
        if role not in {"user", "assistant"}:
            role = "assistant"
        content = item.get("content", "")
        with st.chat_message(role):
            st.markdown(content)


def _collect_current_uploads() -> Tuple[List[Tuple[str, bytes]], Any, bool]:
    nonce = st.session_state.composer_nonce
    upload_key = f"composer_uploads_{nonce}"
    voice_key = f"composer_voice_{nonce}"
    tools_toggle_key = f"composer_tools_toggle_{nonce}"
    send_key = f"composer_send_{nonce}"

    st.markdown("<div class='pia-composer-shell'>", unsafe_allow_html=True)
    toggle_col, hint_col, send_col = st.columns([0.9, 3.3, 0.8], gap="small")
    with toggle_col:
        if st.button("+ Tools", key=tools_toggle_key, use_container_width=True):
            st.session_state.composer_tools_open = not bool(st.session_state.get("composer_tools_open"))
    with hint_col:
        st.markdown(
            "<div class='pia-composer-label'>Tools are hidden by default. Open only when needed.</div>",
            unsafe_allow_html=True,
        )
    with send_col:
        send_tools_payload = st.button("Send", key=send_key, type="primary", use_container_width=True)

    if st.session_state.get("composer_tools_open"):
        left, right = st.columns([1.15, 2.85], gap="small")
        with left:
            st.markdown("<div class='pia-composer-label'>Voice Input</div>", unsafe_allow_html=True)
            st.audio_input("Record voice", key=voice_key, label_visibility="collapsed")
        with right:
            st.markdown("<div class='pia-composer-label'>Attachments</div>", unsafe_allow_html=True)
            st.file_uploader(
                "Attach files",
                key=upload_key,
                accept_multiple_files=True,
                type=[
                    "pdf",
                    "docx",
                    "txt",
                    "csv",
                    "xlsx",
                    "xls",
                    "png",
                    "jpg",
                    "jpeg",
                    "webp",
                    "bmp",
                    "gif",
                    "tif",
                    "tiff",
                    "heic",
                    "heif",
                    "mp4",
                    "mov",
                    "avi",
                    "mkv",
                    "wav",
                    "mp3",
                    "m4a",
                    "ogg",
                    "flac",
                    "webm",
                ],
                label_visibility="collapsed",
            )
    st.markdown("</div>", unsafe_allow_html=True)

    uploaded_files = st.session_state.get(upload_key) or []
    voice_clip = st.session_state.get(voice_key)
    payloads = [(uploaded.name, uploaded.getvalue()) for uploaded in uploaded_files if uploaded is not None]
    return payloads, voice_clip, send_tools_payload


def handle_user_turn(user: Dict[str, str], store: SupabaseVectorDatabase, engine: PIAEngine) -> None:
    uploads, voice_clip, send_tools_payload = _collect_current_uploads()
    user_prompt = st.chat_input("Ask PIA")
    if user_prompt is None and not send_tools_payload:
        return

    prompt = str(user_prompt or "").strip()
    if not prompt and voice_clip is not None:
        transcribed = engine.transcribe_audio(payload=voice_clip.getvalue(), filename=voice_clip.name or "voice.wav")
        prompt = transcribed.strip()
        if transcribed:
            st.info(f"Voice transcript: {transcribed}")
        else:
            diagnostics = engine.last_transcription_error()
            st.warning(diagnostics or "Voice transcription returned an empty result.")

    if not prompt and uploads:
        prompt = "Analyze the uploaded files and give me the key insights."

    if not prompt:
        st.warning("Type a prompt, or use Send with voice/attachments.")
        return

    active_chat_id = st.session_state.active_chat_id

    attachment_insights = engine.process_attachments(
        user_id=user["id"],
        chat_id=active_chat_id,
        prompt=prompt,
        uploads=uploads,
    )

    with st.chat_message("user"):
        st.markdown(prompt)

    st.session_state.chat_messages.append({"role": "user", "content": prompt, "metadata": {}})
    store.save_chat_message(
        chat_id=active_chat_id,
        user_id=user["id"],
        role="user",
        content=prompt,
        metadata={"uploads": [name for name, _ in uploads]},
    )

    with st.chat_message("assistant"):
        if attachment_insights.errors:
            for error in attachment_insights.errors:
                st.warning(error)

        if attachment_insights.notes:
            with st.expander("Attachment Insights", expanded=True):
                for note in attachment_insights.notes:
                    st.markdown(f"- {note}")

        for figure in attachment_insights.figures:
            st.plotly_chart(figure, use_container_width=True)

        try:
            streamed = st.write_stream(
                engine.stream_response(
                    user_prompt=prompt,
                    user_id=user["id"],
                    chat_id=active_chat_id,
                    chat_history=st.session_state.chat_messages,
                    attachment_notes=attachment_insights.notes,
                )
            )
        except Exception as exc:
            streamed = f"PIA could not stream a response: {exc}"

        answer = str(streamed or "").strip()
        if not answer:
            answer = "I was unable to generate a response. Please retry."

    st.session_state.chat_messages.append({"role": "assistant", "content": answer, "metadata": {}})
    store.save_chat_message(
        chat_id=active_chat_id,
        user_id=user["id"],
        role="assistant",
        content=answer,
        metadata={
            "attachment_notes": attachment_insights.notes,
            "attachment_errors": attachment_insights.errors,
        },
    )

    current_title = _active_chat_title()
    if current_title.startswith("New Chat"):
        new_title = _short_title(prompt)
        store.update_chat_title(chat_id=active_chat_id, title=new_title)
        _update_session_title(chat_id=active_chat_id, title=new_title)

    used_non_text_inputs = bool(uploads) or (voice_clip is not None)
    st.session_state.loaded_chat_id = active_chat_id
    if used_non_text_inputs:
        st.session_state.composer_nonce += 1
        st.session_state.composer_tools_open = False
        st.rerun()

def main() -> None:
    # [Persistence Patch] Initialize session state IMMEDIATELY
    init_session_state()
    
    ensure_data_dirs()
    configure_page()
    apply_obsidian_glass_css()


    user = authenticate_user()
    
    # Strictly isolate user email for all operations
    st.session_state.user_email = user.get("email")
    
    store = get_store()
    
    try:
        engine = get_engine(user_id=user["id"])
    except Exception as e:
        st.error(f"Failed to initialize PIA Engine: {str(e)}")
        st.stop()

    # Register user in profiles
    try:
        store.upsert_user_profile(
            user_id=user["id"],
            email=user["email"],
            display_name=user["name"],
            avatar_url=user.get("picture", ""),
        )
    except Exception:
        pass # Non-critical failure

    try:
        _refresh_connectivity(engine=engine, max_age_seconds=600)
    except Exception:
        # Don't let connectivity check crash the app
        pass

    ensure_chat_context(store=store, user_id=user["id"])
    render_sidebar(user=user, store=store, engine=engine)

    render_topbar(user=user, store=store, engine=engine)

    render_messages()
    mount_copy_buttons()
    mount_sidebar_toggle()
    handle_user_turn(user=user, store=store, engine=engine)



if __name__ == "__main__":
    main()

