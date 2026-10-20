# apps/litwatch/litwatch/api/ai.py
"""
Proxy from Frappe to the LitWatch AI Layer (a separate service, default http://127.0.0.1:8001).

The frontend calls one Frappe method with the AI Layer's subroute, the HTTP method and the
payload; Frappe checks the caller (API key / session, per-user scoping), forwards the request
and returns the AI Layer's answer. Port 8001 never has to be exposed to the internet.

    POST /api/method/litwatch.api.ai.proxy
    {
      "path": "analyze/notice",          # AI Layer subroute (no scheme, no "..")
      "method": "POST",                  # GET, POST, PUT, PATCH or DELETE (default POST)
      "payload": {"noticeId": "DRC-2026-00001"},   # JSON body; for GET/DELETE sent as query params
      "query": {"lang": "en"}            # optional extra query params
    }

Response: the AI Layer's JSON as "message" (HTTP status passed through), its text as
{"text": ...}, or a file (PDF, image) as a download.

Forwarded headers: X-Frappe-User (session user), X-LitWatch-GST-User and X-LitWatch-Businesses
(when the request is scoped to a GST User, see litwatch/scope.py), X-Request-Id, and
X-AI-Layer-Secret when ai_layer_secret is set, so the AI Layer can trust the call.

site_config.json (all optional):
    "ai_layer_url": "http://127.0.0.1:8001",
    "ai_layer_timeout": 120,                     # seconds
    "ai_layer_secret": "<shared secret>",
    "ai_layer_allowed_paths": ["analyze/", "draft/", "chat/"]   # prefixes; empty = any path
"""

import json
import re

import frappe
import requests
from frappe import _

from litwatch import scope

METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE")
DEFAULT_URL = "http://127.0.0.1:8001"
DEFAULT_TIMEOUT = 120
_PATH_RE = re.compile(r"^[A-Za-z0-9._~\-/]*$")


class AIError(frappe.ValidationError):
	"""Raised with the HTTP status to return (AI Layer's own 4xx/5xx, 502 unreachable, 504 timeout)."""

	http_status_code = 502


def _fail(message, status, title):
	frappe.msgprint(message, title=title, indicator="red")
	err = AIError(message)
	err.http_status_code = status
	raise err


def _conf(key, default=None):
	value = frappe.conf.get(key)
	return default if value in (None, "") else value


def _clean_path(path):
	"""AI Layer subroute: relative, no scheme, no '..', only URL-safe path characters."""
	path = str(path or "").strip()
	if "?" in path:
		frappe.throw(_("Put query parameters in query, not in path"))
	path = path.lstrip("/")
	if not path or "://" in path or "\\" in path or not _PATH_RE.match(path):
		frappe.throw(_("Invalid AI path: {0}").format(path or "-"))
	if any(part in ("..", ".") for part in path.split("/")):
		frappe.throw(_("Invalid AI path: {0}").format(path))
	allowed = _conf("ai_layer_allowed_paths") or []
	if allowed and not any(path.startswith(str(p).lstrip("/")) for p in allowed):
		frappe.throw(_("AI path {0} is not allowed").format(path), frappe.PermissionError)
	return path


def _json_arg(value, name):
	if value in (None, ""):
		return None
	if isinstance(value, (dict, list)):
		return value
	try:
		return json.loads(value)
	except (TypeError, ValueError):
		frappe.throw(_("{0} must be JSON").format(name))


def _request_body():
	req = getattr(frappe.local, "request", None)
	if req is not None and req.data:
		try:
			body = req.get_json(silent=True)
			if isinstance(body, dict):
				return body
		except Exception:
			pass
	return {}


def _headers():
	headers = {"Accept": "application/json, */*", "X-Frappe-User": frappe.session.user,
	           "X-Request-Id": frappe.generate_hash(length=16)}
	allowed = scope.get_scope()  # None = firm staff (everything)
	gst_user = scope.scope_user() if allowed is not None else None
	if gst_user:
		headers["X-LitWatch-GST-User"] = gst_user
		headers["X-LitWatch-Businesses"] = ",".join(allowed or [])
	secret = _conf("ai_layer_secret")
	if secret:
		headers["X-AI-Layer-Secret"] = secret
	return headers


@frappe.whitelist(methods=["GET", "POST"])
def proxy(path=None, method=None, payload=None, query=None):
	"""Forward {path, method, payload, query} to the AI Layer and return its response."""
	if frappe.session.user == "Guest":
		frappe.throw(_("Login required"), frappe.AuthenticationError)

	body = _request_body()
	path = _clean_path(path or body.get("path"))
	method = str(method or body.get("method") or "POST").strip().upper()
	if method not in METHODS:
		frappe.throw(_("method must be one of {0}").format(", ".join(METHODS)))
	payload = _json_arg(payload if payload is not None else body.get("payload"), "payload")
	query = _json_arg(query if query is not None else body.get("query"), "query") or {}
	if not isinstance(query, dict):
		frappe.throw(_("query must be a JSON object"))

	params = dict(query)
	json_body = None
	if method in ("GET", "DELETE"):
		if isinstance(payload, dict):
			params.update(payload)
		elif payload is not None:
			frappe.throw(_("For {0} the payload must be a JSON object (sent as query params)").format(method))
	else:
		json_body = payload if payload is not None else {}

	base = str(_conf("ai_layer_url", DEFAULT_URL)).rstrip("/")
	url = f"{base}/{path}"
	timeout = float(_conf("ai_layer_timeout", DEFAULT_TIMEOUT))
	try:
		resp = requests.request(method, url, params=params or None, json=json_body, headers=_headers(), timeout=timeout)
	except requests.Timeout:
		_fail(_("The AI service took longer than {0} seconds").format(int(timeout)), 504, _("AI timeout"))
	except requests.RequestException as e:
		frappe.log_error(title="LitWatch AI Layer unreachable", message=f"{method} {url}\n{e}")
		_fail(_("The AI service is not reachable right now. Try again in a moment."), 502, _("AI unavailable"))

	return _relay(resp, path)


def _relay(resp, path):
	"""Pass the AI Layer's answer back: JSON as message, text as {"text"}, anything else as a download."""
	status = resp.status_code
	ctype = (resp.headers.get("Content-Type") or "").split(";")[0].strip().lower()
	if status >= 400:
		try:
			detail = resp.json()
		except ValueError:
			detail = resp.text[:2000]
		if status >= 500:
			frappe.log_error(title=f"LitWatch AI Layer error {status}", message=f"{path}\n{detail}")
		message = (detail.get("detail") or detail.get("message") or detail.get("error")) if isinstance(detail, dict) else detail
		if not isinstance(message, str):
			message = json.dumps(message, default=str)[:2000] if message else ""
		_fail(message or _("AI service error {0}").format(status), status, _("AI error"))

	if status != 200:
		frappe.local.response.http_status_code = status
	if ctype == "application/json" or ctype.endswith("+json"):
		try:
			return resp.json()
		except ValueError:
			return {"text": resp.text}
	if ctype.startswith("text/") or not resp.content:
		return {"text": resp.text}

	disposition = resp.headers.get("Content-Disposition") or ""
	match = re.search(r'filename="?([^";]+)"?', disposition)
	frappe.local.response.filename = match.group(1) if match else (path.rsplit("/", 1)[-1] or "ai-output")
	frappe.local.response.filecontent = resp.content
	frappe.local.response.type = "download"
	frappe.local.response.display_content_as = "inline" if ctype in ("application/pdf",) or ctype.startswith("image/") else "attachment"


@frappe.whitelist(methods=["GET"])
def health():
	"""Is the AI Layer up? Calls its /health (falls back to /). For staff and monitoring."""
	base = str(_conf("ai_layer_url", DEFAULT_URL)).rstrip("/")
	for p in ("health", ""):
		try:
			r = requests.get(f"{base}/{p}", headers=_headers(), timeout=5)
			if r.status_code < 500:
				return {"reachable": True, "url": base, "status": r.status_code}
		except requests.RequestException:
			continue
	return {"reachable": False, "url": base}
