"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://192.168.1.92:8000";

export default function Register() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const router = useRouter();

  const handleRegister = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setIsLoading(true);

    try {
      const res = await fetch(`${API_URL}/auth/register`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password }),
      });

      if (!res.ok) {
        const data = await res.json();
        throw new Error(data.detail || "Registration failed");
      }

      const data = await res.json();
      localStorage.setItem("token", data.access_token);
      router.push("/");
    } catch (err: unknown) {
      if (err instanceof Error) {
        setError(err.message);
      } else {
        setError("An unexpected registration error occurred.");
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
            Registration
          </span>
        </div>

        <h1 className="text-xl font-display font-semibold text-ink tracking-tight mb-1">
          Create Account
        </h1>
        <p className="text-xs text-muted mb-6">
          Provision an identity for document ingestion and conversational analytics.
        </p>

        {error && (
          <div className="mb-5 p-3 bg-ruby-subtle border border-ruby/30 rounded-base text-ruby text-xs font-mono">
            [ERR] {error}
          </div>
        )}

        <form onSubmit={handleRegister} className="space-y-4">
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
            <label className="block font-mono text-[11px] uppercase tracking-wider text-muted mb-1.5">
              Password
            </label>
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
            {isLoading ? "Provisioning..." : "Provision Account →"}
          </button>
        </form>

        <div className="mt-6 pt-4 border-t border-rule text-center">
          <p className="text-xs text-muted">
            Already provisioned?{" "}
            <Link href="/login" className="text-accent hover:underline font-medium">
              Sign in to console
            </Link>
          </p>
        </div>
      </div>
    </div>
  );
}

