# Copyright (c) 2026, john daudi and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import getdate

from smart_school.school_calendar import COLORS, DEFAULT_COLOR


class SchoolEvent(Document):
	def validate(self):
		self.end_date = self.end_date or self.start_date
		if getdate(self.end_date) < getdate(self.start_date):
			frappe.throw("End Date is before Start Date")
		if self.repeat_every_year and (getdate(self.end_date) - getdate(self.start_date)).days > 31:
			frappe.throw("An event that repeats every year can last a month at most")
		if self.audience == "Specific Classes" and not self.classes:
			frappe.throw("Choose the classes, or set the audience to All School")
		if self.audience != "Specific Classes":
			self.classes = []
		if self.sms_reminder:
			if self.repeat_every_year:
				frappe.throw("An SMS reminder is for a single event, not one that repeats every year")
			if not self.show_on_portal:
				frappe.throw("Show the event on the parent portal before reminding parents of it by SMS")
		if self.has_value_changed("start_date") or self.has_value_changed("sms_days_before"):
			self.sms_sent_on = None  # a moved event is reminded again
		self.color = COLORS.get(self.event_type, DEFAULT_COLOR)
