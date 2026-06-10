import { TENANT_IDS } from "@/lib/tenants";
import FieldPickerEmbed from "./components/FieldPickerEmbed";

// Server component — passes the configured tenant list to the client.
export default function Page() {
  return (
    <main style={{ height: "100vh", display: "flex", flexDirection: "column" }}>
      <header
        style={{
          padding: "12px 20px",
          borderBottom: "1px solid #e5e7eb",
          background: "#fff",
        }}
      >
        <h1 style={{ fontSize: 16, margin: 0 }}>Custom Field Explorer</h1>
        <p style={{ fontSize: 12, margin: "4px 0 0", color: "#6b7280" }}>
          Pick fields from your model to bring them into the dashboard. The list
          updates per customer based on their extension model.
        </p>
      </header>
      <FieldPickerEmbed tenants={TENANT_IDS} />
    </main>
  );
}
