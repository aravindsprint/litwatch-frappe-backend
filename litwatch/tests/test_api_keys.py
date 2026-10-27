# Run: bench --site <site> run-tests --module litwatch.tests.test_api_keys
import frappe
from frappe.core.doctype.user.user import generate_keys
from frappe.tests.utils import FrappeTestCase
from frappe.utils.password import get_decrypted_password

from litwatch.api.api_keys import get_api_secret, get_gsp_client_secret

A, B = "apikeys-a@example.com", "apikeys-b@example.com"


class TestApiKeys(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		for u in (A, B):
			if not frappe.db.exists("User", u):
				frappe.get_doc({"doctype": "User", "email": u, "first_name": u.split("@")[0],
				                "user_type": "Website User", "send_welcome_email": 0}).insert(ignore_permissions=True)
		generate_keys(A)

	def tearDown(self):
		frappe.set_user("Administrator")

	def test_secret_shown_again(self):
		secret = get_decrypted_password("User", A, "api_secret")
		res = get_api_secret(A)
		self.assertEqual(secret, res["api_secret"])
		self.assertEqual(frappe.db.get_value("User", A, "api_key"), res["api_key"])

	def test_only_self_or_system_manager(self):
		frappe.set_user(A)
		self.assertTrue(get_api_secret(A).get("api_secret"))  # own secret
		frappe.set_user(B)
		self.assertEqual({}, get_api_secret(A))  # someone else's: nothing
		self.assertEqual({}, get_api_secret(B))  # no keys yet

	def test_gsp_client_secret_staff_only(self):
		name = frappe.db.get_value("Adaequare Settings", {"client_secret": ["is", "set"]}, "name")
		if not name:
			self.skipTest("no Adaequare Settings with a Client Secret on this site")
		secret = get_decrypted_password("Adaequare Settings", name, "client_secret")
		self.assertEqual(secret, get_gsp_client_secret(name)["client_secret"])
		frappe.set_user(A)  # not a System Manager
		self.assertEqual({}, get_gsp_client_secret(name))
