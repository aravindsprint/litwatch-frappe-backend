# apps/litwatch/litwatch/api/dashboard.py
"""
Command Hub dashboard: every aggregate the page shows, in one call.

GET /api/method/litwatch.api.dashboard.get_command_hub
    ?client_key=<Business ID>   optional, one client only
    &gstin=<GSTIN>              optional, one GSTIN only
    &months=12                  months in the charts (1-36)
    &priority_limit=5           rows in the Active Notices table
    &as_of=YYYY-MM-DD           optional, "today" for the calculation

Notice keeps most of its data in JSON fields filled by the portal sync, the AI
extraction or the frontend. Each value below is read from the first key that
has a value (the *_KEYS lists); add a key there if the frontend stores it
under another name.
"""

import json
import re
from datetime import date, datetime, timedelta

import frappe
from frappe import _
from frappe.utils import cint, getdate, nowdate

# ---------------------------------------------------------------------------
# Where each value is read from: (JSON field, dotted key) in order of preference
# ---------------------------------------------------------------------------
DUE_DATE_KEYS = [
	("portal_metadata", "dueDateOfReplyIso"), ("portal_metadata", "dueDateOfReply"),
	("notice", "due_date"), ("notice", "dueDate"), ("notice", "reply_due_date"),
	("notice", "due_date_of_reply"), ("notice", "replyDueDate"),
	("hearing", "reply_due_date"), ("extensions", "extended_due_date"),
	("analysis", "due_date"),
]
ISSUE_DATE_KEYS = [
	("portal_metadata", "dateOfIssueIso"), ("portal_metadata", "dateOfIssue"),
	("notice", "date_of_issue"), ("notice", "issue_date"), ("notice", "dateOfIssue"),
	("notice", "date"), ("document_identity", "date_of_issue"),
]
RISK_KEYS = [
	("risk_mapping", "risk_level"), ("risk_mapping", "level"), ("risk_mapping", "overall_risk"),
	("risk_mapping", "riskLevel"), ("risk_mapping", "overall.level"), ("risk_mapping", "overall"),
	("risk_mapping", "risk"), ("risk_mapping", "risk_score"), ("risk_mapping", "score"),
	("analysis", "risk_level"), ("analysis", "risk"),
	("analysis", "riskLevel"), ("review", "risk"),
]
DEMAND_TOTAL_KEYS = [
	("demand", "total"), ("demand", "total_demand"), ("demand", "totalDemand"),
	("demand", "grand_total"), ("demand", "total_amount"), ("demand", "amount"),
	("notice", "total_demand"), ("notice", "demand"), ("analysis", "total_demand"),
]
DEMAND_PART_KEYS = ["tax", "interest", "penalty", "late_fee", "fee", "others"]  # summed when no total
STATE_KEYS = [
	("taxpayer", "state"), ("taxpayer", "address.state"), ("jurisdiction_and_authority", "state"),
	("notice", "state"), ("portal_metadata", "state"),
]
NOTICE_TYPE_KEYS = [
	("portal_metadata", "noticeType"), ("notice", "type"), ("notice", "notice_type"),
	("document_identity", "type"), ("notice", "form"),
]
STATUS_KEYS = [("notice", "status"), ("review", "status"), ("analysis", "status")]

RESOLVED_WORDS = ("resolved", "closed", "disposed", "dropped", "settled", "withdrawn", "concluded")
RESOLVED_ON_SUBMIT = True  # a Submitted Notice (docstatus 1) counts as resolved
RISK_LEVELS = ["Critical", "High", "Medium", "Low", "Unrated"]
RISK_RANK = {lvl: i for i, lvl in enumerate(RISK_LEVELS)}

JSON_FIELDS = sorted({f for f, _ in DUE_DATE_KEYS + ISSUE_DATE_KEYS + RISK_KEYS + DEMAND_TOTAL_KEYS
                      + STATE_KEYS + NOTICE_TYPE_KEYS + STATUS_KEYS} | {"demand_versions", "lifecycle_events"})

# GST state codes (first two digits of a GSTIN)
GST_STATES = {
	"01": "Jammu and Kashmir", "02": "Himachal Pradesh", "03": "Punjab", "04": "Chandigarh",
	"05": "Uttarakhand", "06": "Haryana", "07": "Delhi", "08": "Rajasthan", "09": "Uttar Pradesh",
	"10": "Bihar", "11": "Sikkim", "12": "Arunachal Pradesh", "13": "Nagaland", "14": "Manipur",
	"15": "Mizoram", "16": "Tripura", "17": "Meghalaya", "18": "Assam", "19": "West Bengal",
	"20": "Jharkhand", "21": "Odisha", "22": "Chhattisgarh", "23": "Madhya Pradesh", "24": "Gujarat",
	"26": "Dadra and Nagar Haveli and Daman and Diu", "27": "Maharashtra", "29": "Karnataka",
	"30": "Goa", "31": "Lakshadweep", "32": "Kerala", "33": "Tamil Nadu", "34": "Puducherry",
	"35": "Andaman and Nicobar Islands", "36": "Telangana", "37": "Andhra Pradesh", "38": "Ladakh",
	"97": "Other Territory",
}


# ---------------------------------------------------------------------------
# Value helpers
# ---------------------------------------------------------------------------
def _json(value):
	if isinstance(value, (dict, list)):
		return value
	if isinstance(value, str) and value.strip()[:1] in ("{", "["):
		try:
			return json.loads(value)
		except ValueError:
			return None
	return None


def _dig(obj, dotted):
	for part in dotted.split("."):
		if isinstance(obj, dict):
			obj = obj.get(part)
		else:
			return None
	return obj


def _first(row, keys):
	for field, key in keys:
		v = _dig(row["_j"].get(field), key)
		if v not in (None, "", [], {}):
			return v
	return None


def _date(value):
	if value in (None, ""):
		return None
	if isinstance(value, datetime):
		return value.date()
	if isinstance(value, date):
		return value
	s = str(value).strip()[:10]
	for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y"):
		try:
			return datetime.strptime(s, fmt).date()
		except ValueError:
			pass
	try:
		return getdate(str(value))
	except Exception:
		return None


def _amount(value):
	if value in (None, ""):
		return 0.0
	if isinstance(value, (int, float)):
		return float(value)
	if isinstance(value, dict):
		for k in ("total", "amount", "value"):
			if k in value:
				return _amount(value[k])
		return 0.0
	s = re.sub(r"[^\d.\-]", "", str(value))
	try:
		return float(s) if s not in ("", "-", ".") else 0.0
	except ValueError:
		return 0.0


def _risk(value):
	if isinstance(value, dict):
		value = value.get("level") or value.get("value")
	s = str(value or "").strip().lower()
	if not s:
		return "Unrated"
	if s.startswith("crit") or s in ("very high", "severe", "p0"):
		return "Critical"
	if s.startswith("high") or s == "p1":
		return "High"
	if s.startswith("med") or s.startswith("mod") or s == "p2":
		return "Medium"
	if s.startswith("low") or s == "p3":
		return "Low"
	try:  # numeric score 0-100
		n = float(s)
		return "Critical" if n >= 80 else "High" if n >= 60 else "Medium" if n >= 30 else "Low"
	except ValueError:
		return "Unrated"


def _demand(row):
	total = _amount(_first(row, DEMAND_TOTAL_KEYS))
	if total:
		return total
	demand = row["_j"].get("demand")
	if isinstance(demand, dict):
		total = sum(_amount(demand.get(k)) for k in DEMAND_PART_KEYS)
		if total:
			return total
	if isinstance(demand, list):  # list of demand lines
		total = sum(_amount(d.get("amount") if isinstance(d, dict) else d) for d in demand)
		if total:
			return total
	versions = row["_j"].get("demand_versions")
	if isinstance(versions, list) and versions and isinstance(versions[-1], dict):
		return _amount(versions[-1].get("total") or versions[-1].get("amount"))
	return 0.0


def _resolved_on(row):
	"""Date the notice was resolved, or None while it is still open."""
	events = row["_j"].get("lifecycle_events")
	if isinstance(events, list):
		for ev in reversed(events):
			if not isinstance(ev, dict):
				continue
			text = " ".join(str(ev.get(k) or "") for k in ("event", "type", "status", "name")).lower()
			if any(w in text for w in RESOLVED_WORDS):
				return _date(ev.get("at") or ev.get("date") or ev.get("on")) or getdate(row["modified"])
	status = str(_first(row, STATUS_KEYS) or "").lower()
	if any(w in status for w in RESOLVED_WORDS):
		return getdate(row["modified"])
	if RESOLVED_ON_SUBMIT and row.get("docstatus") == 1:
		return getdate(row["modified"])
	return None


def _prepare(row, gstin_states):
	row["_j"] = {f: (_json(row.get(f)) or {}) for f in JSON_FIELDS}
	gstin = (row.get("gstin") or "").strip().upper()
	state = _first(row, STATE_KEYS)
	if not state and gstin:
		state = gstin_states.get(gstin) or GST_STATES.get(gstin[:2])
	return {
		"id": row["name"],
		"businessId": row.get("business_id"),
		"gstin": gstin or None,
		"noticeType": _first(row, NOTICE_TYPE_KEYS),
		"received": _date(_first(row, ISSUE_DATE_KEYS)) or getdate(row["creation"]),
		"due": _date(_first(row, DUE_DATE_KEYS)),
		"risk": _risk(_first(row, RISK_KEYS)),
		"demand": _demand(row),
		"state": state or "Unknown",
		"resolvedOn": _resolved_on(row),
		"proceedingStage": row.get("proceeding_stage"),
	}


# ---------------------------------------------------------------------------
# Aggregation (pure Python; no database access below this line)
# ---------------------------------------------------------------------------
def _month_key(d):
	return f"{d.year:04d}-{d.month:02d}"


def _month_starts(today, months):
	y, m = today.year, today.month
	out = []
	for _i in range(months):
		out.append(date(y, m, 1))
		m -= 1
		if m == 0:
			y, m = y - 1, 12
	return list(reversed(out))


def _active_at(n, day):
	return n["received"] <= day and (n["resolvedOn"] is None or n["resolvedOn"] > day)


def _kpis_at(notices, day):
	active = [n for n in notices if _active_at(n, day)]
	return {
		"activeNotices": len(active),
		"criticalRisk": sum(1 for n in active if n["risk"] == "Critical"),
		"overdueResponses": sum(1 for n in active if n["due"] and n["due"] < day),
		"dueIn7Days": sum(1 for n in active if n["due"] and day <= n["due"] <= day + timedelta(days=7)),
		"totalExposure": round(sum(n["demand"] for n in active), 2),
	}


def _change(now, before):
	if not before:
		return None  # no base to compare with
	return round((now - before) * 100.0 / before, 1)


def build_command_hub(notices, today, months=12, priority_limit=5, businesses=None):
	businesses = businesses or {}
	last_month_end = date(today.year, today.month, 1) - timedelta(days=1)
	now_k, prev_k = _kpis_at(notices, today), _kpis_at(notices, last_month_end)

	def card(key):
		return {"value": now_k[key], "lastMonth": prev_k[key], "changePct": _change(now_k[key], prev_k[key])}

	active = [n for n in notices if _active_at(n, today)]
	resolved = [n for n in notices if n["resolvedOn"] and n["resolvedOn"] <= today]
	starts = _month_starts(today, months)
	window_start = starts[0]

	# Monthly series
	by_month = {_month_key(s): {"received": 0, "resolved": 0, "exposure": 0.0} for s in starts}
	for n in notices:
		k = _month_key(n["received"])
		if k in by_month:
			by_month[k]["received"] += 1
			by_month[k]["exposure"] += n["demand"]
		if n["resolvedOn"]:
			k = _month_key(n["resolvedOn"])
			if k in by_month:
				by_month[k]["resolved"] += 1
	labels = [s.strftime("%b %Y") for s in starts]
	keys = [_month_key(s) for s in starts]
	received = [by_month[k]["received"] for k in keys]
	resolved_series = [by_month[k]["resolved"] for k in keys]
	peak_i = max(range(len(keys)), key=lambda i: received[i]) if any(received) else None

	# Risk distribution (active notices)
	risk_counts = {lvl: 0 for lvl in RISK_LEVELS}
	for n in active:
		risk_counts[n["risk"]] += 1
	total_active = len(active)

	# State-wise heat (active notices)
	states = {}
	for n in active:
		s = states.setdefault(n["state"], {"state": n["state"], "notices": 0, "demand": 0.0})
		s["notices"] += 1
		s["demand"] += n["demand"]
	state_rows = sorted(states.values(), key=lambda s: (-s["notices"], -s["demand"], s["state"]))
	for s in state_rows:
		s["demand"] = round(s["demand"], 2)

	# Active notices table: overdue first, then risk, then nearest due date, then biggest demand
	def priority(n):
		overdue = 0 if (n["due"] and n["due"] < today) else 1
		return (overdue, RISK_RANK[n["risk"]], n["due"] or date.max, -n["demand"])

	ordered = sorted(active, key=priority)
	limit = len(ordered) if priority_limit <= 0 else priority_limit

	def table_row(n):
		days_left = (n["due"] - today).days if n["due"] else None
		status = ("Overdue" if days_left is not None and days_left < 0
		          else "Due in 7 days" if days_left is not None and days_left <= 7 else "Open")
		return {
			"id": n["id"], "businessId": n["businessId"], "businessName": businesses.get(n["businessId"]),
			"gstin": n["gstin"], "noticeType": n["noticeType"], "risk": n["risk"],
			"demand": round(n["demand"], 2), "dueDate": n["due"].isoformat() if n["due"] else None,
			"daysLeft": days_left, "status": status, "state": n["state"],
			"proceedingStage": n["proceedingStage"], "receivedOn": n["received"].isoformat(),
		}

	in_window_received = sum(received)
	in_window_resolved = sum(resolved_series)
	return {
		"asOf": today.isoformat(),
		"comparedWith": last_month_end.isoformat(),
		"kpis": {k: card(k) for k in ("activeNotices", "criticalRisk", "overdueResponses", "dueIn7Days")},
		"exposure": {
			"total": now_k["totalExposure"], "lastMonth": prev_k["totalExposure"],
			"changePct": _change(now_k["totalExposure"], prev_k["totalExposure"]),
			"byMonth": [{"month": labels[i], "key": keys[i], "amount": round(by_month[keys[i]]["exposure"], 2)}
			            for i in range(len(keys))],
		},
		"resolved": {
			"total": len(resolved),
			"thisMonth": sum(1 for n in resolved if n["resolvedOn"] >= date(today.year, today.month, 1)),
			"inPeriod": in_window_resolved,
		},
		"intake": {
			"months": labels, "keys": keys, "received": received, "resolved": resolved_series,
			"totalReceived": in_window_received, "totalResolved": in_window_resolved,
			"averageResolveRate": round(in_window_resolved * 100.0 / in_window_received, 1) if in_window_received else None,
			"peakMonth": {"month": labels[peak_i], "key": keys[peak_i], "received": received[peak_i]} if peak_i is not None else None,
		},
		"riskDistribution": {
			"total": total_active,
			"levels": [{"level": lvl, "count": risk_counts[lvl],
			            "percent": round(risk_counts[lvl] * 100.0 / total_active, 1) if total_active else 0}
			           for lvl in RISK_LEVELS],
		},
		"stateHeat": {"top": state_rows[:8], "totalStates": len(state_rows)},
		"activeNotices": {
			"rows": [table_row(n) for n in ordered[:limit]],
			"otherCount": max(len(ordered) - limit, 0),
			"total": len(ordered),
		},
		"dataQuality": {  # active notices missing a value the cards depend on
			"withoutDueDate": sum(1 for n in active if not n["due"]),
			"withoutRisk": risk_counts["Unrated"],
			"withoutDemand": sum(1 for n in active if not n["demand"]),
			"withoutState": sum(1 for n in active if n["state"] == "Unknown"),
		},
		"_windowStart": window_start.isoformat(),
	}


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------
def _resolve_business(key):
	key = str(key).strip()
	if frappe.db.exists("Business", key):
		return key
	alt = frappe.db.get_value("Business", {"short_name": key.upper()}, "name")
	if alt:
		return str(alt)
	frappe.throw(_("Client {0} not found").format(key), frappe.DoesNotExistError)


@frappe.whitelist(methods=["GET"])
def get_command_hub(client_key=None, gstin=None, months=12, priority_limit=5, as_of=None):
	"""All Command Hub metrics. See the module docstring for parameters."""
	if not frappe.has_permission("Notice", "read"):
		frappe.throw(_("Not permitted to read notices"), frappe.PermissionError)

	today = getdate(as_of) if as_of else getdate(nowdate())
	months = min(max(cint(months) or 12, 1), 36)
	meta = frappe.get_meta("Notice")
	json_fields = [f for f in JSON_FIELDS if meta.get_field(f)]
	fields = ["name", "business_id", "gstin", "proceeding_stage", "docstatus", "creation", "modified"] + json_fields

	filters = [["docstatus", "!=", 2]]  # cancelled notices are left out
	or_filters = None
	if client_key:
		business_id = _resolve_business(client_key)
		gstins = frappe.get_all("GSTIN", filters={"business_id": business_id}, pluck="name")
		or_filters = [["business_id", "=", business_id]] + ([["gstin", "in", gstins]] if gstins else [])
	if gstin:
		filters.append(["gstin", "=", str(gstin).strip().upper()])

	rows = frappe.get_all("Notice", filters=filters, or_filters=or_filters, fields=fields,
	                      limit_page_length=0, order_by="creation asc")

	gstin_states = {g.name: g.state for g in frappe.get_all("GSTIN", fields=["name", "state"], limit_page_length=0) if g.state}
	notices = [_prepare(dict(r), gstin_states) for r in rows]
	notices = [n for n in notices if n["received"] <= today]

	business_ids = {n["businessId"] for n in notices if n["businessId"]}
	businesses = {}
	if business_ids:
		businesses = {str(b.name): b.business_name for b in frappe.get_all(
			"Business", filters={"name": ["in", list(business_ids)]}, fields=["name", "business_name"])}

	result = build_command_hub(notices, today, months, cint(priority_limit), businesses)
	result.pop("_windowStart", None)
	return result
