import "server-only";

// Email-domain → customer_id mapping. A user signing in with someone@abc.com
// is mapped to tenant ABC. Edit this to match your tenants' real email domains.
const DOMAIN_TENANTS: Record<string, string> = {
  "abc.com": "ABC",
  "def.com": "DEF",
  "ghi.com": "GHI",
  "jkl.com": "JKL",
};

/** Resolve the customer_id for an email, or null if the domain isn't mapped. */
export function tenantForEmail(email: string): string | null {
  const at = email.lastIndexOf("@");
  if (at < 0) return null;
  const domain = email.slice(at + 1).trim().toLowerCase();
  return DOMAIN_TENANTS[domain] ?? null;
}

/** A friendly display name derived from the local part of the email. */
export function nameForEmail(email: string): string {
  const local = email.slice(0, email.lastIndexOf("@")) || email;
  return local
    .split(/[._-]+/)
    .filter(Boolean)
    .map((p) => p.charAt(0).toUpperCase() + p.slice(1))
    .join(" ");
}
