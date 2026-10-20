# Run: bench --site <site> run-tests --module litwatch.tests.test_ai_proxy
# The AI Layer is mocked: no service on port 8001 is needed.

from unittest.mock import MagicMock, patch

import frappe
import requests
from frappe.tests.utils import FrappeTestCase

from litwatch import scope
from litwatch.api import ai


def fake(status=200, json_body=None, text="", ctype="application/json", content=b"", headers=None):
	r = MagicMock()
	r.status_code = status
	r.headers = {"Content-Type": ctype, **(headers or {})}
	r.json.side_effect = (lambda: json_body) if json_body is not None else ValueError
	r.text = text
	r.content = content or (text.encode() if text else b"{}")
	return r


class TestAIProxy(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		frappe.local.form_dict = frappe._dict()
		frappe.local.response = frappe._dict()
		scope.reset_cache()

	@patch("litwatch.api.ai.requests.request")
	def test_post_json(self, req):
		req.return_value = fake(json_body={"summary": "ok", "risk": "high"})
		res = ai.proxy(path="/analyze/notice", method="post", payload={"noticeId": "DRC-1"}, query={"lang": "en"})
		self.assertEqual({"summary": "ok", "risk": "high"}, res)
		args, kwargs = req.call_args
		self.assertEqual(("POST", "http://127.0.0.1:8001/analyze/notice"), args)
		self.assertEqual({"noticeId": "DRC-1"}, kwargs["json"])
		self.assertEqual({"lang": "en"}, kwargs["params"])
		self.assertEqual("Administrator", kwargs["headers"]["X-Frappe-User"])

	@patch("litwatch.api.ai.requests.request")
	def test_get_sends_payload_as_query(self, req):
		req.return_value = fake(json_body=[1, 2])
		self.assertEqual([1, 2], ai.proxy(path="chat/history", method="GET", payload='{"limit": 5}'))
		kwargs = req.call_args.kwargs
		self.assertEqual({"limit": 5}, kwargs["params"])
		self.assertIsNone(kwargs["json"])

	def test_bad_paths(self):
		for bad in ("", "http://evil/x", "../etc/passwd", "a/../../b", "a?x=1", "a b"):
			with self.assertRaises(frappe.ValidationError):
				ai.proxy(path=bad)
		with self.assertRaises(frappe.ValidationError):
			ai.proxy(path="x", method="TRACE")

	@patch("litwatch.api.ai.requests.request")
	def test_errors_pass_status(self, req):
		req.return_value = fake(status=422, json_body={"detail": "noticeId is required"})
		with self.assertRaises(ai.AIError) as e:
			ai.proxy(path="analyze/notice", payload={})
		self.assertEqual(422, e.exception.http_status_code)

		req.side_effect = requests.ConnectionError("refused")
		with self.assertRaises(ai.AIError) as e:
			ai.proxy(path="analyze/notice", payload={})
		self.assertEqual(502, e.exception.http_status_code)

		req.side_effect = requests.Timeout()
		with self.assertRaises(ai.AIError) as e:
			ai.proxy(path="analyze/notice", payload={})
		self.assertEqual(504, e.exception.http_status_code)

	@patch("litwatch.api.ai.requests.request")
	def test_text_and_file(self, req):
		req.return_value = fake(text="plain answer", ctype="text/plain")
		self.assertEqual({"text": "plain answer"}, ai.proxy(path="draft/reply", payload={}))

		req.return_value = fake(ctype="application/pdf", content=b"%PDF-1.4",
		                        headers={"Content-Disposition": 'attachment; filename="reply.pdf"'})
		ai.proxy(path="draft/reply.pdf", payload={})
		self.assertEqual(("download", "reply.pdf", b"%PDF-1.4"),
		                 (frappe.local.response.type, frappe.local.response.filename, frappe.local.response.filecontent))

	@patch("litwatch.api.ai.requests.request")
	def test_allowed_paths_and_secret(self, req):
		req.return_value = fake(json_body={})
		with patch.dict(frappe.conf, {"ai_layer_allowed_paths": ["analyze/"], "ai_layer_secret": "s3cret",
		                              "ai_layer_url": "http://ai.internal:9000/"}):
			ai.proxy(path="analyze/notice", payload={})
			self.assertEqual("http://ai.internal:9000/analyze/notice", req.call_args.args[1])
			self.assertEqual("s3cret", req.call_args.kwargs["headers"]["X-AI-Layer-Secret"])
			with self.assertRaises(frappe.PermissionError):
				ai.proxy(path="admin/reset", payload={})

	def test_guest_refused(self):
		frappe.set_user("Guest")
		try:
			with self.assertRaises(frappe.AuthenticationError):
				ai.proxy(path="analyze/notice")
		finally:
			frappe.set_user("Administrator")
