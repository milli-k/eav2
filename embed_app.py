"""Generate a self-contained hierarchical-filter demo for an Omni embed.

Run it, get `embed_demo.html`, open it in a browser. The customer's hierarchy
data is baked into the HTML at generation time; the only runtime dependency is
the Inter web font. The embed URL is signed here in Python so the HMAC secret
never reaches the browser.

Configuration
-------------
Copy `.env.example` to `.env` and fill in your values before running.

Required environment variables
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
OMNI_EMBED_SECRET       Your Omni embed secret (Settings → Embed).
OMNI_VANITY_DOMAIN      Your embed vanity domain, e.g. yourorg.embed-omniapp.co
OMNI_DASHBOARD_PATH     Path to the dashboard, e.g. /embed/dashboards/<id>

Optional environment variables
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
CSV_PATH                Path to your subjects CSV (default: dim_subject.csv)
EMBED_OUTPUT_FILE       Output HTML filename (default: embed_demo.html)
EMBED_FILTER_FIELD      The Omni field ID the filter targets.
                        Format: <view_name>.<field_name>
                        e.g. my_schema__dim_subject.subject_id
OMNI_DEMO_EXTERNAL_ID   External user ID baked into the signed URL (default: demo-user-001)
OMNI_DEMO_USER_NAME     Display name baked into the signed URL (default: Demo User)
OMNI_DEMO_CUSTOMER_ID   customer_id user attribute value to scope the iframe (RLS).
                        Defaults to the first customer found in the CSV.
"""
import argparse
import base64
import csv
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import sys
import urllib.parse
from dotenv import load_dotenv


logger = logging.getLogger('embed_app')

load_dotenv()  # picks up the OMNI_EMBED_* signing config

# ---------------------------------------------------------------------------
# Configuration — override any of these via environment variables or .env
# ---------------------------------------------------------------------------

# Path to the CSV containing your subject/hierarchy data.
# Expected columns: customer_id, subject_id, dim_subject
CSV_PATH = os.environ.get('CSV_PATH', 'dim_subject.csv')

# Output HTML file
OUTPUT_FILE = os.environ.get('EMBED_OUTPUT_FILE', 'embed_demo.html')

# The Omni field ID used for the dashboard filter.
# This must match the field id in your embedded dashboard's queries.
# Format: <view_name>.<field_name>
# Example: my_schema__dim_subject.subject_id
FILTER_FIELD = os.environ.get('EMBED_FILTER_FIELD', 'YOUR_SCHEMA__DIM_SUBJECT.SUBJECT_ID')

# ---------------------------------------------------------------------------
# Field name normalization
# ---------------------------------------------------------------------------

# Map variant field names to a canonical name when they share the same data.
# e.g. FIELD_ALIASES = {'Mkt': 'Market'}
# Leave empty if your field names are already consistent across tenants.
FIELD_ALIASES: dict[str, str] = {}


def normalize_field_name(name):
    """Canonicalize a raw field name so casing/whitespace variants merge.

    Collapses internal runs of whitespace, strips, and Title Cases the name,
    then applies FIELD_ALIASES. This ensures 'location', ' Location ', and
    'LOCATION' all resolve to the same dimension.
    """
    cleaned = re.sub(r'\s+', ' ', name).strip()
    canonical = cleaned.title()
    return FIELD_ALIASES.get(canonical, canonical)


def parse_dim_subject(packed):
    """Parse a packed dim_subject string into [(field_name, [levels]), ...].

    Fields are delimited by ';' or newlines; within a field the form is
    'Name: levelA > levelB > ...'. Trailing empty levels are dropped so depth
    reflects only populated values. Field names are normalized before being
    returned so variants merge instead of producing duplicate dimensions.

    Example input:  'Region: EMEA > UK > London; Product: SaaS > Analytics'
    Example output: [('Region', ['EMEA', 'UK', 'London']),
                     ('Product', ['SaaS', 'Analytics'])]
    """
    fields = []
    for segment in re.split(r'[;\n]', packed or ''):
        segment = segment.strip()
        if ':' not in segment:
            continue
        name, _, value = segment.partition(':')
        name = normalize_field_name(name)
        if not name:
            continue
        levels = [lvl.strip() for lvl in value.split('>')]
        while levels and not levels[-1]:
            levels.pop()
        fields.append((name, levels))
    return fields


def slug(name):
    """snake_case a field name into an Omni-safe field identifier."""
    s = re.sub(r'[^0-9a-z]+', '_', name.strip().lower()).strip('_')
    return s or 'field'


# ---------------------------------------------------------------------------
# Hierarchy builder
# ---------------------------------------------------------------------------

def build_hierarchy(csv_path):
    """Build per-customer, per-axis selectable nodes from the subjects CSV.

    For each subject's axis path (e.g. 'Region: EMEA > UK > London'), every
    prefix becomes a selectable node. Nodes at the same (axis, level, label)
    are deduplicated and their reachable subject_ids merged. Returns:

        { customer_id: { axis: [ {node_label, node_level, axis,
                                  descendant_subject_ids}, ... ] } }

    Nodes within an axis are returned in pre-order (roots first, then each
    root's subtree) so the UI can render them in tree order.
    """
    from collections import defaultdict

    customers: dict = {}
    with open(csv_path, newline='') as f:
        for row in csv.DictReader(f):
            customer_id = (row.get('customer_id') or '').strip()
            subject_id = (row.get('subject_id') or '').strip()
            if not customer_id or not subject_id:
                continue
            axes = customers.setdefault(customer_id, {})
            for axis, levels in parse_dim_subject(row.get('dim_subject')):
                nodes = axes.setdefault(axis, {})
                path = []
                for level, label in enumerate(levels, start=1):
                    if not label:
                        continue
                    path.append(label)
                    key = (level, label)
                    node = nodes.get(key)
                    if node is None:
                        node = {
                            'node_label': label,
                            'node_level': level,
                            'axis': axis,
                            '_ids': set(),
                            '_path': tuple(path),
                        }
                        nodes[key] = node
                    node['_ids'].add(subject_id)
                    if tuple(path) < node['_path']:
                        node['_path'] = tuple(path)

    data = {}
    for customer_id, axes in customers.items():
        data[customer_id] = {}
        for axis, nodes in axes.items():
            ordered = sorted(nodes.values(), key=lambda n: n['_path'])
            data[customer_id][axis] = [
                {
                    'node_label': n['node_label'],
                    'node_level': n['node_level'],
                    'axis': n['axis'],
                    'descendant_subject_ids': sorted(n['_ids']),
                }
                for n in ordered
            ]
    return data


# ---------------------------------------------------------------------------
# Embed URL signing
# ---------------------------------------------------------------------------

def load_embed_config():
    """Read the embed signing config from the environment.

    Set these in your .env file (see .env.example). Missing values fall back
    to placeholder strings so the HTML can still render for a UI preview, but
    the embed URL will NOT authenticate without a real secret and vanity domain.
    """
    cfg = {
        'secret':           os.environ.get('OMNI_EMBED_SECRET', ''),
        'vanity':           os.environ.get('OMNI_VANITY_DOMAIN', 'YOUR_ORG.embed-omniapp.co'),
        'dashboard_path':   os.environ.get('OMNI_DASHBOARD_PATH', '/embed/dashboards/YOUR_DASHBOARD_ID'),
        'external_id':      os.environ.get('OMNI_DEMO_EXTERNAL_ID', 'demo-user-001'),
        'user_name':        os.environ.get('OMNI_DEMO_USER_NAME', 'Demo User'),
    }
    if not cfg['secret']:
        logger.warning(
            'OMNI_EMBED_SECRET is not set — the embed URL will be signed with '
            'an empty secret and will NOT authenticate. Set it in .env before '
            'running a real demo.'
        )
    return cfg


def sign_embed_url(cfg, customer_id):
    """Sign an Omni SSO embed URL per the Omni embed signing spec.

    The signature is HMAC-SHA256 over the newline-joined values (loginUrl,
    contentPath, externalId, name, nonce, userAttributes), base64url-encoded
    without padding.

    The userAttributes payload sets `customer_id`, which:
      - Selects the correct tenant extension model (dynamic_shared_extensions)
      - Applies row-level security via access_filters on the topic

    The signed URL is static — filters are applied client-side via postMessage,
    so the iframe src doesn't change when the user changes their selection.

    Returns (url, origin).
    """
    login_url = f"https://{cfg['vanity']}/embed/sso/login"
    nonce = secrets.token_hex(16)
    # Compact JSON — the string must be identical in both the signed blob and
    # the URL parameter.
    user_attributes = json.dumps({'customer_id': customer_id}, separators=(',', ':'))

    blob = '\n'.join([
        login_url,
        cfg['dashboard_path'],
        cfg['external_id'],
        cfg['user_name'],
        nonce,
        user_attributes,
    ])
    digest = hmac.new(cfg['secret'].encode('utf-8'), blob.encode('utf-8'),
                      hashlib.sha256).digest()
    signature = base64.urlsafe_b64encode(digest).decode('ascii').rstrip('=')

    params = {
        'contentPath':    cfg['dashboard_path'],
        'externalId':     cfg['external_id'],
        'name':           cfg['user_name'],
        'nonce':          nonce,
        'userAttributes': user_attributes,
        'signature':      signature,
    }
    # urllib.parse.quote (not quote_plus) encodes spaces as %20, which Omni expects.
    query = urllib.parse.urlencode(params, quote_via=urllib.parse.quote)
    url = f'{login_url}?{query}'
    origin = f"https://{cfg['vanity']}"
    return url, origin


# ---------------------------------------------------------------------------
# HTML template
# ---------------------------------------------------------------------------

def _js_json(value):
    """json.dumps safe for inlining inside a <script> tag.

    Escapes '</' so a stray '</script>' in data can't close the tag.
    """
    return json.dumps(value, separators=(',', ':')).replace('</', '<\\/')


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>Omni Hierarchical Filter Demo</title>
<link rel="preconnect" href="https://fonts.googleapis.com" />
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet" />
<style>
  :root {
    --bg: #f7f8fa;
    --card: #ffffff;
    --border: #e6e8ec;
    --text: #1a1d23;
    --muted: #6b7280;
    --accent: #4f46e5;
    --accent-soft: #eef2ff;
    --accent-border: #c7d2fe;
    --radius: 12px;
    --shadow: 0 1px 2px rgba(16, 24, 40, 0.04), 0 1px 3px rgba(16, 24, 40, 0.06);
  }
  * { box-sizing: border-box; }
  html, body { margin: 0; height: 100%; }
  body {
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    color: var(--text);
    background: var(--bg);
    font-size: 14px;
    line-height: 1.45;
  }
  .app { display: flex; height: 100vh; }
  .panel {
    width: 40%;
    min-width: 360px;
    max-width: 560px;
    padding: 24px;
    overflow-y: auto;
    border-right: 1px solid var(--border);
    background: var(--bg);
  }
  .viewer { flex: 1; min-width: 0; background: #eceef1; }
  .viewer iframe { width: 100%; height: 100%; border: none; display: block; }

  .title { font-size: 18px; font-weight: 700; margin: 0 0 2px; }
  .subtitle { color: var(--muted); margin: 0 0 20px; font-size: 13px; }

  .field { margin-bottom: 18px; }
  .field > label {
    display: block; font-weight: 600; font-size: 12px;
    text-transform: uppercase; letter-spacing: 0.04em;
    color: var(--muted); margin-bottom: 6px;
  }
  select {
    width: 100%; padding: 9px 12px; font: inherit; color: var(--text);
    background: var(--card); border: 1px solid var(--border);
    border-radius: 10px; appearance: none; cursor: pointer;
    background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='16' height='16' viewBox='0 0 24 24' fill='none' stroke='%236b7280' stroke-width='2'%3E%3Cpath d='M6 9l6 6 6-6'/%3E%3C/svg%3E");
    background-repeat: no-repeat; background-position: right 10px center;
    padding-right: 34px;
  }
  select:focus { outline: none; border-color: var(--accent-border); box-shadow: 0 0 0 3px var(--accent-soft); }

  .axis-card {
    background: var(--card); border: 1px solid var(--border);
    border-radius: var(--radius); padding: 14px; margin-bottom: 12px;
    box-shadow: var(--shadow);
  }
  .axis-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px; }
  .axis-head label { font-weight: 600; font-size: 14px; }
  .pill {
    font-size: 11px; font-weight: 600; padding: 2px 9px; border-radius: 999px;
    background: #f1f3f5; color: var(--muted); border: 1px solid var(--border);
    white-space: nowrap;
  }
  .pill.active { background: var(--accent-soft); color: var(--accent); border-color: var(--accent-border); }

  .actions { display: flex; gap: 10px; margin: 20px 0 18px; }
  button {
    font: inherit; font-weight: 600; padding: 9px 16px; border-radius: 10px;
    cursor: pointer; border: 1px solid transparent;
  }
  button.primary { background: var(--accent); color: #fff; }
  button.primary:hover { filter: brightness(1.05); }
  button.ghost { background: var(--card); color: var(--text); border-color: var(--border); }
  button.ghost:hover { background: #f1f3f5; }

  .summary-wrap { background: var(--card); border: 1px solid var(--border); border-radius: var(--radius); box-shadow: var(--shadow); overflow: hidden; }
  .summary-title {
    font-size: 12px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.04em;
    color: var(--muted); padding: 10px 14px; border-bottom: 1px solid var(--border); background: #fafbfc;
  }
  pre#summary {
    margin: 0; padding: 14px; font-size: 12px; line-height: 1.5;
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    white-space: pre-wrap; word-break: break-word; color: #334155; max-height: 280px; overflow: auto;
  }
</style>
</head>
<body>
<div class="app">
  <aside class="panel">
    <h1 class="title">Hierarchical Filter</h1>
    <p class="subtitle">Pick nodes across axes; selections intersect (AND) and drive the embedded dashboard.</p>

    <div class="field">
      <label for="customer">Customer</label>
      <select id="customer"></select>
    </div>

    <div id="axes"></div>

    <div class="actions">
      <button id="apply" class="primary">Apply filter</button>
      <button id="clear" class="ghost">Clear</button>
    </div>

    <div class="summary-wrap">
      <div class="summary-title">Filter payload (live)</div>
      <pre id="summary"></pre>
    </div>
  </aside>
  <main class="viewer">
    <iframe id="omni" src="__EMBED_URL_ATTR__" title="Omni dashboard"></iframe>
  </main>
</div>

<script>
  // Baked-in at generation time. The HMAC secret stays server-side in
  // embed_app.py and never reaches the browser; only the already-signed URL
  // is shipped with the HTML.
  const HIERARCHY_DATA = __HIERARCHY_JSON__;
  const OMNI_ORIGIN = __OMNI_ORIGIN_JSON__;
  const FILTER_FIELD = __FILTER_FIELD_JSON__;

  const customerSelect = document.getElementById('customer');
  const axesEl = document.getElementById('axes');
  const summaryEl = document.getElementById('summary');
  const iframe = document.getElementById('omni');
  const applyBtn = document.getElementById('apply');
  const clearBtn = document.getElementById('clear');

  // Indent option text proportional to depth so the flat <select> reads as a
  // tree. Level 1 = root (no prefix); deeper levels get nbsp indent + en-dash.
  function indent(level) {
    const pad = '\\u00A0\\u00A0\\u00A0'.repeat(Math.max(0, level - 1));
    return level > 1 ? pad + '\\u2013 ' : pad;
  }

  function renderAxes(customerId) {
    axesEl.innerHTML = '';
    const axes = HIERARCHY_DATA[customerId] || {};
    for (const axis of Object.keys(axes)) {
      const nodes = axes[axis];
      const card = document.createElement('div');
      card.className = 'axis-card';

      const head = document.createElement('div');
      head.className = 'axis-head';
      const label = document.createElement('label');
      label.setAttribute('for', 'axis-' + axis);
      label.textContent = axis;
      const pill = document.createElement('span');
      pill.className = 'pill';
      pill.id = 'pill-' + axis;
      pill.textContent = 'All';
      head.appendChild(label);
      head.appendChild(pill);

      const sel = document.createElement('select');
      sel.id = 'axis-' + axis;
      sel.className = 'axis-select';
      sel.dataset.axis = axis;
      const allOpt = document.createElement('option');
      allOpt.value = '';
      allOpt.textContent = 'All ' + axis + 's';
      sel.appendChild(allOpt);
      // Nodes already arrive in pre-order from Python, so render as-is.
      nodes.forEach(function (n, i) {
        const o = document.createElement('option');
        o.value = String(i);
        o.textContent = indent(n.node_level) + n.node_label + '  (' + n.descendant_subject_ids.length + ')';
        sel.appendChild(o);
      });
      sel.addEventListener('change', updateSummary);

      card.appendChild(head);
      card.appendChild(sel);
      axesEl.appendChild(card);
    }
    updateSummary();
  }

  // The nodes currently chosen (excluding the "All" option) for the active
  // customer, one per axis dropdown.
  function selectedNodes() {
    const axes = HIERARCHY_DATA[customerSelect.value] || {};
    const chosen = [];
    document.querySelectorAll('.axis-select').forEach(function (sel) {
      if (sel.value === '') return;
      chosen.push(axes[sel.dataset.axis][Number(sel.value)]);
    });
    return chosen;
  }

  function intersect(sets) {
    if (sets.length === 0) return [];
    let acc = new Set(sets[0]);
    for (let i = 1; i < sets.length; i++) {
      const s = new Set(sets[i]);
      acc = new Set([...acc].filter(function (x) { return s.has(x); }));
    }
    return [...acc].sort();
  }

  // Intersect (AND) the descendant id sets of every selected axis.
  // No selection => empty list => "show everything" (no filter constraint).
  function currentValues() {
    const nodes = selectedNodes();
    if (nodes.length === 0) return [];
    return intersect(nodes.map(function (n) { return n.descendant_subject_ids; }));
  }

  function filterUrlParameter(values) {
    const filter = { kind: 'EQUALS', type: 'string', values: values, is_negative: false };
    return 'f--' + FILTER_FIELD + '=' + JSON.stringify(filter);
  }

  function updateSummary() {
    const axes = HIERARCHY_DATA[customerSelect.value] || {};
    document.querySelectorAll('.axis-select').forEach(function (sel) {
      const pill = document.getElementById('pill-' + sel.dataset.axis);
      if (sel.value === '') {
        pill.textContent = 'All';
        pill.classList.remove('active');
      } else {
        const n = axes[sel.dataset.axis][Number(sel.value)];
        pill.textContent = 'Level ' + n.node_level;
        pill.classList.add('active');
      }
    });
    const values = currentValues();
    summaryEl.textContent = JSON.stringify({
      filterUrlParameter: filterUrlParameter(values),
      matchedSubjectCount: values.length
    }, null, 2);
  }

  // Push the filter into the embedded dashboard via postMessage.
  // Omni listens for this exact envelope and applies the f-- URL parameter
  // to the live dashboard without a page reload.
  function sendFilter(values) {
    iframe.contentWindow.postMessage({
      source: 'omni',
      name: 'dashboard:filter-change-by-url-parameter',
      payload: { filterUrlParameter: filterUrlParameter(values) }
    }, OMNI_ORIGIN);
  }

  applyBtn.addEventListener('click', function () { sendFilter(currentValues()); });
  clearBtn.addEventListener('click', function () {
    document.querySelectorAll('.axis-select').forEach(function (s) { s.value = ''; });
    updateSummary();
    sendFilter([]);  // values:[] resets the filter
  });
  customerSelect.addEventListener('change', function () {
    renderAxes(customerSelect.value);
    sendFilter([]);  // reset the iframe filter when switching tenants
  });

  // Populate the customer selector and render the first tenant.
  Object.keys(HIERARCHY_DATA).forEach(function (c) {
    const o = document.createElement('option');
    o.value = c;
    o.textContent = c;
    customerSelect.appendChild(o);
  });
  renderAxes(Object.keys(HIERARCHY_DATA)[0]);
</script>
</body>
</html>
"""


def render_html(hierarchy_data, embed_url, origin):
    html = HTML_TEMPLATE
    html = html.replace('__HIERARCHY_JSON__', _js_json(hierarchy_data))
    html = html.replace('__OMNI_ORIGIN_JSON__', _js_json(origin))
    html = html.replace('__FILTER_FIELD_JSON__', _js_json(FILTER_FIELD))
    # iframe src lives in an HTML attribute; escape & and quotes.
    html = html.replace('__EMBED_URL_ATTR__',
                        embed_url.replace('&', '&amp;').replace('"', '&quot;'))
    return html


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description='Generate a self-contained Omni hierarchical-filter demo HTML.')
    parser.add_argument('--customer',
                        help='Bake only this customer_id into the HTML for a '
                             'focused demo (default: all customers).')
    parser.add_argument('--emit-json', metavar='PATH',
                        help='Write the hierarchy data as JSON to PATH and exit, '
                             'without signing or writing HTML. Useful for '
                             'regenerating the hierarchy.json file consumed by '
                             'a Next.js or other front-end embed app.')
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')

    hierarchy_data = build_hierarchy(CSV_PATH)
    if not hierarchy_data:
        logger.error('No customers found in %s', CSV_PATH)
        sys.exit(1)

    if args.customer:
        if args.customer not in hierarchy_data:
            logger.error('Customer %s not found in %s', args.customer, CSV_PATH)
            sys.exit(1)
        hierarchy_data = {args.customer: hierarchy_data[args.customer]}

    # JSON-emit mode: dump the parsed hierarchy and stop.
    # No signing or secret needed.
    if args.emit_json:
        with open(args.emit_json, 'w') as f:
            json.dump(hierarchy_data, f, indent=2)
            f.write('\n')
        for customer_id, axes in hierarchy_data.items():
            node_count = sum(len(nodes) for nodes in axes.values())
            logger.info('  %s: %d axes, %d nodes (%s)',
                        customer_id, len(axes), node_count, ', '.join(axes))
        logger.info('Wrote hierarchy JSON to %s', args.emit_json)
        return

    cfg = load_embed_config()

    # The signed URL scopes the iframe to ONE tenant via the customer_id user
    # attribute (RLS + extension). Prefer --customer, then OMNI_DEMO_CUSTOMER_ID
    # from .env, then the first customer in the CSV.
    # Note: the client-side customer selector only re-targets the filter UI —
    # it does NOT re-scope server-side RLS. Use --customer or
    # OMNI_DEMO_CUSTOMER_ID to sign for a different tenant.
    embed_customer = (args.customer
                      or os.environ.get('OMNI_DEMO_CUSTOMER_ID')
                      or next(iter(hierarchy_data)))
    embed_url, origin = sign_embed_url(cfg, embed_customer)

    html = render_html(hierarchy_data, embed_url, origin)
    with open(OUTPUT_FILE, 'w') as f:
        f.write(html)

    for customer_id, axes in hierarchy_data.items():
        node_count = sum(len(nodes) for nodes in axes.values())
        logger.info('  %s: %d axes, %d nodes (%s)',
                    customer_id, len(axes), node_count, ', '.join(axes))
    logger.info('Wrote %s (embed origin %s)', OUTPUT_FILE, origin)
    logger.info('Embed URL scoped to customer_id=%s via userAttributes', embed_customer)
    if not args.customer and len(hierarchy_data) > 1:
        logger.warning(
            'Iframe is RLS-scoped to %s only; switching customers in the UI '
            're-targets filters but not server-side scope. Use --customer or '
            'OMNI_DEMO_CUSTOMER_ID to scope a different tenant.', embed_customer)


if __name__ == '__main__':
    main()
