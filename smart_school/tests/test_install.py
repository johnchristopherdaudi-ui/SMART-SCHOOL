"""A fresh site gets the data the app needs from after_install (patches do not run on install)."""

import frappe
from frappe.tests.utils import FrappeTestCase


class TestFreshInstall(FrappeTestCase):
	def test_grading_tables_seeded_with_provisional_d3_values(self):
		grades = frappe.get_all(
			"Grading System",
			fields=["grade", "minimum_mark", "maximum_mark", "points", "remark"],
			order_by="minimum_mark desc",
			as_list=True,
		)
		self.assertEqual(
			[tuple(g) for g in grades],
			[
				("A", 75, 100, 1, "Excellent"),
				("B", 65, 74, 2, "Very Good"),
				("C", 45, 64, 3, "Good"),
				("D", 30, 44, 4, "Satisfactory"),
				("F", 0, 29, 5, "Fail"),
			],
		)

	def test_division_table_seeded(self):
		divisions = frappe.get_all(
			"Division Grading",
			fields=["division", "minimum_points", "maximum_points"],
			order_by="minimum_points",
			as_list=True,
		)
		self.assertEqual(
			[tuple(d) for d in divisions],
			[
				("Division I", 7, 17),
				("Division II", 18, 21),
				("Division III", 22, 25),
				("Division IV", 26, 33),
				("Division 0", 34, 35),
			],
		)

	def test_risk_defaults(self):
		s = frappe.get_single("Smart School Settings")
		weights = [
			s.risk_weight_attendance,
			s.risk_weight_discipline,
			s.risk_weight_low_average,
			s.risk_weight_failed_subjects,
			s.risk_weight_decline,
		]
		self.assertEqual(weights, [25, 20, 25, 15, 15])
		self.assertEqual((s.risk_average_threshold, s.risk_medium_from, s.risk_high_from), (45, 30, 60))

	def test_sms_defaults_and_templates(self):
		from smart_school.patches import set_sms_defaults
		from smart_school.sms import DEFAULT_TEMPLATES

		stored = dict(
			frappe.db.sql(
				"select field, value from `tabSingles` where doctype = 'Smart School Settings' and field like 'sms%%'"
			)
		)
		self.assertEqual(
			{f: stored.get(f) for f in ("sms_mode", "sms_price", "sms_daily_limit", "sms_monthly_limit", "sms_quiet_start", "sms_quiet_end")},
			{
				"sms_mode": "Off",
				"sms_price": "25",
				"sms_daily_limit": "1500",
				"sms_monthly_limit": "5000",
				"sms_quiet_start": "21:00:00",
				"sms_quiet_end": "07:00:00",
			},
		)
		self.assertEqual((stored.get("sms_fee_reminder_before_term"), stored.get("sms_fee_reminder_overdue")), ("0", "0"))
		for template_type in DEFAULT_TEMPLATES:
			self.assertEqual(frappe.db.get_value("SMS Template", template_type, "example_segments"), 1, template_type)

		# A number that was never stored is filled in, although get_single_value reads it as 0
		frappe.db.delete("Singles", {"doctype": "Smart School Settings", "field": "sms_daily_limit"})
		self.assertEqual(frappe.db.get_single_value("Smart School Settings", "sms_daily_limit"), 0)
		set_sms_defaults.execute()
		self.assertEqual(frappe.db.get_single_value("Smart School Settings", "sms_daily_limit"), 1500)
		frappe.db.rollback()

	def test_external_exam_types(self):
		for name in ("District Exam", "Regional Exam", "Mock"):
			self.assertTrue(frappe.db.exists("External Exam Type", name), name)

	def test_roles_and_parent_is_portal_only(self):
		for role in ("Headmaster", "Teacher", "Accountant", "Parent"):
			self.assertTrue(frappe.db.exists("Role", role), role)
		self.assertEqual(frappe.db.get_value("Role", "Parent", "desk_access"), 0)

	def test_term_result_unique_index(self):
		self.assertTrue(
			frappe.db.sql("show index from `tabStudent Term Result` where Key_name = 'unique_student_term'")
		)

	def test_app_records_synced(self):
		for doctype, name in [
			("Report", "Class Merit List"),
			("Report", "Fee Collection and Defaulters"),
			("Report", "My Classes"),
			("Print Format", "Report Card"),
			("Web Form", "student-admission-form"),
			("Workspace", "Headmaster"),
			("Workspace", "Academics"),
			("Workspace", "Finance"),
			("Workspace", "School Settings"),
			("Number Card", "Outstanding Fees"),
			("Dashboard Chart", "Division Distribution"),
		]:
			self.assertTrue(frappe.db.exists(doctype, name), f"{doctype} {name}")
