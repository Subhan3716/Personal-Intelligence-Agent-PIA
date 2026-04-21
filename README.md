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
    %% Node Definitions
    UI["👤 User Interaction (Streamlit UI)"]
    
    subgraph Brain ["🧠 PIA Orchestrator"]
        L70B["Meta Llama 3.3 70B"]
        Router["🛠️ Tool & Intent Router"]
        RAG["📚 RAG Memory Engine"]
    end

    subgraph Senses ["👁️ Vision & 🎙️ Audio"]
        Vision["Groq Vision (Llava)"]
        Whisper["Groq Whisper (STT)"]
    end

    subgraph Workspace ["📧 Workspace & Search"]
        Gmail["Gmail API"]
        Calendar["Google Calendar"]
        Search["Tavily Web Search"]
    end

    subgraph Storage ["💾 Persistent Memory"]
        Supa["Supabase pgvector"]
    end

    %% Data Flow
    UI --> L70B
    L70B <--> Router
    L70B <--> RAG
    RAG <--> Supa
    L70B --> Vision
    UI --> Whisper --> L70B
    Router --> Gmail
    Router --> Calendar
    Router --> Search
    L70B --> UI

    %% Styling
    classDef userCls fill:#6366f1,stroke:#fff,stroke-width:2px,color:#fff;
    classDef brainCls fill:#8b5cf6,stroke:#fff,stroke-width:2px,color:#fff;
    classDef toolCls fill:#10b981,stroke:#fff,stroke-width:2px,color:#fff;
    classDef storeCls fill:#f59e0b,stroke:#fff,stroke-width:2px,color:#fff;

    class UI userCls;
    class Brain,L70B,Router,RAG,Senses,Vision,Whisper brainCls;
    class Workspace,Gmail,Calendar,Search toolCls;
    class Storage,Supa storeCls;
```

---

## 🔍 How It Works: A Deep Dive

### 1. The Entry Point: Premium Streamlit Interface
The user interacts with an **Obsidian Glass** UI. When you type a message, upload a document, or send a voice note, PIA catches the input and prepares it for processing.

### 2. The Brain: Llama 3.3 70B Orchestration
At the center is **Meta Llama 3.3 (70B)** running on **LlamaAPI**. This model doesn't just "chat"—it acts as a reasoner:
- **Intent Detection**: It analyzes your query to see if you need an email sent, a meeting scheduled, or a web search performed.
- **Context Assembly**: It pulls relevant snippets from your past documents (RAG) and injects them into the current conversation.

### 3. The Senses: Multimodal Processing
If you upload an image or video, PIA calls **Groq Vision**. If you send a voice note, it uses **Groq Whisper** to transcribe it instantly. This allows the agent to "see" and "hear" your workspace.

### 4. The Action: Tool Execution
When the Brain decides an action is needed (e.g., "Summarize my latest email"), the **Tool Router** engages the **Google Workspace APIs**. It handles OAuth2 authentication securely and executes the requested task, returning the result directly to your chat.

### 5. The Memory: Long-Term Context
Every document you upload is "chunked" and transformed into mathematical vectors. These are stored in **Supabase pgvector**. When you ask a question later, PIA performs a **semantic search** to find the exact information you need, across thousands of pages.

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
