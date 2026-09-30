import frappe
from frappe.utils import getdate, today


def execute():
	"""Tanzania's national holidays on fixed dates, repeating every year (no school on them). Eid, Easter and
	Maulid move from year to year: the Headmaster adds them as School Events."""
	from smart_school.school_calendar import FIXED_HOLIDAYS

	year = getdate(today()).year
	for title, month, day in FIXED_HOLIDAYS:
		if frappe.db.exists("School Event", {"title": title, "repeat_every_year": 1}):
			continue
		frappe.get_doc(
			{
				"doctype": "School Event",
				"title": title,
				"event_type": "Public Holiday",
				"start_date": f"{year}-{month:02d}-{day:02d}",
				"is_school_day": 0,
				"repeat_every_year": 1,
				"show_on_portal": 1,
				"audience": "All School",
				"description": "Sikukuu ya kitaifa: hakuna masomo.",
			}
		).insert(ignore_permissions=True)
