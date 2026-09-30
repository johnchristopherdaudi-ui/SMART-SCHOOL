import frappe
from frappe.utils import add_days, formatdate, today

from smart_school.leave import MAX_REASON, days_back, portal_requests
from smart_school.portal_utils import get_children, get_notifications, get_portal_guardian

STATUS = {
	"Pending": ("Inasubiri uamuzi", "pending"),
	"Approved": ("Imeidhinishwa", "approved"),
	"Rejected": ("Haikuidhinishwa", "rejected"),
	"Cancelled": ("Imefutwa", "cancelled"),
}


def get_context(context):
	"""Ruhusa: a parent asks leave for their children and follows the answers."""
	guardian = get_portal_guardian()
	children = get_children(guardian)
	context.children = [c for c in children if c.status == "Active"]
	context.earliest = add_days(today(), -days_back())
	context.today = today()
	context.days_back = days_back()
	context.max_reason = MAX_REASON
	requests = []
	for r in portal_requests(guardian):
		label, css = STATUS.get(r.status, (r.status, "pending"))
		requests.append(
			frappe._dict(
				name=r.name,
				student_name=r.student_name,
				when=formatdate(r.from_date, "dd-MM-yyyy")
				+ ("" if r.from_date == r.to_date else " hadi " + formatdate(r.to_date, "dd-MM-yyyy")),
				school_days=r.school_days,
				reason=r.reason,
				status=r.status,
				status_label=label,
				status_css=css,
				decision_note=r.decision_note,
				has_attachment=bool(r.attachment),
			)
		)
	context.requests = requests
	notif = get_notifications(guardian, children)
	context.notifications = notif["items"]
	context.unseen_count = notif["unseen_count"]
	context.no_cache = 1
