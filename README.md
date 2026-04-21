# 🧠 PIA (Personal Intelligence Agent)

### "Your Autonomous AI Copilot for Document Intelligence & Workspace Mastery"

PIA is a premium, feature-rich AI agent built with **Streamlit** and powered by **Meta Llama 3.3 (70B)** and **Groq**. It combines long-term cloud memory (RAG), multimodal analysis (Images, Video, Audio), and deep integration with **Google Workspace (Gmail & Calendar)** to provide a truly autonomous personal assistant experience.

---

## 🎨 Professional "Obsidian Glass" UI
PIA features a bespoke dark-mode interface designed with modern aesthetics in mind:
- **Glassmorphism Design**: Frosted glass effects, smooth gradients, and elegant typography (Manrope & Space Grotesk).
- **Responsive Interactions**: Fade-up animations, custom sidebar navigation, and interactive data visualizations.
- **Unified Command Center**: Seamlessly switch between chat, file analysis, and workspace management.

---

## 🚀 Key Features

### 📂 1. Intelligent RAG & Document Memory
*   **Full-Text Retrieval**: Persistent vector memory using **Supabase (pgvector)**.
*   **Multimodal Ingestion**: Supports PDF, DOCX, TXT, CSV, XLSX, and Images.
*   **Smart Chunking**: Advanced text processing for high-context retrieval.

### 🌍 2. Web Intelligence & Search
*   **Tavily Integration**: Real-time web searching for current events and market data.
*   **Automatic Context Injection**: Detects when a user query requires real-time data and fetches it autonomously.

### 📧 3. Google Workspace Integration
*   **Gmail Automation**: Search, read, summarize, draft, and send emails directly from the chat.
*   **Calendar Mastery**: List upcoming meetings and schedule new events using natural language.
*   **Forced Tool Calling**: High-reliability intent detection ensures your workspace actions are executed accurately.

### 👁️ 4. Multimodal Vision & Audio
*   **Vision Analysis**: Powered by Groq's high-speed vision models. Analyze screenshots, photos, and even video frames.
*   **Voice-to-Task**: Transcribe voice messages using **Groq Whisper** for hands-free assistant interaction.

### 📊 5. Data Science & Visuals
*   **Auto-Visualization**: Upload tabular data (CSV/XLSX) and PIA will automatically generate Plotly charts (Scatter, Line, Histogram, Bar) based on the data's shape.

---

## 🏗️ System Architecture

```mermaid
graph TD
    %% Define Styles
    classDef user fill:#6366f1,stroke:#fff,stroke-width:2px,color:#fff;
    classDef engine fill:#8b5cf6,stroke:#fff,stroke-width:2px,color:#fff;
    classDef tool fill:#10b981,stroke:#fff,stroke-width:2px,color:#fff;
    classDef storage fill:#f59e0b,stroke:#fff,stroke-width:2px,color:#fff;

    %% Nodes
    U["👤 User Interaction<br/>(Streamlit UI)"] ::: user
    
    subgraph Intelligence ["🧠 PIA Orchestrator (Llama 3.3 70B)"]
        TC["🛠️ Intent Detection & Tool Router"]
        RAG["📚 Retrieval Augmented Generation"]
        VIZ["📈 Plotly Data Visualization"]
    end
    Intelligence ::: engine

    subgraph Multimodal ["👁️ Vision & 🎙️ Audio"]
        G_VIS["Groq Vision (Llava)"]
        G_WSP["Groq Whisper (Speech-to-Text)"]
    end
    Multimodal ::: engine

    subgraph Workspace ["📧 Connectors"]
        GM["Gmail API"]
        GC["Google Calendar"]
        TV["Tavily Search"]
    end
    Workspace ::: tool

    subgraph Data ["💾 Persistent Memory"]
        SUPA["Supabase (pgvector)"]
        CACHE["Local Cache"]
    end
    Data ::: storage

    %% Connections
    U -->|"Query / File / Voice"| Intelligence
    Intelligence <-->|"Retrieve Context"| Data
    Intelligence -->|"Process Media"| Multimodal
    TC -->|"Execute Action"| Workspace
    Intelligence -->|"Render Charts"| U
    TC -->|"Update Memory"| SUPA
```

---

## 🛠️ Quick Setup

### 1. Prerequisites
*   Python 3.10+
*   Supabase Account (Database + pgvector)
*   API Keys: Groq, LlamaAPI, Tavily, Google Cloud (Optional)

### 2. Environment Setup
```bash
git clone https://github.com/Subhan3716/Personal-Intelligence-Agent-PIA.git
cd Personal-Intelligence-Agent-PIA

python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

pip install -r requirements.txt
```

### 3. Configuration
Create a `.env` file in the root directory (see [setup_guide.md](setup_guide.md) for details).

### 4. Database Initialization
Run the following SQL scripts in your Supabase SQL Editor:
1.  `supabase_schema.sql`
2.  `oauth_handshakes.sql`
3.  `user_tokens_migration.sql`

### 5. Launch
```bash
streamlit run app.py
```

---

## 🛡️ Security & Privacy
PIA is designed with security in mind:
*   **Local Secrets**: API keys are managed via `.env` and excluded from Git.
*   **OAuth 2.0 PKCE**: Secure Google authorization without exposing Client Secrets.
*   **Data Isolation**: User data and chat history are isolated by UID in Supabase.

---

## 📦 Technology Stack
*   **Frontend**: Streamlit (Premium Custom CSS)
*   **LLM Engine**: Meta Llama 3.3 70B (via Llama API)
*   **Inference**: Groq (Vision & Whisper)
*   **Vector DB**: Supabase PostgreSQL + pgvector
*   **Web Intel**: Tavily Search API
*   **Integrations**: Gmail API, Google Calendar API

---

**Developed with ❤️ for Advanced AI Productivity.**
