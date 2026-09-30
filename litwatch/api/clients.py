# apps/litwatch/litwatch/api/clients.py

import frappe
from frappe import _


@frappe.whitelist(methods=["GET"])
def get_clients():
    """
    Returns the client roster with per-client summary metrics.

    Used in:
      - Sidebar's ActiveClientDropdown
      - Client Portfolio (per-client cards) — /client-portfolio
      - Client Management (roster) — /client-management

    Response:
      [
        {
          "key": "masl",
          "name": "Meridian Apparel Sourcing Ltd",
          "shortName": "MASL",
          "pan": "AABCM1234F",
          "sector": "Textiles",
          "notices": 14,
          "demand": 1840000,
          "overdue": 2,
          "registrations": [
            { "gstin": "29ABCDE1234F1Z5", "state": "Karnataka", "consent": "active" }
          ],
          "trendData": [3, 5, 2, 6, 4, 7, 3, 5, 8, 6, 4, 5],
          "resolvedData": [2, 4, 3, 5, 4, 6, 3, 4, 7, 5, 5, 4]
        }
      ]
    """
    from frappe.utils import add_months, get_first_day, get_last_day, getdate, nowdate

    raw_clients = frappe.get_all(
        "Client",
        fields=["name", "client_name", "short_name", "pan", "sector"],
        limit_page_length=0,
    )

    # Rename fields in Python instead of aliasing reserved words in SQL
    clients = []
    for rc in raw_clients:
        clients.append({
            "key": rc["name"],
            "name": rc["client_name"],
            "shortName": rc["short_name"],
            "pan": rc["pan"],
            "sector": rc["sector"],
        })

    today = getdate(nowdate())

    # Build the trailing 12-month window (oldest first)
    months = []
    for i in range(11, -1, -1):
        month_date = add_months(today, -i)
        months.append({
            "start": get_first_day(month_date),
            "end": get_last_day(month_date),
        })

    for c in clients:
        client_key = c["key"]

        # Litigation Notice was removed; notice metrics stay in the
        # response (as zeros) so the frontend shape does not change.
        c["notices"] = 0
        c["demand"] = 0
        c["overdue"] = 0

        registrations = frappe.get_all(
            "GST Registration",
            filters={"client": client_key},
            fields=["gstin", "state", "consent_status as consent"],
            limit_page_length=0,
        )
        c["registrations"] = registrations

        c["trendData"] = [0] * len(months)
        c["resolvedData"] = [0] * len(months)

    return clients


def _resolve_firm_profile():
    firm_profile = frappe.defaults.get_user_default("firm_profile")
    if firm_profile and frappe.db.exists("Firm Profile", firm_profile):
        return firm_profile

    existing = frappe.db.get_value("Client", {"firm_profile": ["is", "set"]}, "firm_profile")
    if existing and frappe.db.exists("Firm Profile", existing):
        return existing

    first = frappe.db.get_value("Firm Profile", {}, "name", order_by="creation asc")
    if first:
        return first

    frappe.throw(_("No Firm Profile exists. Create one before adding clients."))


def _onboarding_stages():
    options = frappe.get_meta("Client").get_field("onboarding_stage").options or ""
    return [o for o in options.split("\n") if o]


@frappe.whitelist(methods=["POST"])
def create_client(name=None, pan=None, sector=None, firstGstin=None):
    import re
    from frappe.utils import nowdate

    name = str(name or "").strip()
    if not name:
        frappe.throw(_("name is required"))

    firstGstin = str(firstGstin or "").strip().upper() or None
    if firstGstin:
        if not re.fullmatch(r"[0-9]{2}[A-Z0-9]{13}", firstGstin):
            frappe.throw(_("Invalid GSTIN: {0}").format(firstGstin))
        owner = frappe.db.get_value("GST Registration", firstGstin, "client")
        if owner:
            frappe.throw(_("GSTIN {0} is already registered to client {1}").format(firstGstin, owner))

    initials = "".join(w[0].upper() for w in name.split() if w and w[0].isalnum()) or "CL"
    client_code = initials
    suffix = 1
    while frappe.db.exists("Client", client_code):
        suffix += 1
        client_code = f"{initials}{suffix}"

    stages = _onboarding_stages()
    client = frappe.get_doc({
        "doctype": "Client",
        "client_code": client_code,
        "client_name": name,
        "short_name": client_code,
        "firm_profile": _resolve_firm_profile(),
        "pan": str(pan).strip().upper() if pan else None,
        "sector": str(sector).strip() if sector else None,
        "status": "Active",
        "onboarding_stage": stages[0] if stages else None,
        "onboarding_date": nowdate(),
    })
    client.insert(ignore_permissions=True)

    registrations = []
    if firstGstin:
        reg = frappe.get_doc({
            "doctype": "GST Registration",
            "gstin": firstGstin,
            "client": client.name,
            "consent_status": "inactive",
        }).insert(ignore_permissions=True)
        registrations.append({"gstin": reg.name, "state": reg.state, "consent": reg.consent_status})

    frappe.db.commit()

    frappe.local.response.http_status_code = 201
    return {
        "key": client.name,
        "name": client.client_name,
        "notices": 0,
        "registrations": registrations,
    }

# ---------------------------------------------------------------------------
# 2.3) PATCH /session/active-client
# ---------------------------------------------------------------------------
@frappe.whitelist(methods=["PATCH", "POST"])
def set_active_client(clientKey=None):
    """
    Sets the caller's active client for the current session.

    Used in:
      - Sidebar's ActiveClientDropdown
      - Client Portfolio's "Enter Workspace" button
      - Litigation Dashboard's client tiles
    (triggered on any client-select action; no dedicated page route)

    Accepts `clientKey` from JSON body, form_dict, or query string.

    Returns (200 OK, raw JSON — no "message" wrapper):
      { "clientKey": "masl" }
    """
    body = {}
    if frappe.request and frappe.request.data:
        try:
            body = frappe.request.get_json(silent=True) or {}
        except Exception:
            body = {}

    fd = dict(frappe.form_dict or {})
    qs = dict(frappe.request.args or {}) if frappe.request else {}

    def _pick(*keys):
        for src in (body, fd, qs):
            for k in keys:
                v = src.get(k)
                if v not in (None, ""):
                    return v
        return None

    client_key = clientKey or _pick("clientKey", "client_key", "key")

    if not client_key:
        frappe.throw(_("clientKey is required"))

    # Validate existence — matches the client's `name` docname
    if not frappe.db.exists("Client", client_key):
        # Also try by client_code (uppercase initials) for tolerance
        alt = frappe.db.get_value("Client", {"client_code": client_key.upper()}, "name")
        if alt:
            client_key = alt
        else:
            frappe.throw(_("Client {0} not found").format(client_key))

    frappe.defaults.set_user_default("active_client", client_key)

    # --- Response: raw JSON, no "message" wrapper ---
    frappe.local.response.update({
        "clientKey": client_key,
    })
    frappe.local.response.http_status_code = 200
    return


# ---------------------------------------------------------------------------
# 2.4) GET /session/active-client
# ---------------------------------------------------------------------------
@frappe.whitelist(methods=["GET"])
def get_active_client():
    """
    Returns the caller's currently active client, or null if none is set.

    Used in:
      - Sidebar's ActiveClientDropdown (initial load)
      - Any page that needs to know which client the user is currently in

    Returns (200 OK, raw JSON — no "message" wrapper):
      { "clientKey": "masl" }   or   { "clientKey": null }
    """
    client_key = frappe.defaults.get_user_default("active_client") or None

    frappe.local.response.update({
        "clientKey": client_key,
    })
    frappe.local.response.http_status_code = 200
    return

# ---------------------------------------------------------------------------
# 2.4) GET /clients/pipeline
# ---------------------------------------------------------------------------
@frappe.whitelist(methods=["GET"])
def get_client_pipeline():
    """
    Returns clients in the onboarding pipeline (anything not yet 'Complete').

    Used in: Client Management's onboarding pipeline — /client-management.

    Returns (raw JSON — no "message" wrapper):
      [
        {
          "name": "Horizon Retail Pvt Ltd",
          "sector": "Retail",
          "stage": "GSTIN pending",
          "gstins": 1,
          "when": "2026-08-10"
        }
      ]
    """
    from frappe.utils import getdate

    clients = frappe.get_all(
        "Client",
        filters={"onboarding_stage": ["!=", "Complete"]},
        fields=[
            "name",
            "client_name",
            "sector",
            "onboarding_stage",
            "onboarding_date",
        ],
        limit_page_length=0,
    )

    result = []
    for c in clients:
        gstin_count = frappe.db.count(
            "GST Registration",
            filters={"client": c["name"]},
        )
        when = c.get("onboarding_date")
        result.append({
            "name": c.get("client_name") or c.get("name"),
            "sector": c.get("sector"),
            "stage": c.get("onboarding_stage"),
            "gstins": gstin_count,
            "when": str(getdate(when)) if when else None,
        })

    # Sort by stage (custom order), then by date ascending
    # Order = order of the options on Client.onboarding_stage
    stage_order = {stage: i for i, stage in enumerate(_onboarding_stages(), start=1)}
    result.sort(key=lambda r: (
        stage_order.get(r["stage"], 99),
        r.get("when") or "",
    ))

    frappe.local.response.update({
        "data": result,
    })
    frappe.local.response.http_status_code = 200
    return


# ---------------------------------------------------------------------------
# 2.5) PATCH /clients/:id/pipeline-stage
# ---------------------------------------------------------------------------
@frappe.whitelist(methods=["PATCH", "POST"])
def update_client_pipeline_stage(id=None, stage=None):
    """
    Updates a client's onboarding stage.

    Used in: Client Management's pipeline drag-and-drop / stage selector.

    Accepts `id` and `stage` from JSON body, form_dict, or query string.

    Returns (raw JSON — no "message" wrapper):
      { "name": "Horizon Retail Pvt Ltd", "stage": "GSTIN pending" }
    """
    # --- Resolve params from JSON body / form_dict / query string ---
    body = {}
    if frappe.request and frappe.request.data:
        try:
            body = frappe.request.get_json(silent=True) or {}
        except Exception:
            body = {}

    fd = dict(frappe.form_dict or {})
    qs = dict(frappe.request.args or {}) if frappe.request else {}

    def _pick(*keys):
        for src in (body, fd, qs):
            for k in keys:
                v = src.get(k)
                if v not in (None, ""):
                    return v
        return None

    id = id or _pick("id", "clientKey", "client_key", "key")
    stage = stage or _pick("stage", "onboarding_stage")

    # --- Validation ---
    if not id:
        frappe.throw(_("id is required"))

    if not stage:
        frappe.throw(_("stage is required"))

    valid_stages = _onboarding_stages()
    if stage not in valid_stages:
        frappe.throw(_("Invalid stage: {0}. Must be one of {1}").format(stage, valid_stages))

    if not frappe.db.exists("Client", id):
        # Try client_code fallback
        alt = frappe.db.get_value("Client", {"client_code": id.upper()}, "name")
        if alt:
            id = alt
        else:
            frappe.throw(_("Client {0} not found").format(id))

    # --- Persist ---
    frappe.db.set_value("Client", id, "onboarding_stage", stage)
    frappe.db.commit()

    client_name = frappe.db.get_value("Client", id, "client_name")

    frappe.local.response.update({
        "name": client_name,
        "stage": stage,
    })
    frappe.local.response.http_status_code = 200
    return