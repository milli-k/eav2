import { NextRequest, NextResponse } from "next/server";
import { getTenant } from "@/lib/tenants";
import { signTenantDashboard } from "@/lib/sign";

// GET /api/embed?customerId=ABC -> { url, origin }
export async function GET(req: NextRequest) {
  const customerId = req.nextUrl.searchParams.get("customerId");
  if (!customerId) {
    return NextResponse.json({ error: "customerId is required" }, { status: 400 });
  }
  const tenant = getTenant(customerId);
  if (!tenant) {
    return NextResponse.json(
      { error: `Unknown tenant '${customerId}'` },
      { status: 404 }
    );
  }
  try {
    const signed = await signTenantDashboard({
      dashboardId: tenant.dashboardId,
      customerId,
    });
    return NextResponse.json(signed);
  } catch (err) {
    return NextResponse.json(
      { error: (err as Error).message },
      { status: 500 }
    );
  }
}
