import frappe


def execute():
	"""GST User.user_email_id is now a Link to User. Create a User for every GST User
	whose email has no User yet, so the links are valid. New users are Website Users
	with no password and no welcome email: they can't log in until a password is set."""
	for row in frappe.get_all("GST User", fields=["name", "user_email_id", "user_name"], limit_page_length=0):
		email = (row.user_email_id or row.name or "").strip().lower()
		if not email or frappe.db.exists("User", email) or frappe.db.exists("User", {"email": email}):
			continue
		if "@" not in email:
			print(f"GST User {row.name}: '{email}' is not an email address - fix it by hand")
			continue
		user = frappe.get_doc({
			"doctype": "User",
			"email": email,
			"first_name": row.user_name or email.split("@")[0],
			"user_type": "Website User",
			"send_welcome_email": 0,
			"enabled": 1,
		})
		user.flags.ignore_permissions = True
		user.flags.no_welcome_mail = True
		user.insert()
		print(f"Created User {email} for GST User {row.name}")
	frappe.db.commit()
