import { NextResponse } from "next/server";
import { SESSION_COOKIE } from "@/lib/session";

// POST /api/logout -> clears the session cookie.
export async function POST() {
  const res = NextResponse.json({ ok: true });
  res.cookies.delete(SESSION_COOKIE);
  return res;
}
