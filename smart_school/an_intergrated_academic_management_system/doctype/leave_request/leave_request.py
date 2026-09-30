# Copyright (c) 2026, john daudi and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import getdate

from smart_school.school_calendar import SchoolCalendar

# What the parent wrote stays as written; the school changes the status through smart_school.leave only
FIXED = ("student", "guardian", "class", "from_date", "to_date", "reason", "attachment", "status")


class LeaveRequest(Document):
	def validate(self):
		if getdate(self.to_date) < getdate(self.from_date):
			frappe.throw("To is before From")
		if self.is_new():
			self.set("class", self.get("class") or frappe.db.get_value("Student", self.student, "current_class"))
			self.status = self.status or "Pending"
		elif not (self.flags.from_portal or self.flags.deciding):
			changed = [f for f in FIXED if self.has_value_changed(f)]
			if changed:
				frappe.throw(
					"Use Approve, Reject or Withdraw; the request itself cannot be changed ("
					+ ", ".join(self.meta.get_label(f) for f in changed)
					+ ")"
				)
		self.school_days = len(SchoolCalendar().school_days(self.from_date, self.to_date, self.get("class")))
