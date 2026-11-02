"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { getApiUrl } from "@/lib/api";
import CyberSpinner from "@/components/CyberSpinner";

export default function Login() {
  const API_URL = getApiUrl();
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

  const handleOAuthLogin = async (provider: string) => {
    setError("");
    setIsLoading(true);
    try {
      const redirectUri = `${window.location.origin}/auth/callback?provider=${provider}`;
      const res = await fetch(`${API_URL}/auth/oauth/${provider}/authorize?redirect_uri=${encodeURIComponent(redirectUri)}`);
      if (!res.ok) {
        const data = await res.json();
        throw new Error(data.detail || `Failed to initialize ${provider} authorization`);
      }
      const data = await res.json();
      if (data.authorization_url) {
        window.location.href = data.authorization_url;
      } else {
        throw new Error("No authorization URL returned from identity provider.");
      }
    } catch (err: unknown) {
      if (err instanceof Error) {
        setError(err.message);
      } else {
        setError("Failed to connect to identity provider.");
      }
      setIsLoading(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-paper text-ink p-4 font-body">
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
            Auth v2.0
          </span>
        </div>

        <h1 className="text-xl font-display font-semibold text-ink tracking-tight mb-1">
          Sign In
        </h1>
        <p className="text-xs text-muted mb-5">
          Authenticate with enterprise SSO or credentials to access scoped knowledge.
        </p>

        {error && (
          <div className="mb-4 p-3 bg-ruby-subtle border border-ruby/30 rounded-base text-ruby text-xs font-mono">
            [ERR] {error}
          </div>
        )}

        {/* 1-Click Social / OAuth SSO Options */}
        <div className="space-y-2 mb-4">
          <button
            type="button"
            onClick={() => handleOAuthLogin("google")}
            disabled={isLoading}
            className="w-full flex items-center justify-center gap-3 py-2 px-3 rounded-base bg-paper hover:bg-paper-3 border border-rule text-xs font-medium text-ink transition-all hover:border-rule-strong cursor-pointer disabled:opacity-50"
          >
            <svg className="w-4 h-4 shrink-0" viewBox="0 0 24 24">
              <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z" />
              <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" />
              <path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.06H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.94l2.85-2.22.81-.63z" />
              <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.06l3.66 2.84c.87-2.6 3.3-4.52 6.16-4.52z" />
            </svg>
            <span>Continue with Google</span>
          </button>

          <div className="grid grid-cols-2 gap-2">
            <button
              type="button"
              onClick={() => handleOAuthLogin("microsoft")}
              disabled={isLoading}
              className="flex items-center justify-center gap-2 py-2 px-2.5 rounded-base bg-paper hover:bg-paper-3 border border-rule text-xs font-medium text-ink transition-all hover:border-rule-strong cursor-pointer disabled:opacity-50"
            >
              <svg className="w-3.5 h-3.5 shrink-0" viewBox="0 0 23 23">
                <path fill="#f35325" d="M1 1h10v10H1z" />
                <path fill="#81bc06" d="M12 1h10v10H12z" />
                <path fill="#05a6f0" d="M1 12h10v10H1z" />
                <path fill="#ffba08" d="M12 12h10v10H12z" />
              </svg>
              <span>Microsoft 365</span>
            </button>

            <button
              type="button"
              onClick={() => handleOAuthLogin("github")}
              disabled={isLoading}
              className="flex items-center justify-center gap-2 py-2 px-2.5 rounded-base bg-paper hover:bg-paper-3 border border-rule text-xs font-medium text-ink transition-all hover:border-rule-strong cursor-pointer disabled:opacity-50"
            >
              <svg className="w-3.5 h-3.5 shrink-0 fill-current" viewBox="0 0 24 24">
                <path fillRule="evenodd" clipRule="evenodd" d="M12 2C6.477 2 2 6.484 2 12.017c0 4.425 2.865 8.18 6.839 9.504.5.092.682-.217.682-.483 0-.237-.008-.868-.013-1.703-2.782.605-3.369-1.343-3.369-1.343-.454-1.158-1.11-1.466-1.11-1.466-.908-.62.069-.608.069-.608 1.003.07 1.53 1.032 1.53 1.032.892 1.53 2.341 1.088 2.91.832.092-.647.35-1.088.636-1.338-2.22-.253-4.555-1.113-4.555-4.951 0-1.093.39-1.988 1.029-2.688-.103-.253-.446-1.272.098-2.65 0 0 .84-.27 2.75 1.026A9.564 9.564 0 0112 6.844c.85.004 1.705.115 2.504.337 1.909-1.296 2.747-1.027 2.747-1.027.546 1.379.202 2.398.1 2.651.64.7 1.028 1.595 1.028 2.688 0 3.848-2.339 4.695-4.566 4.943.359.309.678.92.678 1.855 0 1.338-.012 2.419-.012 2.747 0 .268.18.58.688.482A10.019 10.019 0 0022 12.017C22 6.484 17.522 2 12 2z" />
              </svg>
              <span>GitHub</span>
            </button>
          </div>
        </div>

        {/* Cyberpunk Divider */}
        <div className="relative my-4">
          <div className="absolute inset-0 flex items-center">
            <div className="w-full border-t border-rule" />
          </div>
          <div className="relative flex justify-center text-[10px] uppercase font-mono tracking-wider">
            <span className="bg-paper-2 px-2 text-muted">Or credentials</span>
          </div>
        </div>

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
            className="w-full py-2.5 px-4 rounded-base bg-accent hover:bg-accent-hover active:scale-[0.99] text-accent-ink text-xs font-mono uppercase tracking-wider font-semibold transition-all disabled:opacity-50 disabled:cursor-not-allowed mt-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-focus cursor-pointer flex items-center justify-center gap-2"
          >
            {isLoading ? (
              <CyberSpinner size="sm" variant="ink" label="Authenticating Identity..." />
            ) : (
              "Authorize Access →"
            )}
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

