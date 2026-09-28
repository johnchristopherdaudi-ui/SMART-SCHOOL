# Copyright (c) 2026, john daudi and contributors
# For license information, please see license.txt

import frappe
from frappe.utils import add_months, get_first_day, getdate, today

from smart_school.sms import FEE_TYPES, MANAGER_ROLES, MESSAGE_TYPES, SENT, TESTED, get_settings, usage

ROLES = (*MANAGER_ROLES, "Accountant")


def execute(filters=None):
	"""SMS per month, type and status: messages, SMS parts and cost. Sent is money spent; Test is what the same
	messages would have cost. The Accountant sees the fee messages only."""
	frappe.only_for(ROLES)
	filters = frappe._dict(filters or {})
	from_date = getdate(filters.from_date or add_months(get_first_day(today()), -11))
	to_date = getdate(filters.to_date or today())
	types = visible_types()
	if filters.message_type:
		types = [t for t in types if t == filters.message_type]

	rows = frappe.db.sql(
		"""
		select date_format(coalesce(sent_on, creation), '%%Y-%%m') as month, message_type, status,
			count(*) as messages, coalesce(sum(segments), 0) as sms, coalesce(sum(estimated_cost), 0) as cost
		from `tabSMS Outbox`
		where message_type in %(types)s and date(coalesce(sent_on, creation)) between %(from_date)s and %(to_date)s
		group by month, message_type, status
		order by month desc, message_type, status
		""",
		{"types": tuple(types) or ("",), "from_date": from_date, "to_date": to_date},
		as_dict=True,
	)
	for r in rows:
		r.note = NOTES.get(r.status, "")
		if r.status not in (SENT, TESTED):
			r.cost = 0  # nothing was sent, nothing was paid
	return get_columns(), rows, None, get_chart(rows), get_summary(types)


NOTES = {
	SENT: "Sent and paid for",
	TESTED: "Test mode: not sent; the cost is what it would have been",
	"Queued": "Waiting (quiet hours, limits or a retry)",
	"Failed": "Not sent: see the reason on each message",
	"Skipped": "Not sent: no consent, SMS turned off, or expired",
}


def visible_types():
	roles = set(frappe.get_roles())
	if frappe.session.user == "Administrator" or roles & set(MANAGER_ROLES):
		return list(MESSAGE_TYPES)
	return list(FEE_TYPES)


def get_summary(types):
	settings = get_settings()
	if set(types) != set(MESSAGE_TYPES):
		return []  # the limits count every type: shown to the Headmaster only
	used_today, used_month = usage()
	return [
		{"value": settings.mode, "label": "SMS Mode", "datatype": "Data", "indicator": {"Live": "Green", "Test": "Blue"}.get(settings.mode, "Gray")},
		{"value": f"{used_today:,} / {settings.daily_limit:,}", "label": "SMS Today / Daily Limit", "datatype": "Data"},
		{"value": f"{used_month:,} / {settings.monthly_limit:,}", "label": "SMS This Month / Monthly Limit", "datatype": "Data"},
		{"value": settings.price, "label": "Price per SMS (TZS)", "datatype": "Currency"},
	]


def get_chart(rows):
	months = sorted({r.month for r in rows})
	if not months:
		return None
	total = lambda status, month: sum(r.cost for r in rows if r.status == status and r.month == month)
	return {
		"data": {
			"labels": months,
			"datasets": [
				{"name": "Sent (TZS)", "values": [total(SENT, m) for m in months]},
				{"name": "Test mode (TZS, not spent)", "values": [total(TESTED, m) for m in months]},
			],
		},
		"type": "bar",
		"barOptions": {"stacked": 1},
	}


def get_columns():
	return [
		{"fieldname": "month", "label": "Month", "fieldtype": "Data", "width": 90},
		{"fieldname": "message_type", "label": "Type", "fieldtype": "Data", "width": 160},
		{"fieldname": "status", "label": "Status", "fieldtype": "Data", "width": 90},
		{"fieldname": "messages", "label": "Messages", "fieldtype": "Int", "width": 100},
		{"fieldname": "sms", "label": "SMS", "fieldtype": "Int", "width": 80},
		{"fieldname": "cost", "label": "Cost (TZS)", "fieldtype": "Currency", "width": 120},
		{"fieldname": "note", "label": "Notes", "fieldtype": "Data", "width": 330},
	]
