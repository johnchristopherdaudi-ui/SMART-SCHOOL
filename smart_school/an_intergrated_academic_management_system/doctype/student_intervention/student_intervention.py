# Copyright (c) 2026, john daudi and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import getdate

from smart_school.interventions import SNAPSHOT_FIELDS, check_responsible, fill_snapshot, previous_term


class StudentIntervention(Document):
	def validate(self):
		check_responsible(self.responsible)
		if self.follow_up_date and self.start_date and getdate(self.follow_up_date) < getdate(self.start_date):
			frappe.throw("The follow-up date cannot be before the start date")

		if self.is_new():
			if not self.get("class"):
				self.set("class", frappe.db.get_value("Student", self.student, "current_class"))
			if not self.flags.keep_snapshot:  # the demo generator writes its own
				for fieldname in SNAPSHOT_FIELDS:
					self.set(fieldname, None)
				fill_snapshot(self)
			self.baseline_term = self.baseline_term or previous_term(self.term)
			return

		fixed = [f for f in (*SNAPSHOT_FIELDS, "student", "term", "baseline_term", "source") if self.has_value_changed(f)]
		if fixed:
			frappe.throw(f"{', '.join(self.meta.get_label(f) for f in fixed)} cannot be changed after creation")
		if self.has_value_changed("follow_up_date"):
			self.reminder_sent_on = None  # a new follow-up date gets its own reminder
