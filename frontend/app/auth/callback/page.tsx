"use client";

import { useEffect, useState, Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { getApiUrl } from "@/lib/api";
import CyberSpinner from "@/components/CyberSpinner";

function OAuthCallbackContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const API_URL = getApiUrl();

  const [statusText, setStatusText] = useState("Verifying Identity with Provider...");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const code = searchParams.get("code");
    const provider = searchParams.get("provider") || "google";
    const errorParam = searchParams.get("error") || searchParams.get("error_description");

    if (errorParam) {
      setError(`Identity provider returned an authorization error: ${errorParam}`);
      return;
    }

    // Direct JWT token returned from Enterprise SSO (SAML ACS or OIDC callback)
    const directToken = searchParams.get("token");
    if (directToken) {
      setStatusText("Enterprise SSO authenticated! Launching workspace...");
      localStorage.setItem("token", directToken);
      const role = searchParams.get("role");
      const tenantId = searchParams.get("tenant_id");
      const tenantName = searchParams.get("tenant_name");
      const username = searchParams.get("username");
      const email = searchParams.get("email");
      const isPlatformAdmin = searchParams.get("is_platform_admin");

      if (role) localStorage.setItem("role", role);
      if (tenantId) localStorage.setItem("tenant_id", tenantId);
      if (tenantName) localStorage.setItem("tenant_name", tenantName);
      if (username) localStorage.setItem("username", username);
      if (email) localStorage.setItem("email", email);
      if (isPlatformAdmin === "true") {
        localStorage.setItem("is_platform_admin", "true");
      } else {
        localStorage.removeItem("is_platform_admin");
      }

      setTimeout(() => {
        router.push("/");
      }, 500);
      return;
    }

    if (!code) {
      setError("No authorization code or token was found in the provider callback.");
      return;
    }

    const processCallback = async () => {
      try {
        setStatusText(`Exchanging token with ${provider.toUpperCase()}...`);
        const redirectUri = `${window.location.origin}/auth/callback?provider=${provider}`;

        const res = await fetch(`${API_URL}/auth/oauth/${provider}/callback`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            code,
            redirect_uri: redirectUri,
          }),
        });

        if (!res.ok) {
          const errData = await res.json().catch(() => ({}));
          throw new Error(errData.detail || "Authentication verification failed");
        }

        const data = await res.json();
        setStatusText("Session established. Launching Enterprise Knowledge Workspace...");

        localStorage.setItem("token", data.access_token);
        if (data.role) localStorage.setItem("role", data.role);
        if (data.tenant_name) localStorage.setItem("tenant_name", data.tenant_name);
        if (data.tenant_id) localStorage.setItem("tenant_id", String(data.tenant_id));
        if (data.username) localStorage.setItem("username", data.username);
        if (data.avatar_url) localStorage.setItem("avatar_url", data.avatar_url);
        if (data.email) localStorage.setItem("email", data.email);

        if (data.is_platform_admin) {
          localStorage.setItem("is_platform_admin", "true");
        } else {
          localStorage.removeItem("is_platform_admin");
        }

        setTimeout(() => {
          router.push("/");
        }, 600);
      } catch (err: unknown) {
        if (err instanceof Error) {
          setError(err.message);
        } else {
          setError("Failed to verify OAuth identity session.");
        }
      }
    };

    processCallback();
  }, [searchParams, router, API_URL]);

  return (
    <div className="flex min-h-screen items-center justify-center bg-paper text-ink p-4 font-body">
      <div className="w-full max-w-sm p-6 sm:p-8 bg-paper-2 rounded-card border border-rule shadow-sm text-center">
        {/* Terminal Header Landmark */}
        <div className="flex items-center justify-between pb-4 mb-6 border-b border-rule">
          <div className="flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-accent animate-pulse" />
            <span className="font-mono text-xs uppercase tracking-wider text-muted font-medium">
              Enterprise Knowledge Engine
            </span>
          </div>
          <span className="font-mono text-[10px] uppercase tracking-wider text-muted px-2 py-0.5 rounded border border-rule bg-paper">
            OAuth Gateway
          </span>
        </div>

        {error ? (
          <div className="space-y-4">
            <div className="p-3.5 bg-ruby-subtle border border-ruby/30 rounded-base text-ruby text-xs font-mono text-left">
              <span className="font-bold">[OAUTH_VERIFY_ERROR]</span>
              <p className="mt-1">{error}</p>
            </div>
            <p className="text-xs text-muted">
              The corporate identity verification could not be completed. You can sign in using account credentials.
            </p>
            <Link
              href="/login"
              className="inline-block w-full py-2.5 px-4 rounded-base bg-accent hover:bg-accent-hover text-accent-ink text-xs font-mono uppercase tracking-wider font-semibold transition-all cursor-pointer"
            >
              ← Return to Sign In
            </Link>
          </div>
        ) : (
          <div className="py-6 space-y-4 flex flex-col items-center">
            <CyberSpinner size="lg" variant="accent" label={statusText} />
            <p className="text-xs text-muted font-mono tracking-wide mt-2">
              Validating cryptographic claims & domain routing...
            </p>
          </div>
        )}
      </div>
    </div>
  );
}

export default function OAuthCallbackPage() {
  return (
    <Suspense
      fallback={
        <div className="flex min-h-screen items-center justify-center bg-paper text-ink font-body">
          <CyberSpinner size="lg" variant="accent" label="Initializing Identity Handshake..." />
        </div>
      }
    >
      <OAuthCallbackContent />
    </Suspense>
  );
}
