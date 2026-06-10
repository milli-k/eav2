import { NextRequest, NextResponse } from "next/server";
import { getTenant } from "@/lib/tenants";
import { getDashboardPicker } from "@/lib/omni";

// GET /api/fields?customerId=ABC -> { pickerId, fields: [{value,label}] }
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
    const picker = await getDashboardPicker(tenant.dashboardId);
    return NextResponse.json(picker);
  } catch (err) {
    return NextResponse.json(
      { error: (err as Error).message },
      { status: 500 }
    );
  }
}
