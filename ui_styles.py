from __future__ import annotations

import streamlit as st

from config import APP_ICON, APP_NAME


def configure_page() -> None:
    st.set_page_config(
        page_title=APP_NAME,
        page_icon=APP_ICON,
        layout="wide",
        initial_sidebar_state="expanded",
    )


def apply_obsidian_glass_css() -> None:
    st.markdown(
        """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Manrope:wght@400;500;600;700;800&family=Space+Grotesk:wght@500;700&family=IBM+Plex+Mono:wght@400;600&display=swap');

        :root {
            --pia-bg: #0f1116;
            --pia-surface: #191c22;
            --pia-surface-soft: #1f222a;
            --pia-border: rgba(120, 150, 205, 0.24);
            --pia-text: #e9eef9;
            --pia-muted: #9aa9c4;
            --pia-accent: #3a8bfd;
            --pia-accent-2: #53b6ff;
            --pia-ok: #56c786;
            --pia-warn: #f3c04c;
            --pia-danger: #ff6b86;
            --pia-code-bg: #141821;
        }

        #MainMenu { visibility: hidden; }
        footer { visibility: hidden; }
        header[data-testid="stHeader"] {
            background: transparent;
            border: none;
        }
        [data-testid="stToolbar"] {
            right: 0.5rem;
        }

        html, body, [data-testid="stAppViewContainer"] {
            background:
                radial-gradient(58rem 30rem at 50% -18%, rgba(58, 139, 253, 0.18) 0%, rgba(58, 139, 253, 0) 64%),
                linear-gradient(180deg, #0d1015 0%, #0f1116 100%);
            color: var(--pia-text);
            font-family: "Manrope", sans-serif;
        }

        .block-container {
            max-width: 1200px;
            padding-top: 0.55rem;
            padding-bottom: 1.0rem;
        }

        [data-testid="stSidebar"] {
            background: linear-gradient(180deg, #171a20 0%, #15181e 100%);
            border-right: 1px solid var(--pia-border);
            min-width: 320px !important;
            max-width: 320px !important;
            box-shadow: 14px 0 28px rgba(0, 0, 0, 0.28);
        }

        [data-testid="stSidebar"] * {
            font-family: "Manrope", sans-serif;
        }

        [data-testid="stSidebarCollapsedControl"],
        [data-testid="stSidebarCollapseButton"],
        button[title="Collapse sidebar"],
        button[title="Expand sidebar"],
        button[aria-label="Collapse sidebar"],
        button[aria-label="Expand sidebar"] {
            opacity: 0 !important;
            visibility: hidden !important;
            pointer-events: none !important;
            width: 0 !important;
            height: 0 !important;
            min-width: 0 !important;
            min-height: 0 !important;
            margin: 0 !important;
            padding: 0 !important;
            border: none !important;
            overflow: hidden !important;
        }

        .pia-sidebar-header {
            border: 1px solid var(--pia-border);
            border-radius: 16px;
            background: linear-gradient(145deg, rgba(58, 139, 253, 0.18), rgba(26, 30, 38, 0.94));
            padding: 0.8rem;
            margin-bottom: 0.62rem;
            box-shadow: 0 12px 26px rgba(0, 0, 0, 0.24);
        }

        .pia-sidebar-brand-row {
            display: flex;
            align-items: center;
            gap: 0.75rem;
        }

        .pia-sidebar-logo {
            width: 2.15rem;
            height: 2.15rem;
            border-radius: 14px;
            display: grid;
            place-items: center;
            background: linear-gradient(135deg, var(--pia-accent), var(--pia-accent-2));
            color: #ffffff;
            font-weight: 800;
            font-family: "Space Grotesk", sans-serif;
        }

        .pia-sidebar-title {
            font-size: 1rem;
            font-weight: 800;
            letter-spacing: -0.02em;
            color: var(--pia-text);
            font-family: "Space Grotesk", sans-serif;
        }

        .pia-sidebar-subtitle {
            margin-top: 0.08rem;
            font-size: 0.7rem;
            text-transform: uppercase;
            letter-spacing: 0.08em;
            color: #8fbaf8;
            font-weight: 700;
        }

        .pia-user-pill {
            border: 1px solid var(--pia-border);
            border-radius: 14px;
            background: rgba(31, 34, 42, 0.95);
            padding: 0.58rem 0.72rem;
            margin-bottom: 0.72rem;
            color: var(--pia-text);
            font-weight: 600;
        }

        .pia-user-pill span {
            color: var(--pia-muted);
            font-weight: 500;
            font-size: 0.8rem;
        }

        .pia-sidebar-section-title {
            margin: 0.55rem 0 0.4rem 0;
            color: #9db2d5;
            font-size: 0.74rem;
            font-weight: 700;
            letter-spacing: 0.09em;
            text-transform: uppercase;
        }

        .pia-history-label {
            margin: 0.7rem 0 0.28rem 0;
            font-size: 0.68rem;
            text-transform: uppercase;
            letter-spacing: 0.09em;
            color: #8095b6;
            font-weight: 700;
        }

        .pia-connect-row {
            display: grid;
            grid-template-columns: 0.8rem 5rem 1fr;
            align-items: center;
            gap: 0.35rem;
            border: 1px solid var(--pia-border);
            border-radius: 12px;
            background: rgba(31, 34, 42, 0.94);
            padding: 0.4rem 0.54rem;
            margin-bottom: 0.34rem;
            font-size: 0.79rem;
            color: var(--pia-text);
        }

        .pia-status-ok { color: var(--pia-ok); font-weight: 700; }
        .pia-status-warn { color: var(--pia-warn); font-weight: 700; }
        .pia-status-fail { color: var(--pia-danger); font-weight: 700; }

        .pia-topbar-shell,
        .pia-workspace-card,
        .pia-hero {
            border: 1px solid var(--pia-border);
            border-radius: 18px;
            background: linear-gradient(180deg, rgba(25, 28, 34, 0.95), rgba(20, 23, 29, 0.95));
            box-shadow: 0 12px 26px rgba(0, 0, 0, 0.22);
            animation: pia-fade-up 0.4s ease;
        }

        .pia-topbar-shell {
            padding: 0.68rem 0.82rem;
            margin-bottom: 0.55rem;
        }

        .pia-brand-lockup {
            display: flex;
            align-items: center;
            gap: 0.78rem;
            min-height: 3rem;
        }

        .pia-brand-mark {
            width: 2.35rem;
            height: 2.35rem;
            border-radius: 14px;
            display: grid;
            place-items: center;
            background: linear-gradient(135deg, var(--pia-accent), var(--pia-accent-2));
            color: #ffffff;
            font-family: "Space Grotesk", sans-serif;
            font-size: 1rem;
            font-weight: 800;
        }

        .pia-brand-name {
            color: var(--pia-text);
            font-size: 1.12rem;
            font-weight: 800;
            font-family: "Space Grotesk", sans-serif;
            letter-spacing: -0.02em;
        }

        .pia-brand-subtitle,
        .pia-active-chat-subtitle,
        .pia-history-meta,
        .pia-subtitle {
            color: var(--pia-muted);
        }

        .pia-active-chat-shell {
            text-align: center;
            padding-top: 0.18rem;
        }

        .pia-active-chat-title {
            font-size: 1.15rem;
            font-weight: 700;
            color: var(--pia-text);
            letter-spacing: -0.02em;
        }

        .pia-active-chat-subtitle {
            font-size: 0.84rem;
            margin-top: 0.12rem;
        }

        .pia-workspace-card {
            padding: 0.88rem 1rem;
            margin-bottom: 0.8rem;
            display: none;
        }

        .pia-section-label {
            margin-bottom: 0.45rem;
            color: #5b6c8c;
            font-size: 0.76rem;
            font-weight: 700;
            letter-spacing: 0.08em;
            text-transform: uppercase;
        }

        .pia-history-meta {
            margin-top: 0.42rem;
            font-size: 0.85rem;
        }

        .pia-kicker {
            font-size: 0.76rem;
            text-transform: uppercase;
            letter-spacing: 0.11em;
            color: #82abed;
            font-weight: 700;
        }

        .pia-title {
            margin-top: 0.2rem;
            margin-bottom: 0.18rem;
            font-size: 2.25rem;
            font-weight: 800;
            letter-spacing: -0.03em;
            color: var(--pia-text);
            font-family: "Space Grotesk", sans-serif;
        }

        .pia-hero {
            padding: 0.95rem 1.05rem;
            margin-bottom: 0.8rem;
            display: none;
        }

        .pia-subtitle {
            margin: 0;
            font-weight: 500;
        }

        .stChatMessage {
            border: none !important;
            border-radius: 0;
            background: transparent !important;
            box-shadow: none !important;
            animation: pia-fade-up 0.18s ease;
            padding-top: 0.15rem;
            padding-bottom: 0.15rem;
        }

        .stChatMessage [data-testid="stMarkdownContainer"] {
            font-size: 0.99rem;
            line-height: 1.62;
            color: var(--pia-text);
        }

        [data-testid="chatAvatarIcon-assistant"] {
            background: linear-gradient(135deg, var(--pia-accent), var(--pia-accent-2));
            color: #ffffff;
        }

        [data-testid="chatAvatarIcon-user"] {
            background: #2e323c;
            color: #d5deef;
        }

        [data-testid="stChatMessageContent"] {
            background: transparent !important;
            padding: 0.15rem 0.1rem !important;
        }

        .stMarkdown p code,
        .stChatMessage p code,
        .stMarkdown li code,
        .stChatMessage li code {
            font-family: "IBM Plex Mono", monospace;
            border: 1px solid rgba(122, 151, 207, 0.24);
            border-radius: 6px;
            background: var(--pia-code-bg);
            color: #b9d4ff;
            padding: 0.1rem 0.26rem;
            font-size: 0.9em;
        }

        .stMarkdown pre,
        .stChatMessage pre {
            position: relative;
            border-radius: 12px;
            border: 1px solid rgba(122, 151, 207, 0.2);
            background: var(--pia-code-bg);
            padding-top: 2rem;
            overflow-x: auto;
        }

        .stMarkdown pre code,
        .stChatMessage pre code {
            font-family: "IBM Plex Mono", monospace;
            font-size: 0.86rem;
            line-height: 1.55;
            background: transparent;
            border: none;
            color: #d0e2ff;
        }

        .pia-copy-btn {
            position: absolute;
            top: 0.46rem;
            right: 0.52rem;
            border: 1px solid rgba(122, 151, 207, 0.24);
            background: #1f2430;
            color: #c7dafb;
            border-radius: 8px;
            padding: 0.18rem 0.52rem;
            font-size: 0.72rem;
            font-weight: 700;
            cursor: pointer;
        }

        .pia-copy-btn:hover {
            background: #262b37;
            border-color: rgba(122, 151, 207, 0.34);
        }

        .stTextInput label,
        .stSelectbox label,
        .stChatInput label,
        .stFileUploader label,
        .stAudioInput label {
            color: var(--pia-muted) !important;
        }

        [data-testid="stButton"] > button {
            border-radius: 14px;
            border: 1px solid var(--pia-border);
            background: #1f232d;
            color: var(--pia-text);
            font-weight: 700;
            min-height: 2.9rem;
            box-shadow: none;
        }

        [data-testid="stButton"] > button[kind="primary"] {
            background: linear-gradient(145deg, var(--pia-accent), #2975e6);
            color: #f8fbff;
            border-color: rgba(110, 168, 255, 0.42);
        }

        [data-testid="stSidebar"] [data-testid="stButton"] > button[kind="primary"] {
            min-height: 3rem;
            font-size: 0.95rem;
        }

        [data-testid="stButton"] > button:hover,
        [data-testid="stButton"] > button:focus {
            border-color: rgba(138, 183, 255, 0.5);
            color: #f2f6ff;
        }

        [data-testid="stButton"] > button:active {
            transform: translateY(1px);
            filter: brightness(1.04);
        }

        [data-testid="stTextInput"] input,
        [data-testid="stTextArea"] textarea,
        [data-baseweb="select"] > div,
        [data-testid="stChatInput"] textarea {
            border-radius: 14px !important;
            border: 1px solid var(--pia-border) !important;
            background: #171b23 !important;
            color: var(--pia-text) !important;
        }

        [data-testid="stChatInput"] {
            border: 1px solid var(--pia-border);
            border-radius: 24px;
            background: rgba(22, 25, 32, 0.96);
            box-shadow: 0 14px 26px rgba(0, 0, 0, 0.24);
            padding: 0.26rem 0.58rem 0.34rem 0.58rem;
        }

        [data-testid="stFileUploader"] section {
            border-radius: 14px;
            border: 1px dashed rgba(122, 151, 207, 0.28);
            background: #171b23;
        }

        [data-testid="stExpander"] {
            border: 1px solid var(--pia-border);
            border-radius: 14px;
            background: rgba(25, 28, 34, 0.9);
        }

        .pia-composer-shell {
            border: 1px solid var(--pia-border);
            background: linear-gradient(180deg, rgba(24, 27, 34, 0.96), rgba(20, 23, 30, 0.98));
            box-shadow: 0 14px 28px rgba(0, 0, 0, 0.24);
            border-radius: 26px;
            padding: 0.56rem 0.72rem 0.24rem 0.72rem;
            margin: 0.35rem 0 0.82rem 0;
        }

        .pia-composer-label {
            font-size: 0.76rem;
            letter-spacing: 0.02em;
            font-weight: 600;
            color: #9fb5d8;
            margin-bottom: 0.26rem;
        }

        [data-testid="stSidebar"] [data-testid="stButton"] > button {
            justify-content: flex-start;
        }

        @media (max-width: 900px) {
            [data-testid="stSidebar"] {
                min-width: 100% !important;
                max-width: 100% !important;
            }
            .block-container { 
                padding-top: 0.5rem !important; 
                padding-bottom: 5rem !important;
                max-width: 100% !important;
            }
            .pia-title { font-size: 1.55rem; }
            .pia-hero { padding: 0.8rem; }
            .pia-topbar-shell { 
                padding: 0.6rem;
                margin-bottom: 0.4rem;
            }
            .pia-brand-lockup { gap: 0.5rem; min-height: 2.2rem; }
            .pia-brand-mark { width: 1.8rem; height: 1.8rem; font-size: 0.8rem; }
            .pia-brand-name { font-size: 0.95rem; }
            
            /* Better spacing for mobile chat */
            .stChatMessage {
                padding: 0.4rem 0.2rem !important;
            }
            
            /* Responsive Input */
            [data-testid="stChatInput"] {
                bottom: 1rem !important;
                left: 0.5rem !important;
                right: 0.5rem !important;
                width: auto !important;
            }
        }

        @keyframes pia-fade-up {
            from { opacity: 0; transform: translateY(6px); }
            to { opacity: 1; transform: translateY(0); }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
