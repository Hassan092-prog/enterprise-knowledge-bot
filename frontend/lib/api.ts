/**
 * Dynamic API Base URL Resolver
 * 
 * Automatically resolves the correct backend API endpoint across environments:
 * 1. HTTPS / Domain access (e.g., https://knowledge.alphalabs.nurexia.co)
 *    -> Routes via Nginx reverse proxy at `${origin}/api` (zero Mixed Content errors)
 * 2. Local LAN direct access (e.g., http://192.168.1.92:3000)
 *    -> Routes directly to backend on port 8000
 * 3. Localhost developer environment (http://localhost:3000)
 *    -> Routes directly to http://localhost:8000
 */
export function getApiUrl(): string {
  if (typeof window !== "undefined") {
    const { protocol, hostname, port, origin } = window.location;

    // Production domain or any HTTPS connection: use Nginx reverse proxy `/api`
    if (protocol === "https:" || hostname.includes("nurexia.co")) {
      return `${origin}/api`;
    }

    // Direct access to Next.js on port 3000 over local LAN/IP
    if (port === "3000") {
      return `http://${hostname}:8000`;
    }

    // Default same-origin `/api` proxy
    return `${origin}/api`;
  }

  // SSR fallback
  return process.env.NEXT_PUBLIC_API_URL || "http://192.168.1.92:8000";
}
