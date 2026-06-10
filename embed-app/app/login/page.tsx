"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

export default function LoginPage() {
  const [email, setEmail] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const router = useRouter();

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    const res = await fetch("/api/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      setError(data.error || "Sign in failed.");
      setBusy(false);
      return;
    }
    router.push("/");
    router.refresh();
  }

  return (
    <main
      style={{
        height: "100vh",
        display: "grid",
        placeItems: "center",
        background: "#f9fafb",
      }}
    >
      <form
        onSubmit={onSubmit}
        style={{
          width: 340,
          background: "#fff",
          border: "1px solid #e5e7eb",
          borderRadius: 12,
          padding: 28,
          boxShadow: "0 1px 3px rgba(0,0,0,0.06)",
        }}
      >
        <h1 style={{ fontSize: 18, margin: "0 0 4px" }}>Sign in</h1>
        <p style={{ fontSize: 13, color: "#6b7280", margin: "0 0 20px" }}>
          Enter your work email — we&apos;ll load your company&apos;s dashboard.
        </p>

        <label style={{ fontSize: 12, fontWeight: 600, color: "#374151" }}>
          Email
        </label>
        <input
          type="email"
          required
          autoFocus
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          placeholder="you@abc.com"
          style={{
            display: "block",
            width: "100%",
            boxSizing: "border-box",
            marginTop: 6,
            marginBottom: 16,
            padding: "9px 10px",
            border: "1px solid #d1d5db",
            borderRadius: 8,
            fontSize: 14,
          }}
        />

        {error && (
          <div style={{ color: "#b91c1c", fontSize: 12, marginBottom: 12 }}>
            {error}
          </div>
        )}

        <button
          type="submit"
          disabled={busy}
          style={{
            width: "100%",
            padding: "9px 10px",
            border: "none",
            borderRadius: 8,
            background: busy ? "#9ca3af" : "#111827",
            color: "#fff",
            fontSize: 14,
            fontWeight: 600,
            cursor: busy ? "default" : "pointer",
          }}
        >
          {busy ? "Signing in…" : "Continue"}
        </button>

        <p style={{ fontSize: 11, color: "#9ca3af", marginTop: 16 }}>
          Demo domains: abc.com · def.com · ghi.com · jkl.com
        </p>
      </form>
    </main>
  );
}
