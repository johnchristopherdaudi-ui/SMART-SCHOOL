import frappe


def execute():
	"""Single doctypes do not get field defaults on an existing site."""
	if not frappe.db.get_single_value("Smart School Settings", "intervention_min_sample"):
		frappe.db.set_single_value("Smart School Settings", "intervention_min_sample", 20)
