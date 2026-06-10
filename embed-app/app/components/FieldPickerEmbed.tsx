"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";

type PickerField = { value: string; label: string };

// Build the raw filter parameter string Omni's FIELD_PICKER expects. This is
// passed verbatim (NOT url-encoded) inside the postMessage payload.
function fieldPickerParam(pickerId: string, selected: string[]): string {
  return `f--${pickerId}=${JSON.stringify({ values: selected })}`;
}

export default function FieldPickerEmbed({
  email,
  customerId,
}: {
  email: string;
  customerId: string;
}) {
  const [embedUrl, setEmbedUrl] = useState<string>("");
  const [embedOrigin, setEmbedOrigin] = useState<string>("");
  const [pickerId, setPickerId] = useState<string>("");
  const [fields, setFields] = useState<PickerField[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [status, setStatus] = useState<string>("Loading…");
  const [error, setError] = useState<string>("");
  const router = useRouter();

  const iframeRef = useRef<HTMLIFrameElement>(null);
  const selectedRef = useRef(selected);
  const pickerIdRef = useRef(pickerId);
  const originRef = useRef(embedOrigin);
  selectedRef.current = selected;
  pickerIdRef.current = pickerId;
  originRef.current = embedOrigin;

  // Send the current field selection into the embedded dashboard.
  const pushSelection = useCallback(() => {
    const iframe = iframeRef.current;
    if (!iframe?.contentWindow || !pickerIdRef.current || !originRef.current) return;
    const param = fieldPickerParam(
      pickerIdRef.current,
      Array.from(selectedRef.current)
    );
    iframe.contentWindow.postMessage(
      {
        source: "omni",
        name: "dashboard:filter-change-by-url-parameter",
        payload: { filterUrlParameter: param },
      },
      originRef.current
    );
  }, []);

  // Load embed URL + field list once (tenant is fixed by the session).
  useEffect(() => {
    let cancelled = false;
    Promise.all([
      fetch("/api/embed").then((r) => r.json()),
      fetch("/api/fields").then((r) => r.json()),
    ])
      .then(([embed, picker]) => {
        if (cancelled) return;
        if (embed.error) throw new Error(embed.error);
        if (picker.error) throw new Error(picker.error);
        setEmbedUrl(embed.url);
        setEmbedOrigin(embed.origin);
        setPickerId(picker.pickerId);
        setFields(picker.fields);
        setSelected(new Set(picker.fields.map((f: PickerField) => f.value)));
        setStatus("Loading dashboard…");
      })
      .catch((e) => {
        if (!cancelled) setError(e.message || String(e));
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // Listen for events coming out of the embedded dashboard.
  useEffect(() => {
    function onMessage(event: MessageEvent) {
      if (event.data?.source !== "omni") return;
      switch (event.data.name) {
        case "dashboard:loaded":
          setStatus("Ready");
          pushSelection();
          break;
        case "dashboard:filters":
          // eslint-disable-next-line no-console
          console.log("[omni] dashboard:filters", event.data.payload);
          break;
        case "error":
          // eslint-disable-next-line no-console
          console.error("[omni] error", event.data.payload);
          break;
      }
    }
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, [pushSelection]);

  function toggle(value: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(value)) next.delete(value);
      else next.add(value);
      return next;
    });
    setTimeout(pushSelection, 0);
  }

  async function logout() {
    await fetch("/api/logout", { method: "POST" });
    router.push("/login");
    router.refresh();
  }

  return (
    <div style={{ display: "flex", flex: 1, minHeight: 0 }}>
      {/* Sidebar: signed-in user + custom field picker */}
      <aside
        style={{
          width: 280,
          borderRight: "1px solid #e5e7eb",
          background: "#fff",
          padding: 16,
          overflowY: "auto",
          display: "flex",
          flexDirection: "column",
        }}
      >
        <div
          style={{
            paddingBottom: 14,
            marginBottom: 14,
            borderBottom: "1px solid #f3f4f6",
          }}
        >
          <div style={{ fontSize: 13, fontWeight: 600 }}>{email}</div>
          <div style={{ fontSize: 12, color: "#6b7280", marginTop: 2 }}>
            Customer: {customerId}
          </div>
          <button
            onClick={logout}
            style={{
              marginTop: 10,
              fontSize: 12,
              padding: "4px 10px",
              border: "1px solid #d1d5db",
              borderRadius: 6,
              background: "#fff",
              cursor: "pointer",
            }}
          >
            Sign out
          </button>
        </div>

        <div style={{ fontSize: 12, fontWeight: 600, color: "#374151", marginBottom: 8 }}>
          Custom fields
        </div>

        {error && (
          <div style={{ color: "#b91c1c", fontSize: 12 }}>Error: {error}</div>
        )}
        {!error && fields.length === 0 && (
          <div style={{ color: "#6b7280", fontSize: 12 }}>No fields.</div>
        )}

        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          {fields.map((f) => (
            <label
              key={f.value}
              style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13 }}
            >
              <input
                type="checkbox"
                checked={selected.has(f.value)}
                onChange={() => toggle(f.value)}
              />
              {f.label}
            </label>
          ))}
        </div>

        <div style={{ marginTop: 18, fontSize: 11, color: "#9ca3af" }}>{status}</div>
      </aside>

      {/* Embedded Omni dashboard */}
      <section style={{ flex: 1, minWidth: 0, background: "#f3f4f6" }}>
        {embedUrl ? (
          <iframe
            ref={iframeRef}
            src={embedUrl}
            title="Omni dashboard"
            style={{ width: "100%", height: "100%", border: "none" }}
          />
        ) : (
          <div style={{ padding: 24, color: "#6b7280" }}>{error || status}</div>
        )}
      </section>
    </div>
  );
}
