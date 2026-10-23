import frappe

CONSULTANTS = ("pcp@gmail.com",)


def execute():
	"""GST User gets User Type. Everyone starts as Individual; pcp@gmail.com is a Consultant."""
	frappe.reload_doc("litwatch", "doctype", "gst_user")
	frappe.db.sql("UPDATE `tabGST User` SET user_type = 'Individual' WHERE IFNULL(user_type, '') = ''")
	for email in CONSULTANTS:
		if frappe.db.exists("GST User", email):
			frappe.db.set_value("GST User", email, "user_type", "Consultant", update_modified=False)
