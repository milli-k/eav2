import { NextRequest, NextResponse } from "next/server";
import { tenantForEmail } from "@/lib/auth";
import { serializeSession, SESSION_COOKIE, SESSION_MAX_AGE } from "@/lib/session";

// POST /api/login  { email } -> sets the session cookie (tenant from domain).
export async function POST(req: NextRequest) {
  const body = await req.json().catch(() => ({}));
  const email = typeof body.email === "string" ? body.email.trim().toLowerCase() : "";
  if (!email || !email.includes("@")) {
    return NextResponse.json({ error: "Enter a valid email address." }, { status: 400 });
  }

  const customerId = tenantForEmail(email);
  if (!customerId) {
    return NextResponse.json(
      { error: `No customer is mapped to the domain of '${email}'.` },
      { status: 403 }
    );
  }

  const res = NextResponse.json({ ok: true, customerId });
  res.cookies.set(SESSION_COOKIE, serializeSession({ email, customerId }), {
    httpOnly: true,
    sameSite: "lax",
    secure: process.env.NODE_ENV === "production",
    path: "/",
    maxAge: SESSION_MAX_AGE,
  });
  return res;
}
