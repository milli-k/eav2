import type { Metadata } from "next";
import type { ReactNode } from "react";

export const metadata: Metadata = {
  title: "Omni Custom Field Picker",
  description: "Embedded Omni dashboard with a per-tenant custom field picker",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body
        style={{
          margin: 0,
          fontFamily:
            "ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, sans-serif",
          color: "#111827",
          background: "#f9fafb",
        }}
      >
        {children}
      </body>
    </html>
  );
}
