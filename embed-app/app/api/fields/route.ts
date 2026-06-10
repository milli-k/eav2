import { NextResponse } from "next/server";
import { getTenant } from "@/lib/tenants";
import { getDashboardPicker } from "@/lib/omni";
import { getSession } from "@/lib/session";

// GET /api/fields -> { pickerId, fields } for the signed-in user's tenant.
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
    const picker = await getDashboardPicker(tenant.dashboardId);
    return NextResponse.json(picker);
  } catch (err) {
    return NextResponse.json({ error: (err as Error).message }, { status: 500 });
  }
}
