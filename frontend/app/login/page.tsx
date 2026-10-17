"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://192.168.1.92:8000";

export default function Login() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const router = useRouter();

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setIsLoading(true);

    try {
      const res = await fetch(`${API_URL}/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password }),
      });

      if (!res.ok) {
        const data = await res.json();
        throw new Error(data.detail || "Login failed");
      }

      const data = await res.json();
      localStorage.setItem("token", data.access_token);
      if (data.role) localStorage.setItem("role", data.role);
      if (data.tenant_name) localStorage.setItem("tenant_name", data.tenant_name);
      if (data.tenant_id) localStorage.setItem("tenant_id", String(data.tenant_id));
      if (data.is_platform_admin) {
        localStorage.setItem("is_platform_admin", "true");
      } else {
        localStorage.removeItem("is_platform_admin");
      }
      router.push("/");
    } catch (err: unknown) {
      if (err instanceof TypeError && err.message.includes('Failed to fetch')) {
        setError("Cannot connect to backend server. Verify network connectivity.");
      } else if (err instanceof Error) {
        setError(err.message);
      } else {
        setError("An unexpected authentication error occurred.");
      }
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-paper text-ink p-4">
      <div className="w-full max-w-sm p-6 sm:p-8 bg-paper-2 rounded-card border border-rule shadow-sm">
        {/* Terminal Header Landmark */}
        <div className="flex items-center justify-between pb-4 mb-6 border-b border-rule">
          <div className="flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-accent animate-pulse" />
            <span className="font-mono text-xs uppercase tracking-wider text-muted font-medium">
              Knowledge Engine
            </span>
          </div>
          <span className="font-mono text-[10px] uppercase tracking-wider text-muted px-2 py-0.5 rounded border border-rule bg-paper">
            Auth v1.2
          </span>
        </div>

        <h1 className="text-xl font-display font-semibold text-ink tracking-tight mb-1">
          Sign In
        </h1>
        <p className="text-xs text-muted mb-6">
          Authenticate to access global vector indices and tabular data.
        </p>

        {error && (
          <div className="mb-5 p-3 bg-ruby-subtle border border-ruby/30 rounded-base text-ruby text-xs font-mono">
            [ERR] {error}
          </div>
        )}

        <form onSubmit={handleLogin} className="space-y-4">
          <div>
            <label className="block font-mono text-[11px] uppercase tracking-wider text-muted mb-1.5">
              Username
            </label>
            <input
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              className="w-full bg-paper border border-rule focus:border-accent focus:outline-none rounded-base py-2 px-3 text-sm text-ink placeholder:text-muted transition-colors font-body"
              placeholder="e.g. analyst"
              required
            />
          </div>
          <div>
            <div className="flex justify-between items-center mb-1.5">
              <label className="block font-mono text-[11px] uppercase tracking-wider text-muted">
                Password
              </label>
            </div>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full bg-paper border border-rule focus:border-accent focus:outline-none rounded-base py-2 px-3 text-sm text-ink placeholder:text-muted transition-colors font-body"
              placeholder="••••••••"
              required
            />
          </div>
          <button
            type="submit"
            disabled={isLoading}
            className="w-full py-2.5 px-4 rounded-base bg-accent hover:bg-accent-hover active:scale-[0.99] text-accent-ink text-xs font-mono uppercase tracking-wider font-semibold transition-all disabled:opacity-50 disabled:cursor-not-allowed mt-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-focus cursor-pointer"
          >
            {isLoading ? "Authenticating..." : "Authorize Access →"}
          </button>
        </form>

        <div className="mt-6 pt-4 border-t border-rule text-center">
          <p className="text-xs text-muted">
            Need an account?{" "}
            <Link href="/register" className="text-accent hover:underline font-medium">
              Create an identity
            </Link>
          </p>
        </div>
      </div>
    </div>
  );
}

