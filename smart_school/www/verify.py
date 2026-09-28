import frappe

from smart_school.branding import get_school_branding
from smart_school.verification import get_verification_view, within_rate_limit

no_cache = 1


def get_context(context):
	"""Public (no login): is this report card genuine? Only what the report card itself showed."""
	context.no_cache = 1
	context.school = get_school_branding()
	if not within_rate_limit():
		context.http_status_code = 429
		context.view = frappe._dict(status="limited")
		return context
	context.view = get_verification_view(frappe.form_dict.get("token"))
	if context.view.status == "invalid":
		context.http_status_code = 404
	return context
