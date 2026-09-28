# Copyright (c) 2026, john daudi and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

from smart_school.sms import compose, long_values, measure, unknown_placeholders


class SMSTemplate(Document):
	def validate(self):
		unknown = unknown_placeholders(self.template_type, self.message)
		if unknown:
			frappe.throw(
				f"Unknown placeholder(s) for {self.template_type}: "
				+ ", ".join("{" + p + "}" for p in unknown)
			)
		self.example = compose(self.template_type, long_values(self.template_type), template=self.message)
		self.example_characters, self.example_segments, self.example_encoding = measure(self.example)
		if self.example_segments > 1:
			frappe.msgprint(
				f"With long names this message needs {self.example_segments} SMS "
				f"({self.example_characters} characters, {self.example_encoding}); each costs the price of one SMS.",
				indicator="orange",
				alert=True,
			)
