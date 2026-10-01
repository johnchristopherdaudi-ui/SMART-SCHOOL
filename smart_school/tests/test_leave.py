"""Leave requests: a parent asks for their own child on the portal (Swahili), the class teacher or the Headmaster
decides, approved leave excuses the attendance of its school days (and withdrawing it restores it), the reason and
the file stay with the Headmaster and the class teacher, and the parent gets the answer (and an SMS if agreed)."""

import base64
from datetime import timedelta
from unittest.mock import patch

import frappe
import frappe.client
from frappe.utils import add_days, getdate, today

from smart_school import class_attendance, leave, sms
from smart_school.school_calendar import SchoolCalendar
from smart_school.tests.factory import (
	ACCOUNTANT,
	HEADMASTER,
	PARENT_1,
	PARENT_2,
	TEACHER_1,
	TEACHER_2,
	SchoolTestCase,
	as_user,
	enforce_roles,
	render,
)

def blank_pdf():
	from io import BytesIO

	from pypdf import PdfWriter

	writer, out = PdfWriter(), BytesIO()
	writer.add_blank_page(width=200, height=200)
	writer.write(out)
	return out.getvalue()


PDF = "data:application/pdf;base64," + base64.b64encode(blank_pdf()).decode()
BROKEN_PDF = "data:application/pdf;base64," + base64.b64encode(b"%PDF-1.4 truncated").decode()
NOT_A_PDF = "data:application/pdf;base64," + base64.b64encode(b"MZ this is not a pdf").decode()


class LeaveTestCase(SchoolTestCase):
	def setUp(self):
		super().setUp()
		frappe.db.delete("Leave Request")
		self.start, self.end = getdate(add_days(today(), -7)), getdate(today())
		calendar = SchoolCalendar()
		self.school_day = next(
			d for d in reversed(calendar.term_school_days("_Test T3", "_Test FORM 2")) if self.start <= d <= self.end
		)
		self.weekend = next(d for d in (self.start + timedelta(days=i) for i in range(8)) if d.weekday() >= 5)
		self.p1 = frappe.db.get_value("Guardian", {"email": PARENT_1})
		self.p2 = frappe.db.get_value("Guardian", {"email": PARENT_2})

	def ask(self, parent, student, start=None, end=None, reason="Mgonjwa, ana homa", **file):
		with as_user(parent):
			return leave.submit_request(self.s[student], start or self.start, end or self.end, reason, **file)

	def attendance(self, student, day, status):
		return frappe.get_doc(
			{"doctype": "Attendance", "student": self.s[student], "date": day, "status": status}
		).insert(ignore_permissions=True)


class TestAsking(LeaveTestCase):
	def test_a_parent_asks_for_their_own_child_with_a_private_file(self):
		with as_user(PARENT_1):
			self.assertRaises(frappe.PermissionError, leave.submit_request, self.s["e"], self.start, self.end, "Safari")
		name = self.ask(PARENT_2, "e", file_name="cheti.pdf", file_data=PDF)
		doc = frappe.get_doc("Leave Request", name)
		self.assertEqual((doc.status, doc.get("class"), doc.guardian), ("Pending", "_Test FORM 2", self.p2))
		self.assertEqual(doc.school_days, len(SchoolCalendar().school_days(self.start, self.end, "_Test FORM 2")))
		file = frappe.get_doc("File", {"file_url": doc.attachment})
		self.assertEqual((file.is_private, file.attached_to_doctype, file.attached_to_name), (1, "Leave Request", name))
		self.assertTrue(doc.attachment.startswith("/private/files/"))
		# the class teacher of _Test FORM 2 is told
		todo = frappe.get_all("ToDo", filters={"reference_name": name, "status": "Open"}, pluck="allocated_to")
		self.assertEqual(todo, [TEACHER_2])
		# _Test FORM 1 has no class teacher: the Headmaster is told
		other = self.ask(PARENT_1, "a")
		self.assertIn(HEADMASTER, frappe.get_all("ToDo", filters={"reference_name": other}, pluck="allocated_to"))

	def test_mistakes_are_explained_in_swahili(self):
		cases = [
			({"start": add_days(today(), -8)}, "hadi siku 7 nyuma"),
			({"start": self.end, "end": self.start}, "iko kabla ya tarehe ya kuanza"),
			({"reason": "  "}, "Andika sababu fupi"),
			({"reason": "x" * 501}, "herufi 500"),
			({"file_name": "cheti.pdf", "file_data": NOT_A_PDF}, "PDF au picha"),
			({"file_name": "cheti.exe", "file_data": PDF}, "PDF au picha"),
			({"file_name": "cheti.pdf", "file_data": BROKEN_PDF}, "haisomeki"),
		]
		for values, message in cases:
			self.assertRaisesRegex(frappe.ValidationError, message, self.ask, PARENT_2, "e", **values)
		with patch.object(leave, "MAX_FILE_BYTES", 10):
			self.assertRaisesRegex(frappe.ValidationError, "MB 5", self.ask, PARENT_2, "e", file_name="c.pdf", file_data=PDF)
		self.ask(PARENT_2, "e")
		self.assertRaisesRegex(frappe.ValidationError, "Tayari kuna ombi", self.ask, PARENT_2, "e")

	def test_parent_cancels_only_their_waiting_request(self):
		name = self.ask(PARENT_2, "e")
		with as_user(PARENT_1):
			self.assertRaises(frappe.PermissionError, leave.cancel_request, name)
		with as_user(PARENT_2):
			leave.cancel_request(name)
			self.assertRaises(frappe.ValidationError, leave.cancel_request, name)
		self.assertEqual(frappe.db.get_value("Leave Request", name, "status"), "Cancelled")
		self.assertEqual(frappe.get_all("ToDo", filters={"reference_name": name, "status": "Open"}), [])


class TestWhoSees(LeaveTestCase):
	def test_reason_and_file_stay_with_the_headmaster_and_class_teacher(self):
		mine = self.ask(PARENT_2, "e", file_name="cheti.pdf", file_data=PDF)  # _Test FORM 2
		theirs = self.ask(PARENT_1, "a")  # _Test FORM 1
		file = frappe.get_doc("File", {"file_url": frappe.db.get_value("Leave Request", mine, "attachment")})

		def visible(user):
			with as_user(user):
				try:
					return set(frappe.get_list("Leave Request", pluck="name"))
				except frappe.PermissionError:
					return set()

		self.assertEqual(visible(HEADMASTER), {mine, theirs})
		self.assertEqual(visible(TEACHER_2), {mine})
		self.assertEqual(visible(TEACHER_1), set())
		self.assertEqual(visible(ACCOUNTANT), set())
		self.assertEqual(visible(PARENT_1), set())  # parents use the portal only
		self.assertTrue(frappe.has_permission("File", "read", doc=file, user=TEACHER_2))
		self.assertTrue(frappe.has_permission("File", "read", doc=file, user=HEADMASTER))
		self.assertFalse(frappe.has_permission("File", "read", doc=file, user=TEACHER_1))
		self.assertFalse(frappe.has_permission("File", "read", doc=file, user=ACCOUNTANT))

		# The portal page shows a parent their own requests only, in Swahili
		with as_user(PARENT_1):
			status, body, _ = render("parent-portal/ruhusa")
		self.assertEqual(status, 200)
		for text in ("Ruhusa", "Tuma ombi", "Inasubiri uamuzi", "_Test Student A", "Mgonjwa, ana homa"):
			self.assertIn(text, body)
		self.assertNotIn(mine, body)
		self.assertNotIn("_Test Student E", body)


class TestDeciding(LeaveTestCase):
	def test_approve_excuses_school_days_and_withdraw_restores(self):
		absent = self.attendance("e", self.school_day, "Absent")
		weekend = self.attendance("e", self.weekend, "Absent")
		name = self.ask(PARENT_2, "e")

		with as_user(TEACHER_1):
			self.assertRaises(frappe.PermissionError, leave.decide, name, "Approved")
		with as_user(TEACHER_2):
			leave.decide(name, "Approved", "Apone haraka")
		doc = frappe.get_doc("Leave Request", name)
		self.assertEqual((doc.status, doc.decided_by, doc.decision_note), ("Approved", TEACHER_2, "Apone haraka"))
		self.assertEqual(
			frappe.db.get_value("Attendance", absent.name, ["status", "leave_request", "status_before_leave"]),
			("Excused", name, "Absent"),
		)
		self.assertEqual(frappe.db.get_value("Attendance", weekend.name, "status"), "Absent")  # not a school day
		self.assertEqual(frappe.get_all("ToDo", filters={"reference_name": name, "status": "Open"}), [])

		# The class attendance page shows the leave; a day recorded then is linked to it
		other_day = next(
			d for d in reversed(SchoolCalendar().term_school_days("_Test T3", "_Test FORM 2"))
			if self.start <= d <= self.end and d != self.school_day
		)
		with as_user(TEACHER_2):
			row = next(r for r in class_attendance.get_sheet("_Test FORM 2", other_day)["students"] if r["student"] == self.s["e"])
			self.assertEqual((row["status"], row["source"]), ("Excused", "leave"))
			class_attendance.save_sheet("_Test FORM 2", other_day, [{"student": self.s["e"], "status": "Excused"}])
		recorded = frappe.get_value("Attendance", {"student": self.s["e"], "date": other_day}, "name")

		with enforce_roles(), as_user(TEACHER_2):
			self.assertRaises(frappe.PermissionError, leave.withdraw, name)
		with enforce_roles(), as_user(HEADMASTER):
			leave.withdraw(name, "Imefutwa")
		self.assertEqual(frappe.db.get_value("Attendance", absent.name, ["status", "leave_request"]), ("Absent", None))
		self.assertEqual(frappe.db.get_value("Attendance", recorded, "status"), "Absent")  # excused only by the leave
		self.assertEqual(frappe.db.get_value("Leave Request", name, "status"), "Cancelled")

	def test_rejection_and_the_request_cannot_be_rewritten(self):
		name = self.ask(PARENT_2, "e")
		with as_user(TEACHER_2):
			doc = frappe.get_doc("Leave Request", name)
			doc.reason = "Nyingine"
			self.assertRaises(frappe.ValidationError, doc.save)
			leave.decide(name, "Rejected", "Mtihani siku hiyo")
			self.assertRaises(frappe.ValidationError, leave.decide, name, "Approved")
		with as_user(PARENT_2):
			_, body, _ = render("parent-portal/ruhusa")
		self.assertIn("Haikuidhinishwa", body)
		self.assertIn("Mtihani siku hiyo", body)

	def test_the_parent_gets_an_sms_without_the_reason(self):
		for fieldname, value in {**sms.DEFAULTS, "sms_mode": sms.TEST, "sms_school_name": "Mwanga SS"}.items():
			previous = frappe.db.get_single_value("Smart School Settings", fieldname)
			self.addCleanup(frappe.db.set_single_value, "Smart School Settings", fieldname, previous)
			frappe.db.set_single_value("Smart School Settings", fieldname, value)
		self.addCleanup(frappe.clear_document_cache, "Smart School Settings", "Smart School Settings")
		frappe.clear_document_cache("Smart School Settings", "Smart School Settings")
		previous = frappe.db.get_value("Guardian", self.p2, "sms_opt_in")
		self.addCleanup(frappe.db.set_value, "Guardian", self.p2, "sms_opt_in", previous)
		frappe.db.set_value("Guardian", self.p2, "sms_opt_in", 1)

		name = self.ask(PARENT_2, "e", reason="Msiba wa familia")
		with as_user(TEACHER_2):
			leave.decide(name, "Approved")
		rows = frappe.get_all("SMS Outbox", filters={"reference_name": name}, fields=["guardian", "message", "segments"])
		self.assertEqual([r.guardian for r in rows], [self.p2])
		self.assertIn("Ombi la ruhusa ya _Test Student E", rows[0].message)
		self.assertIn("limeidhinishwa", rows[0].message)
		self.assertNotIn("Msiba", rows[0].message)
		self.assertTrue(rows[0].message.endswith("/ruhusa"))
		self.assertEqual(rows[0].segments, 1)


class TestOnlyAbsentDays(LeaveTestCase):
	def test_only_absent_days_are_excused_and_only_they_go_back(self):
		end = getdate(add_days(today(), 21))  # recorded days ahead too, so four school days fit
		days = SchoolCalendar().school_days(self.start, end, "_Test FORM 2")
		absent, present, late, corrected = (
			self.attendance("e", day, status) for day, status in zip(days, ("Absent", "Present", "Late", "Absent"))
		)
		name = self.ask(PARENT_2, "e", end=end)
		with as_user(TEACHER_2):
			leave.decide(name, "Approved")

		state = lambda record: frappe.db.get_value("Attendance", record.name, ["status", "leave_request"])
		self.assertEqual(state(absent), ("Excused", name))
		self.assertEqual(state(corrected), ("Excused", name))
		self.assertEqual(state(present), ("Present", None))  # the child came: nothing to excuse
		self.assertEqual(state(late), ("Late", None))

		frappe.db.set_value("Attendance", corrected.name, "status", "Present")  # corrected after the approval
		with enforce_roles(), as_user(HEADMASTER):
			leave.withdraw(name)
		self.assertEqual(state(absent), ("Absent", None))  # what the leave changed goes back
		self.assertEqual(state(corrected), ("Present", None))  # the correction stays
		self.assertEqual(state(present), ("Present", None))
		self.assertEqual(state(late), ("Late", None))
