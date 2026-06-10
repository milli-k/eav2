import "server-only";
import crypto from "node:crypto";
import { cookies } from "next/headers";

// Minimal stateless session: a JSON payload + HMAC signature stored in an
// httpOnly cookie. No DB needed. Swap for a real auth library for production.

export const SESSION_COOKIE = "session";
export const SESSION_MAX_AGE = 60 * 60 * 8; // 8 hours

export type Session = { email: string; customerId: string };

function secret(): string {
  return process.env.SESSION_SECRET || "dev-insecure-secret-change-me";
}

function sign(payload: string): string {
  return crypto.createHmac("sha256", secret()).update(payload).digest("base64url");
}

export function serializeSession(s: Session): string {
  const payload = Buffer.from(JSON.stringify(s)).toString("base64url");
  return `${payload}.${sign(payload)}`;
}

export function parseSession(token: string | undefined): Session | null {
  if (!token) return null;
  const [payload, sig] = token.split(".");
  if (!payload || !sig) return null;
  const expected = sign(payload);
  const a = Buffer.from(sig);
  const b = Buffer.from(expected);
  if (a.length !== b.length || !crypto.timingSafeEqual(a, b)) return null;
  try {
    return JSON.parse(Buffer.from(payload, "base64url").toString()) as Session;
  } catch {
    return null;
  }
}

/** Read and verify the current session from the request cookies. */
export function getSession(): Session | null {
  return parseSession(cookies().get(SESSION_COOKIE)?.value);
}
