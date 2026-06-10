// Server-only Omni REST API helpers. Never import this from a client component
// — it reads the API key from the environment.
import "server-only";

function apiBase(): string {
  const base = process.env.OMNI_API_BASE;
  if (!base) throw new Error("OMNI_API_BASE is not set");
  return base.replace(/\/$/, "");
}

function apiKey(): string {
  const key = process.env.OMNI_API_KEY;
  if (!key) throw new Error("OMNI_API_KEY is not set");
  return key;
}

async function apiGet<T>(path: string): Promise<T> {
  const res = await fetch(`${apiBase()}${path}`, {
    headers: { Authorization: `Bearer ${apiKey()}` },
    // These are tenant-config reads; a short cache keeps the UI snappy without
    // going stale for long. Adjust or set `cache: "no-store"` if needed.
    next: { revalidate: 30 },
  });
  if (!res.ok) {
    throw new Error(`Omni API ${path} -> ${res.status} ${await res.text()}`);
  }
  return (await res.json()) as T;
}

export type PickerField = {
  /** Fully-qualified field ref, e.g. "my_db_main__dim_subject.location". */
  value: string;
  /** Human label, e.g. "Location". */
  label: string;
};

export type DashboardPicker = {
  /** The FIELD_PICKER control id used to build the f--<id> URL parameter. */
  pickerId: string;
  /** Selectable fields, in dashboard order. */
  fields: PickerField[];
};

type FilterConfigEntry = {
  id: string;
  type: string;
  options?: Array<{ label: string; value: string }>;
};

type DashboardDocument = {
  filterConfig?: Record<string, FilterConfigEntry>;
  filterOrder?: string[];
};

/**
 * Read a dashboard's FIELD_PICKER control: its id and selectable fields.
 * The control's options ARE the tenant's custom fields, so this doubles as the
 * field-listing source for the picker UI.
 */
export async function getDashboardPicker(
  dashboardId: string
): Promise<DashboardPicker> {
  const doc = await apiGet<DashboardDocument>(
    `/api/v1/documents/${dashboardId}`
  );
  const config = doc.filterConfig ?? {};
  const order = doc.filterOrder ?? Object.keys(config);

  const pickerId = order.find((id) => config[id]?.type === "FIELD_PICKER");
  if (!pickerId) {
    throw new Error(
      `Dashboard ${dashboardId} has no FIELD_PICKER control in filterConfig`
    );
  }

  const fields = (config[pickerId].options ?? []).map((o) => ({
    value: o.value,
    label: o.label,
  }));

  return { pickerId, fields };
}
