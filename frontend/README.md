# Knowledge Bot Frontend Web Application

The Next.js 15 enterprise web client for the Enterprise Knowledge Bot, built with React 19, Tailwind CSS v4, and the **Precision Dossier** design system — an anti-AI-slop design architecture combining high optical density, ruler-drawn hairlines, archival provenance citations, and live inference telemetry.

---

## 🌟 Key Features

- **Precision Dossier Design Architecture:**
  - **Zero AI-Slop Tells:** Purged all generic radial blur orbs, 3-bouncing-dot animations, and unstyled card containers.
  - **Tri-Fold Typography Discipline:** **Space Grotesk** (confident Roman display headings), **Inter** (high-legibility UI & body), and **JetBrains Mono** (monospaced citations, SQL code, and system telemetry).
  - **Calibrated OKLCH Palette:** Engineered dark graphite ground (`oklch(15.5% 0.008 255)`), 1px structural hairlines, Electric Cobalt interactive signals, Archival Brass citation chips, and Emerald SQL chips.
- **Real-Time Markdown Streaming:** Server-Sent Events (SSE) streaming with live rendering of Markdown formatting, structured tables, and Prism code syntax highlighting (`react-syntax-highlighter`).
- **Interactive Mention Menu (`@file` and `!table`):** Autocomplete dropdown targeting questions or summarization prompts to specific uploaded files or tabular datasets with arrow key navigation.
- **Live Inference Telemetry:** Real-time pulse telemetry readout displaying model and reranker status during generation instead of generic loader dots.
- **Dual Knowledge Repository Drawer:** Tabbed interface categorizing **Personal Documents** (sandboxed to current user) and **Global Documents** (verified enterprise knowledge base) with direct prompt targeting.
- **Session Management Drawer:** Multi-conversation support. Users can start new chats, switch between existing chat histories, rename chat titles inline, or delete past sessions.
- **Role Elevation Requests:** Standard users can submit elevation requests directly from the UI for `editor` or `admin` status, with pending status badges.
- **Admin Dashboard (`/admin`):**
  - High-density telemetry cards (Total Users, Active Sessions, Total Vector Chunks).
  - Pending Role Request Management (approve or reject elevation requests with real-time feedback).
  - User Directory table showing usernames, assigned roles, and join timestamps.
  - Global Document Manager (upload and delete organization-wide files).

---

## 🛠️ Tech Stack

- **Framework:** Next.js 15 (App Router)
- **UI Library:** React 19
- **Styling:** Tailwind CSS v4, PostCSS, OKLCH Tokens
- **Typography:** `Space_Grotesk`, `Inter`, `JetBrains_Mono` (`next/font/google`)
- **Markdown & Highlighting:** `react-markdown`, `remark-gfm`, `react-syntax-highlighter`
- **Notifications:** `react-hot-toast`


---

## 📁 Directory Structure

```text
frontend/
├── app/
│   ├── admin/
│   │   └── page.tsx        # Admin dashboard: metrics, role approvals, global docs
│   ├── login/
│   │   └── page.tsx        # User login form
│   ├── register/
│   │   └── page.tsx        # User registration form
│   ├── globals.css         # Dark theme styling, glassmorphism, animations
│   ├── layout.tsx          # Root layout and metadata
│   └── page.tsx            # Main chat interface, document drawer, session sidebar
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
