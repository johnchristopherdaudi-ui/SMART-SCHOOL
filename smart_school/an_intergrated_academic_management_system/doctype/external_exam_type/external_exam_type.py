# Copyright (c) 2026, john daudi and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class ExternalExamType(Document):
	def before_insert(self):
		# One spelling per type: "district  exam" is the same type as "District Exam"
		self.type_name = " ".join((self.type_name or "").split())
		same = find_type(self.type_name)
		if same:
			frappe.throw(f"This type already exists as {same}", frappe.DuplicateEntryError)


def find_type(text):
	"""The existing type written like text, ignoring case and spaces, or None."""
	key = " ".join((text or "").split()).lower()
	return next((t for t in frappe.get_all("External Exam Type", pluck="name") if t.lower() == key), None)
