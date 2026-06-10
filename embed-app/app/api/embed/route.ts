import { NextResponse } from "next/server";
import { getTenant } from "@/lib/tenants";
import { signTenantDashboard } from "@/lib/sign";
import { getSession } from "@/lib/session";
import { nameForEmail } from "@/lib/auth";

// GET /api/embed -> { url, origin } for the signed-in user's tenant.
export async function GET() {
  const session = getSession();
  if (!session) {
    return NextResponse.json({ error: "Not signed in" }, { status: 401 });
  }
  const tenant = getTenant(session.customerId);
  if (!tenant) {
    return NextResponse.json(
      { error: `No dashboard configured for '${session.customerId}'` },
      { status: 404 }
    );
  }
  try {
    const signed = await signTenantDashboard({
      dashboardId: tenant.dashboardId,
      customerId: session.customerId,
      email: session.email,
      name: nameForEmail(session.email),
    });
    return NextResponse.json(signed);
  } catch (err) {
    return NextResponse.json({ error: (err as Error).message }, { status: 500 });
  }
}
