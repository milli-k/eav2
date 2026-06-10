// Maps each tenant (customer_id) to the Omni dashboard that hosts its
// FIELD_PICKER control. The dashboard's filterConfig is the source of truth
// for both the picker id and the selectable field list, so we only need the
// dashboard identifier here.
//
// Each dashboard's FIELD_PICKER lists that tenant's dim_subject custom fields.
// These are produced by ../../generate_dashboards.py — re-run it and paste the
// printed mapping here when tenants or their fields change.

export type TenantConfig = {
  /** Omni dashboard identifier (the `identifier` from the documents API / URL). */
  dashboardId: string;
};

export const TENANTS: Record<string, TenantConfig> = {
  ABC: { dashboardId: "18512be7" },
  DEF: { dashboardId: "5fe10858" },
  GHI: { dashboardId: "270626e0" },
  JKL: { dashboardId: "bffa4a59" },
};

export function getTenant(customerId: string): TenantConfig | undefined {
  return TENANTS[customerId];
}

export const TENANT_IDS = Object.keys(TENANTS);
