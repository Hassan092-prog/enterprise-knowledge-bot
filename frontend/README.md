# Knowledge Bot Frontend Web Application

The Next.js 15 enterprise web client for the Enterprise Knowledge Bot, built with React 19, Tailwind CSS v4, and the **Precision Dossier** design system — an anti-AI-slop design architecture combining high optical density, ruler-drawn hairlines, archival provenance citations, and live inference telemetry.

---

## 🌟 Key Features

- **Precision Dossier Design Architecture:**
  - **Zero AI-Slop Tells:** Purged all generic radial blur orbs, 3-bouncing-dot animations, and unstyled card containers.
  - **Tri-Fold Typography Discipline:** **Space Grotesk** (confident Roman display headings), **Inter** (high-legibility UI & body), and **JetBrains Mono** (monospaced citations, SQL code, and system telemetry).
  - **Calibrated OKLCH Palette:** Engineered dark graphite ground (`oklch(15.5% 0.008 255)`), 1px structural hairlines, Electric Cobalt interactive signals, Archival Brass citation chips, Emerald SQL chips, and Violet Knowledge Graph badges.
- **Real-Time Markdown Streaming:** Server-Sent Events (SSE) streaming with live rendering of Markdown formatting, structured tables, and Prism code syntax highlighting (`react-syntax-highlighter`).
- **Knowledge Graph Visualizer & Explorer:**
  - Dedicated Knowledge Graph tab in the Admin Console (`/admin`).
  - Real-time graph metrics: total entities, relationship edges, entity types, and density.
  - Entity search with configurable BFS hop depth selector (1-3 hops).
  - Interactive entity node explorer and directed relationship link inspector with source document provenance.
  - One-click "Rebuild Knowledge Graph" trigger.
- **Graph Link Citation Badges:**
  - Distinctive purple badges (`🌐 Graph Link`) rendered alongside standard source document citations in chat responses, representing multi-hop entity connections.
- **Real-Time Ingestion Stepper:**
  - Document uploads display live background progress stepper stages (`Parsing` $\rightarrow$ `Chunking` $\rightarrow$ `Summarizing` $\rightarrow$ `Embedding` $\rightarrow$ `Indexed`) polling `/tasks/{task_id}` every 2s before auto-refreshing.
- **Interactive Mention Autocomplete (`@global` and `!private`):**
  - Autocomplete dropdown targeting questions or summarization prompts to specific global documents (`@file`) or private personal files (`!file`) with keyboard arrow navigation.
- **Organization Multi-Tenancy & Onboarding:**
  - Organization registration with join-code enforcement.
  - SuperAdmin organization management and ownership transfer handshakes.
  - Cross-tenant **Platform Admin Portal** (`/platform-admin`) for platform superusers.
- **Presigned S3 Document Downloads:**
  - Download and view uploaded files via authenticated, time-limited presigned S3 URLs directly from MinIO object storage.
- **Session Management Drawer:**
  - Multi-conversation support. Users can start new chats, switch between existing chat histories, rename chat titles inline, or delete past sessions with full PostgreSQL synchronization.

---

## 🛠️ Tech Stack

- **Framework:** Next.js 15 (App Router, Standalone Output)
- **UI Library:** React 19
- **Styling:** Tailwind CSS v4, PostCSS, OKLCH Tokens
- **Typography:** `Space_Grotesk`, `Inter`, `JetBrains_Mono` (`next/font/google`)
- **Markdown & Highlighting:** `react-markdown`, `remark-gfm`, `react-syntax-highlighter`
- **Icons & Badges:** `lucide-react`
- **Notifications:** `react-hot-toast`

---

## 📁 Directory Structure

```text
frontend/
├── app/
│   ├── admin/
│   │   └── page.tsx        # Admin dashboard: metrics, role approvals, global docs, Knowledge Graph tab
│   ├── auth/
│   │   └── callback/
│   │       └── page.tsx    # OAuth2 / SSO authentication callback handler
│   ├── login/
│   │   └── page.tsx        # User login form
│   ├── platform-admin/
│   │   └── page.tsx        # Cross-tenant platform superadmin dashboard
│   ├── register/
│   │   └── page.tsx        # Organization registration & employee join-code onboarding
│   ├── globals.css         # Dark theme styling, glassmorphism, OKLCH tokens
│   ├── layout.tsx          # Root layout and font configurations
│   └── page.tsx            # Main chat interface, session drawer, document manager, live stepper
├── public/                 # Static assets & icons
├── Dockerfile              # Standalone production container build
├── package.json            # Dependencies and scripts
└── tsconfig.json           # TypeScript configuration
```

---

## ⚙️ Environment Configuration

Create or update `.env.local` inside the `frontend/` directory:

```env
# Backend API Base URL
NEXT_PUBLIC_API_URL=http://localhost:8000
```
*(When deploying across a local network or remote server, set this to the server's LAN IP or domain, e.g. `http://192.168.1.92:8000`)*.

---

## 🚀 Running Locally

1. Install dependencies:
   ```bash
   npm install
   ```

2. Run the development server:
   ```bash
   npm run dev
   ```

3. Open [http://localhost:3000](http://localhost:3000) in your browser.
