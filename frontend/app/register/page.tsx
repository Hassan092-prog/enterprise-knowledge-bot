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
        setError("An unknown error occurred");
      }
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="flex h-screen items-center justify-center bg-paper text-ink font-sans relative overflow-hidden">
      {/* Atmospheric Radial Blooms */}
      <div className="absolute top-[-200px] right-[-100px] w-[600px] h-[600px] rounded-full bg-accent opacity-[0.07] blur-[100px] pointer-events-none" />
      <div className="absolute bottom-[100px] left-[-100px] w-[500px] h-[500px] rounded-full bg-accent opacity-[0.05] blur-[80px] pointer-events-none" />
      
      <div className="w-full max-w-md p-8 bg-paper-2 rounded-base shadow-[0_8px_30px_rgb(0,0,0,0.12)] border border-border relative z-10">
        <h1 className="text-3xl font-display font-semibold text-ink mb-2 text-center tracking-tight">
          Enterprise RAG
        </h1>
        <p className="text-muted text-center mb-8">Create a new account</p>

        {error && (
          <div className="mb-4 p-3 bg-red-900/20 border border-red-500/30 rounded-base text-red-400 text-sm text-center">
            {error}
          </div>
        )}

        <form onSubmit={handleRegister} className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-muted mb-1">Username</label>
            <input
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              className="w-full bg-paper border border-border rounded-base py-3 px-4 text-ink focus:outline-none focus:border-accent transition-colors"
              required
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-muted mb-1">Password</label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full bg-paper border border-border rounded-base py-3 px-4 text-ink focus:outline-none focus:border-accent transition-colors"
              required
            />
          </div>
          <button
            type="submit"
            disabled={isLoading}
            className="w-full py-3 px-4 rounded-base bg-accent hover:bg-accent/90 text-accent-ink font-medium transition-colors disabled:opacity-50 mt-4 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-focus shadow-lg shadow-accent/20"
          >
            {isLoading ? "Creating account..." : "Register"}
          </button>
        </form>

        <p className="mt-6 text-center text-sm text-muted">
          Already have an account?{" "}
          <Link href="/login" className="text-accent hover:text-accent/80 transition-colors">
            Sign in
          </Link>
        </p>
      </div>
    </div>
  );
}
