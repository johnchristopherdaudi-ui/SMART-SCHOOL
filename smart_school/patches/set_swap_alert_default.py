import frappe

from smart_school.patches.set_sms_defaults import SETTINGS, is_unset


def execute():
	"""The Possibly Swapped Marks check starts at z 3.5."""
	if is_unset("alert_swap_z"):
		frappe.db.set_single_value(SETTINGS, "alert_swap_z", 3.5)
	frappe.clear_document_cache(SETTINGS, SETTINGS)
