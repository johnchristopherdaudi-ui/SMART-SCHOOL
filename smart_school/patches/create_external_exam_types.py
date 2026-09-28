import frappe

from smart_school.an_intergrated_academic_management_system.doctype.external_exam_type.external_exam_type import (
	find_type,
)

DEFAULT_TYPES = ("District Exam", "Regional Exam", "Mock")


def execute():
	"""External exam types become a list to choose from: the defaults, plus every type already typed on an Exam.
	Spellings that differ only in case or spaces become one type, so the history of a kind is not split."""
	for name in DEFAULT_TYPES:
		ensure_type(name)
	for exam in frappe.get_all(
		"Exam", filters={"external_exam_type": ["is", "set"]}, fields=["name", "external_exam_type"]
	):
		type_name = ensure_type(exam.external_exam_type)
		if type_name != exam.external_exam_type:
			frappe.db.set_value("Exam", exam.name, "external_exam_type", type_name, update_modified=False)


def ensure_type(text):
	"""The type for text, created when there is none yet."""
	existing = find_type(text)
	if existing:
		return existing
	return frappe.get_doc({"doctype": "External Exam Type", "type_name": text}).insert(ignore_permissions=True).name
