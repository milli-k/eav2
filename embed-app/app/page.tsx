import { redirect } from "next/navigation";
import { getSession } from "@/lib/session";
import FieldPickerEmbed from "./components/FieldPickerEmbed";

// Server component — requires a session; the tenant comes from the logged-in user.
export default function Page() {
  const session = getSession();
  if (!session) redirect("/login");

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
          Pick fields to bring into your dashboard. Your available fields are
          determined by your company&apos;s data model.
        </p>
      </header>
      <FieldPickerEmbed email={session.email} customerId={session.customerId} />
    </main>
  );
}
