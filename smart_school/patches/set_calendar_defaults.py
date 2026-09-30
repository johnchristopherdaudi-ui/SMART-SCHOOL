import frappe

from smart_school.patches.set_sms_defaults import SETTINGS, is_unset

DEFAULTS = {"saturday_is_school_day": 0, "attendance_completeness_min": 80, "leave_days_back": 7}


def execute():
	"""Calendar and leave settings start at their defaults (a single doctype does not get them on an existing site)."""
	for fieldname, value in DEFAULTS.items():
		if is_unset(fieldname):
			frappe.db.set_single_value(SETTINGS, fieldname, value)
	frappe.clear_document_cache(SETTINGS, SETTINGS)
