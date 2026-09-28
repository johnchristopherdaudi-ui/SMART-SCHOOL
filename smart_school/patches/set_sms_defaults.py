import frappe

SETTINGS = "Smart School Settings"


def execute():
	"""SMS settings start Off, with the agreed price and limits, and the Swahili templates. Guardians who were
	there before keep sms_opt_in = 0: nobody gets an SMS until they (or the school, from a paper form) agree."""
	from smart_school.sms import DEFAULT_TEMPLATES, DEFAULTS

	defaults = {**DEFAULTS, "sms_fee_reminder_before_term": 0, "sms_fee_reminder_overdue": 0}
	for fieldname, value in defaults.items():
		if is_unset(fieldname):
			frappe.db.set_single_value(SETTINGS, fieldname, value)
	frappe.clear_document_cache(SETTINGS, SETTINGS)

	for template_type, message in DEFAULT_TEMPLATES.items():
		if not frappe.db.exists("SMS Template", template_type):
			frappe.get_doc(
				{"doctype": "SMS Template", "template_type": template_type, "message": message, "enabled": 1}
			).insert(ignore_permissions=True)


def is_unset(fieldname):
	# get_single_value casts a missing number to 0, so ask tabSingles itself
	return not frappe.db.sql(
		"select 1 from `tabSingles` where doctype = %s and field = %s and ifnull(value, '') != ''",
		(SETTINGS, fieldname),
	)
