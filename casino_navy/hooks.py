from . import __version__ as app_version

app_name = "casino_navy"
app_title = "Casino Navy"
app_publisher = "Lewin Villar"
app_description = "A custom App for Casino Navy"
app_email = "lewin.villar@tzcode.tech"
app_license = "MIT"

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/casino_navy/css/casino_navy.css"
# app_include_js = "/assets/casino_navy/js/casino_navy.js"

# include js, css files in header of web template
# web_include_css = "/assets/casino_navy/css/casino_navy.css"
# web_include_js = "/assets/casino_navy/js/casino_navy.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "casino_navy/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views
doctype_js = {
    "Data Import" : "public/js/data_import.js",
    "Journal Entry" : "public/js/journal_entry.js",
    "User" : "public/js/user.js",
    "Payment Entry" : "public/js/payment_entry.js",
    "Journal Entry" : "public/js/journal_entry.js",
    "Bank Account" : "public/js/bank_account.js",
}
# doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
# role_home_page = {
#	"Role": "home_page"
# }

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# Jinja
# ----------

# add methods and filters to jinja environment
# jinja = {
#	"methods": "casino_navy.utils.jinja_methods",
#	"filters": "casino_navy.utils.jinja_filters"
# }

# Installation
# ------------

# before_install = "casino_navy.install.before_install"
# after_install = "casino_navy.install.after_install"

# Uninstallation
# ------------

# before_uninstall = "casino_navy.uninstall.before_uninstall"
# after_uninstall = "casino_navy.uninstall.after_uninstall"

# Integration Setup
# ------------------
# To set up dependencies/integrations with other apps
# Name of the app being installed is passed as an argument

# before_app_install = "casino_navy.utils.before_app_install"
# after_app_install = "casino_navy.utils.after_app_install"

# Integration Cleanup
# -------------------
# To clean up dependencies/integrations with other apps
# Name of the app being uninstalled is passed as an argument

# before_app_uninstall = "casino_navy.utils.before_app_uninstall"
# after_app_uninstall = "casino_navy.utils.after_app_uninstall"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "casino_navy.notifications.get_notification_config"

# Permissions
# -----------
# Permissions evaluated in scripted ways

# permission_query_conditions = {
#	"Event": "frappe.desk.doctype.event.event.get_permission_query_conditions",
# }
#
# has_permission = {
#	"Event": "frappe.desk.doctype.event.event.has_permission",
# }

# Fixtures
# ---------------
fixtures = [
	{
		"doctype": "Custom Field",
		"filters": {
			"module": "Casino Navy"
        }
    },
    {
		"doctype": "Property Setter",
		"filters": {
			"module": "Casino Navy"
        }
    },
]

# DocType Class
# ---------------
# Override standard doctype classes

override_doctype_class = {
	"Journal Entry": "casino_navy.casino_navy.controllers.journal_entry.JournalEntry"
}

# Document Events
# ---------------
# Hook on document methods and events

# doc_events = {
#	"*": {
#		"on_update": "method",
#		"on_cancel": "method",
#		"on_trash": "method"
#	}
# }

# Scheduled Tasks
# ---------------

scheduler_events = {
#	"all": [
#		"casino_navy.tasks.all"
#	],
#	"daily": [
#		"casino_navy.tasks.daily"
#	],
#	"hourly": [
#		"casino_navy.tasks.hourly"
#	],
	"weekly": [
		"casino_navy.utils.move_luqapay_balance"
	],
#	"monthly": [
#		"casino_navy.tasks.monthly"
#	],
}

# Testing
# -------

# before_tests = "casino_navy.install.before_tests"

# Overriding Methods
# ------------------------------
#
# override_whitelisted_methods = {
#	"frappe.desk.doctype.event.event.get_events": "casino_navy.event.get_events"
# }
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
#	"Task": "casino_navy.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

# Request Events
# ----------------
# before_request = ["casino_navy.utils.before_request"]
# after_request = ["casino_navy.utils.after_request"]

# Job Events
# ----------
# before_job = ["casino_navy.utils.before_job"]
# after_job = ["casino_navy.utils.after_job"]

# User Data Protection
# --------------------

# user_data_fields = [
#	{
#		"doctype": "{doctype_1}",
#		"filter_by": "{filter_by}",
#		"redact_fields": ["{field_1}", "{field_2}"],
#		"partial": 1,
#	},
#	{
#		"doctype": "{doctype_2}",
#		"filter_by": "{filter_by}",
#		"partial": 1,
#	},
#	{
#		"doctype": "{doctype_3}",
#		"strict": False,
#	},
#	{
#		"doctype": "{doctype_4}"
#	}
# ]

# Authentication and authorization
# --------------------------------

# auth_hooks = [
#	"casino_navy.auth.validate"
# ]
