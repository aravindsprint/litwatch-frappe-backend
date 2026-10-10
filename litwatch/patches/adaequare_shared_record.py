import frappe

SHARED_NAME = "LitWatch GSP"


def execute():
	"""One shared GSP app for all GSTINs, named "LitWatch GSP".
	The active record created first becomes the shared one; any others stay as
	GSTIN-specific exceptions (named by their Default GSTIN)."""
	if frappe.db.exists("Adaequare Settings", SHARED_NAME):
		frappe.db.set_value("Adaequare Settings", SHARED_NAME, "is_shared", 1, update_modified=False)
		return
	name = frappe.db.get_value("Adaequare Settings", {"is_active": 1}, "name", order_by="creation asc")
	if not name:
		return
	frappe.db.set_value("Adaequare Settings", name, "is_shared", 1, update_modified=False)
	frappe.rename_doc("Adaequare Settings", name, SHARED_NAME, force=True)
	frappe.db.commit()
	print(f"Adaequare Settings {name} is now the shared record \"{SHARED_NAME}\"")
