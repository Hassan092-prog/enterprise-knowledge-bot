# Knowledge Bot Frontend

This is the Next.js web application for the Enterprise Knowledge Bot.

## Overview
It provides a modern, responsive, dark-mode user interface for:
- User registration and authentication
- Document uploading and management
- Markdown streaming chat interface with precise citations
- Admin dashboard for managing global documents

## Tech Stack
- **Framework:** Next.js 15 (App Router)
- **UI & Styling:** React 19, TailwindCSS
- **Streaming:** Server-sent events for real-time markdown rendering

## Development

First, run the development server:

```bash
npm run dev
# or
yarn dev
# or
pnpm dev
# or
bun dev
```

Open [http://localhost:3000](http://localhost:3000) with your browser to see the result.

Make sure the FastAPI backend is running (typically on port 8000) so the frontend can successfully communicate with the API.
