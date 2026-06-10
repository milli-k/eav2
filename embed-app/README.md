# Omni Custom Field Picker (embed app)

A Next.js + TypeScript app that embeds an Omni dashboard and renders a **custom
field picker** alongside it. The picker lists each customer's custom fields
(from their extension model) and, when you toggle a field, updates the embedded
dashboard **live** — no reload.

## How it works

```
┌─────────────────────────────┐        ┌──────────────────────────────┐
│  Sidebar (your React UI)    │        │  Embedded Omni dashboard      │
│  • customer switcher        │ post   │  (iframe, signed SSO URL)     │
│  • custom-field checkboxes  │ message│  • table tile on dim_subject  │
│           ───────────────────────────▶  • native FIELD_PICKER control│
└─────────────────────────────┘        └──────────────────────────────┘
```

- **Field list + picker id** come straight from the dashboard's `filterConfig`
  (`GET /api/v1/documents/{id}` → the `FIELD_PICKER` control's `options`). The
  control's options are exactly that tenant's `my_db_main__dim_subject.*`
  custom fields, so the picker is automatically per-tenant.
- **Embed signing** is done server-side with `@omni-co/embed`
  (`embedSsoDashboard`). The `customer_id` user attribute both resolves the
  tenant's `dynamic_shared_extension` and drives the topic's `access_filters`
  (row-level security).
- **Live updates**: toggling a field posts
  `dashboard:filter-change-by-url-parameter` into the iframe with
  `f--<pickerId>={"values":[...field refs...]}`. This is the only supported way
  to change a tile's *fields* live from the parent — there is no field-injection
  event, so we drive Omni's native multi-field-picker control instead.

## Setup

```bash
cd embed-app
npm install
cp .env.local.example .env.local   # then fill in the values
npm run dev                         # http://localhost:3000
```

Required env (`.env.local`):

| Var | What |
|-----|------|
| `OMNI_API_BASE` | API host, e.g. `https://milli-test.playground.exploreomni.dev` |
| `OMNI_API_KEY` | API key (Settings → API Keys) — server-side only |
| `OMNI_HUB_MODEL_ID` | Base shared model id the extensions extend |
| `OMNI_EMBED_HOST` | Embed hostname only (no `https://`). From Admin → Embed |
| `OMNI_EMBED_SECRET` | **Embed secret from Admin → Embed — required for the iframe to load** |
| `OMNI_EMBED_USER_EMAIL` / `_NAME` | Identifies the embedded viewer |

> Without a valid `OMNI_EMBED_SECRET` the field list still loads, but the iframe
> will fail to authenticate. The secret is in your Omni instance under
> **Admin → Embed**.

## Adding tenants

Each tenant needs a dashboard with a `FIELD_PICKER` control listing its fields.
Map `customer_id → dashboardId` in `lib/tenants.ts`. `ABC` is wired to the
existing "Subject Dimension Overview" dashboard (`1271bd48`). DEF/GHI/JKL
dashboards are produced by the dashboard generator (see repo root) and added to
the same map.

## Confirming the FIELD_PICKER value shape

The picker sends `{"values":[...]}`. When the dashboard loads, the app logs the
`dashboard:filters` event Omni emits to the browser console — use it to confirm
the exact shape Omni round-trips, and adjust `fieldPickerParam()` in
`app/components/FieldPickerEmbed.tsx` if your instance differs.
