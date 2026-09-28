import frappe


def execute():
	"""The early-warning model's levels get their own thresholds, starting from the rule score's defaults."""
	settings = frappe.get_single("Smart School Settings")
	settings.model_medium_threshold = settings.model_medium_threshold or 30
	settings.model_high_threshold = settings.model_high_threshold or 60
	settings.save(ignore_permissions=True)
