"""Class attendance: the class teacher (and the Headmaster / System Manager) keep attendance, on the doctype and
through the API; the tool shows the class Present by default, warns on days that are not school days and saves once."""

from datetime import timedelta

import frappe
import frappe.client
from frappe.utils import add_days, getdate, today

from smart_school import class_attendance as ca
from smart_school.school_calendar import SchoolCalendar
from smart_school.tests.factory import HEADMASTER, PARENT_1, TEACHER_1, TEACHER_2, SchoolTestCase, as_user


class ClassAttendanceTestCase(SchoolTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		calendar = SchoolCalendar()
		start, end = frappe.db.get_value("Term", "_Test T3", ["start_date", "end_date"])
		days = calendar.term_school_days("_Test T3")
		cls.day, cls.other_day = str(days[-1]), str(days[-2])  # school days of the current term, up to today
		cls.weekend = str(next(d for d in (getdate(start) + timedelta(days=i) for i in range(14)) if d.weekday() == 6))
		t2_end = frappe.db.get_value("Term", "_Test T2", "end_date")
		cls.between_terms = str(add_days(t2_end, 1))

	def record(self, student, day=None, status="Absent"):
		return frappe.get_doc(
			{"doctype": "Attendance", "student": self.s[student], "date": day or self.day, "status": status}
		).insert(ignore_permissions=True)


class TestAttendancePermissions(ClassAttendanceTestCase):
	def test_class_teacher_keeps_their_class_only(self):
		form1 = self.record("a")  # _Test FORM 1: no class teacher
		form2 = self.record("e")  # _Test FORM 2: Teacher Two is its class teacher

		with as_user(TEACHER_2):
			self.assertEqual({r.name for r in frappe.get_list("Attendance")}, {form2.name})
			self.assertRaises(frappe.PermissionError, frappe.client.get, "Attendance", form1.name)
			self.assertRaises(frappe.PermissionError, frappe.client.set_value, "Attendance", form1.name, "status", "Present")
			frappe.client.set_value("Attendance", form2.name, "status", "Late")
			new = frappe.client.insert(
				{"doctype": "Attendance", "student": self.s["e"], "date": self.other_day, "status": "Present"}
			)
			self.assertEqual(new["class"], "_Test FORM 2")
			self.assertRaises(
				frappe.PermissionError,
				frappe.client.insert,
				{"doctype": "Attendance", "student": self.s["a"], "date": self.other_day, "status": "Present"},
			)
			# moving a record of their class onto another class's student
			doc = frappe.get_doc("Attendance", form2.name)
			doc.student = self.s["b"]
			self.assertRaises(frappe.PermissionError, doc.save)

		with as_user(TEACHER_1):  # teaches Form 1 but is nobody's class teacher
			self.assertEqual(frappe.get_list("Attendance"), [])
			self.assertRaises(
				frappe.PermissionError,
				frappe.client.insert,
				{"doctype": "Attendance", "student": self.s["a"], "date": self.other_day, "status": "Present"},
			)

		with as_user(HEADMASTER):
			frappe.client.set_value("Attendance", form1.name, "status", "Excused")
			frappe.client.insert({"doctype": "Attendance", "student": self.s["b"], "date": self.day, "status": "Present"})

		with as_user(PARENT_1):
			self.assertRaises(frappe.PermissionError, frappe.client.get_list, "Attendance")


class TestAttendanceTool(ClassAttendanceTestCase):
	def test_who_gets_which_classes(self):
		with as_user(HEADMASTER):
			self.assertEqual(set(ca.get_classes()), set(frappe.get_all("Class", pluck="name")))
		with as_user(TEACHER_2):
			self.assertEqual(ca.get_classes(), ["_Test FORM 2"])
			self.assertRaises(frappe.PermissionError, ca.get_sheet, "_Test FORM 1", self.day)
		with as_user(TEACHER_1):
			self.assertRaises(frappe.PermissionError, ca.get_classes)

	def test_sheet_defaults_warnings_and_dates(self):
		with as_user(HEADMASTER):
			sheet = ca.get_sheet("_Test FORM 1", self.day)
			self.assertIsNone(sheet["not_school_day"])
			students = {r["student"]: r for r in sheet["students"]}
			self.assertTrue({self.s["a"], self.s["b"]} <= set(students))
			self.assertEqual({r["status"] for r in sheet["students"]}, {"Present"})
			self.assertEqual({r["source"] for r in sheet["students"]}, {"default"})

		self.record("a", status="Late")
		with as_user(HEADMASTER):
			row = next(r for r in ca.get_sheet("_Test FORM 1", self.day)["students"] if r["student"] == self.s["a"])
			self.assertEqual((row["status"], row["source"]), ("Late", "recorded"))

			self.assertEqual(ca.get_sheet("_Test FORM 1", self.weekend)["not_school_day"], "Sunday")
			frappe.get_doc(
				{
					"doctype": "School Event",
					"title": "_Test Sikukuu",
					"event_type": "Public Holiday",
					"start_date": self.other_day,
					"is_school_day": 0,
					"audience": "All School",
				}
			).insert(ignore_permissions=True)
			self.assertEqual(ca.get_sheet("_Test FORM 1", self.other_day)["not_school_day"], "_Test Sikukuu")

			self.assertRaisesRegex(frappe.ValidationError, "not come yet", ca.get_sheet, "_Test FORM 1", add_days(today(), 1))
			self.assertRaisesRegex(frappe.ValidationError, "not inside any term", ca.get_sheet, "_Test FORM 1", self.between_terms)

	def test_save_once_then_correct_without_duplicates(self):
		entries = [{"student": self.s["e"], "status": "Absent"}]
		with as_user(TEACHER_2):
			result = ca.save_sheet("_Test FORM 2", self.day, entries)
			self.assertEqual((result["created"], result["updated"], result["counts"]["Absent"]), (1, 0, 1))
			result = ca.save_sheet("_Test FORM 2", self.day, [{"student": self.s["e"], "status": "Late"}])
			self.assertEqual((result["created"], result["updated"]), (0, 1))
			result = ca.save_sheet("_Test FORM 2", self.day, [{"student": self.s["e"], "status": "Late"}])
			self.assertEqual((result["created"], result["updated"]), (0, 0))
			self.assertEqual(
				frappe.get_all("Attendance", filters={"student": self.s["e"], "date": self.day}, pluck="status"), ["Late"]
			)
			self.assertRaises(
				frappe.ValidationError, ca.save_sheet, "_Test FORM 2", self.day, [{"student": self.s["a"], "status": "Present"}]
			)
			self.assertRaises(
				frappe.ValidationError, ca.save_sheet, "_Test FORM 2", self.day, [{"student": self.s["e"], "status": "Sick"}]
			)
			self.assertRaises(frappe.PermissionError, ca.save_sheet, "_Test FORM 1", self.day, [])
