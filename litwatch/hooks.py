app_name = "litwatch"
app_title = "Litwatch"
app_publisher = "Shahina"
app_description = "Custom app for CA"
app_email = "shahinak1992@gmail.com"
app_license = "mit"

# Apps
# ------------------

# required_apps = []

# Each item in the list will be shown as an app in the apps page
# add_to_apps_screen = [
# 	{
# 		"name": "litwatch",
# 		"logo": "/assets/litwatch/logo.png",
# 		"title": "Litwatch",
# 		"route": "/litwatch",
# 		"has_permission": "litwatch.api.permission.has_app_permission"
# 	}
# ]

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/litwatch/css/litwatch.css"
# app_include_js = "/assets/litwatch/js/litwatch.js"

# include js, css files in header of web template
# web_include_css = "/assets/litwatch/css/litwatch.css"
# web_include_js = "/assets/litwatch/js/litwatch.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "litwatch/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views
# doctype_js = {"doctype" : "public/js/doctype.js"}
# doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

# Svg Icons
# ------------------
# include app icons in desk
# app_include_icons = "litwatch/public/icons.svg"

# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
# role_home_page = {
# 	"Role": "home_page"
# }

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# Jinja
# ----------

# add methods and filters to jinja environment
# jinja = {
# 	"methods": "litwatch.utils.jinja_methods",
# 	"filters": "litwatch.utils.jinja_filters"
# }

# Installation
# ------------

# before_install = "litwatch.install.before_install"
# after_install = "litwatch.install.after_install"

# Uninstallation
# ------------

# before_uninstall = "litwatch.uninstall.before_uninstall"
# after_uninstall = "litwatch.uninstall.after_uninstall"

# Integration Setup
# ------------------
# To set up dependencies/integrations with other apps
# Name of the app being installed is passed as an argument

# before_app_install = "litwatch.utils.before_app_install"
# after_app_install = "litwatch.utils.after_app_install"

# Integration Cleanup
# -------------------
# To clean up dependencies/integrations with other apps
# Name of the app being uninstalled is passed as an argument

# before_app_uninstall = "litwatch.utils.before_app_uninstall"
# after_app_uninstall = "litwatch.utils.after_app_uninstall"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "litwatch.notifications.get_notification_config"

# Awesome Bar
# -----------
# Extra search results: list of dicts with label, description, route, index.
# route: ["List", "ToDo"], "/desk/docs/some/page", or "https://example.com"
# awesomebar_search = ["litwatch.search.awesomebar_results"]

# Permissions
# -----------
# Permissions evaluated in scripted ways

# permission_query_conditions = {
# 	"Event": "frappe.desk.doctype.event.event.get_permission_query_conditions",
# }
#
# has_permission = {
# 	"Event": "frappe.desk.doctype.event.event.has_permission",
# }

# DocType Class
# ---------------
# Override standard doctype classes

# override_doctype_class = {
# 	"ToDo": "custom_app.overrides.CustomToDo"
# }

# Document Events
# ---------------
# Hook on document methods and events

# doc_events = {
# 	"*": {
# 		"on_update": "method",
# 		"on_cancel": "method",
# 		"on_trash": "method"
# 	}
# }

# Scheduled Tasks
# ---------------

# scheduler_events = {
# 	"all": [
# 		"litwatch.tasks.all"
# 	],
# 	"daily": [
# 		"litwatch.tasks.daily"
# 	],
# 	"hourly": [
# 		"litwatch.tasks.hourly"
# 	],
# 	"weekly": [
# 		"litwatch.tasks.weekly"
# 	],
# 	"monthly": [
# 		"litwatch.tasks.monthly"
# 	],
# }

# Testing
# -------

# before_tests = "litwatch.install.before_tests"

# Overriding Methods
# ------------------------------
#
# override_whitelisted_methods = {
# 	"frappe.desk.doctype.event.event.get_events": "litwatch.event.get_events"
# }
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Task": "litwatch.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

# Request Events
# ----------------
# before_request = ["litwatch.utils.before_request"]
# after_request = ["litwatch.utils.after_request"]

# Job Events
# ----------
# before_job = ["litwatch.utils.before_job"]
# after_job = ["litwatch.utils.after_job"]

# User Data Protection
# --------------------

# user_data_fields = [
# 	{
# 		"doctype": "{doctype_1}",
# 		"filter_by": "{filter_by}",
# 		"redact_fields": ["{field_1}", "{field_2}"],
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_2}",
# 		"filter_by": "{filter_by}",
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_3}",
# 		"strict": False,
# 	},
# 	{
# 		"doctype": "{doctype_4}"
# 	}
# ]

# Authentication and authorization
# --------------------------------

# auth_hooks = [
# 	"litwatch.auth.validate"
# ]

# Automatically update python controller files with type annotations for this app.
# export_python_type_annotations = True

# default_log_clearing_doctypes = {
# 	"Logging DocType Name": 30  # days to retain logs
# }

# Translation
# ------------
# List of apps whose translatable strings should be excluded from this app's translations.
# ignore_translatable_strings_from = []


# ---------------------------------------------------------------------------
# Per-user scoping (litwatch/scope.py): lists are filtered to the GST User's
# Businesses. Single records are also checked in each controller's
# has_permission, which covers Administrator / the shared API key.
# ---------------------------------------------------------------------------
permission_query_conditions = {
	"Business": "litwatch.scope.business_query",
	"GSTIN": "litwatch.scope.gstin_query",
	"Notice": "litwatch.scope.notice_query",
	"Payment": "litwatch.scope.payment_query",
	"Review Queue Item": "litwatch.scope.review_queue_item_query",
	"Client Document": "litwatch.scope.client_document_query",
	"Audit Log": "litwatch.scope.audit_log_query",
	"GST User": "litwatch.scope.gst_user_query",
	"GST Sync Log": "litwatch.scope.gst_sync_log_query",
	"GST OTP Request": "litwatch.scope.gst_otp_request_query",
	"Adaequare Settings": "litwatch.scope.adaequare_settings_query",
}

has_permission = {
	"Business": "litwatch.scope.has_permission",
	"GSTIN": "litwatch.scope.has_permission",
	"Notice": "litwatch.scope.has_permission",
	"Payment": "litwatch.scope.has_permission",
	"Review Queue Item": "litwatch.scope.has_permission",
	"Client Document": "litwatch.scope.has_permission",
	"Audit Log": "litwatch.scope.has_permission",
	"GST User": "litwatch.scope.has_permission",
	"Adaequare Settings": "litwatch.scope.has_permission",
}

# ---------------------------------------------------------------------------
# App Notifications (litwatch/notification_events.py, litwatch/notification_jobs.py)
# ---------------------------------------------------------------------------
doc_events = {
	"Notice": {
		"after_insert": "litwatch.notification_events.notice_after_insert",
		"on_update": "litwatch.notification_events.notice_on_update",
	},
	"Review Queue Item": {"on_update": "litwatch.notification_events.review_item_on_update"},
	"Payment": {"after_insert": "litwatch.notification_events.payment_after_insert"},
	"Client Document": {
		"after_insert": "litwatch.notification_events.client_document_after_insert",
		"on_update": "litwatch.notification_events.client_document_on_update",
	},
	"Business": {
		"after_insert": "litwatch.notification_events.business_after_insert",
		"on_update": "litwatch.notification_events.business_on_update",
	},
	"GSTIN": {"on_update": "litwatch.notification_events.gstin_on_update"},
	"GST User": {
		"after_insert": "litwatch.notification_events.gst_user_after_insert",
		"on_update": "litwatch.notification_events.gst_user_on_update",
	},
	"Firm Profile": {
		"on_update": "litwatch.notification_events.firm_profile_on_update",
		"after_rename": "litwatch.notification_events.firm_profile_after_rename",
	},
}

scheduler_events = {
	"cron": {
		# 08:30 every day (system time zone): deadlines, consent expiry, morning digest
		"30 8 * * *": ["litwatch.notification_jobs.run_daily"],
	},
}
