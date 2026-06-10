// Server-only embed URL signing via the @omni-co/embed SDK.
import "server-only";
import { embedSsoDashboard, EmbedSessionMode } from "@omni-co/embed";

export type SignedEmbed = {
  /** Fully signed embed URL to drop into an iframe `src`. */
  url: string;
  /** Origin of the embed URL — the targetOrigin for postMessage calls. */
  origin: string;
};

/**
 * Sign a single-content dashboard embed for a given tenant. The customer_id
 * user attribute resolves the tenant's dynamic_shared_extension AND drives the
 * topic's access_filters (row-level security), so the embedded user only sees
 * their own rows and their own custom fields.
 */
export async function signTenantDashboard(opts: {
  dashboardId: string;
  customerId: string;
}): Promise<SignedEmbed> {
  const host = process.env.OMNI_EMBED_HOST;
  const secret = process.env.OMNI_EMBED_SECRET;
  if (!host) throw new Error("OMNI_EMBED_HOST is not set");
  if (!secret) throw new Error("OMNI_EMBED_SECRET is not set");

  const url = await embedSsoDashboard({
    contentId: opts.dashboardId,
    secret,
    host, // bare hostname — no protocol, no port
    externalId: process.env.OMNI_EMBED_USER_EMAIL || "embed-demo@example.com",
    name: process.env.OMNI_EMBED_USER_NAME || "Embed Demo User",
    userAttributes: { customer_id: [opts.customerId] },
    mode: EmbedSessionMode.SingleContent,
    prefersDark: "false",
  });

  return { url, origin: new URL(url).origin };
}
