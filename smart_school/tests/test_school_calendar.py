"""School calendar: school days (weekends, holidays, breaks, class events, Saturdays), terms and exams shown from
their own dates, attendance counted on school days, completeness, the parent portal page and SMS reminders."""

from datetime import date, timedelta

import frappe
from frappe.utils import add_days, getdate, today

from smart_school import school_calendar, sms
from smart_school.reports import get_attendance_completeness
from smart_school.school_calendar import SchoolCalendar, calendar_items, count_attendance
from smart_school.tests.factory import (
	HEADMASTER,
	PARENT_1,
	PARENT_2,
	TEACHER_1,
	SchoolTestCase,
	as_user,
	enforce_roles,
	make_exam,
	render,
)

TERM = "_Test Cal T1"  # Tuesday 1 April to Friday 30 May 2031
START, END = date(2031, 4, 1), date(2031, 5, 30)
KARUME, WORKERS = date(2031, 4, 7), date(2031, 5, 1)  # Monday, Thursday: fixed holidays
TRIP_FRIDAY, MAKEUP_SATURDAY = date(2031, 4, 4), date(2031, 4, 5)
BREAK = (date(2031, 5, 12), date(2031, 5, 16))  # Monday to Friday


def event(title, start, end=None, is_school_day=0, classes=None, **values):
	return frappe.get_doc(
		{
			"doctype": "School Event",
			"title": title,
			"event_type": values.pop("event_type", "Other"),
			"start_date": start,
			"end_date": end,
			"is_school_day": is_school_day,
			"audience": "Specific Classes" if classes else "All School",
			"classes": [{"class": c} for c in classes or []],
			"show_on_portal": values.pop("show_on_portal", 1),
			**values,
		}
	).insert(ignore_permissions=True)


class CalendarTestCase(SchoolTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		if not frappe.db.exists("Academic Year", "_Test Cal AY"):
			frappe.get_doc(
				{"doctype": "Academic Year", "year": "_Test Cal AY", "start_date": "2031-01-01", "end_date": "2031-12-31"}
			).insert(ignore_permissions=True, set_name="_Test Cal AY")
			frappe.get_doc(
				{"doctype": "Term", "term_name": "Term 1", "academic_year": "_Test Cal AY", "start_date": START, "end_date": END}
			).insert(ignore_permissions=True, set_name=TERM)
		event("_Test Break", *BREAK, event_type="Midterm Break")
		event("_Test Trip", TRIP_FRIDAY, classes=["_Test FORM 2"])
		event("_Test Make-up Saturday", MAKEUP_SATURDAY, is_school_day=1, classes=["_Test FORM 1"])

	def setUp(self):
		super().setUp()
		self.setting("saturday_is_school_day", 0)

	def setting(self, fieldname, value):
		previous = frappe.db.get_single_value("Smart School Settings", fieldname)
		self.addCleanup(frappe.db.set_single_value, "Smart School Settings", fieldname, previous)
		frappe.db.set_single_value("Smart School Settings", fieldname, value)


class TestSchoolDays(CalendarTestCase):
	def test_weekends_holidays_breaks_and_class_events(self):
		calendar = SchoolCalendar()
		days = set(calendar.school_days(START, END))
		weekdays = {d for d in school_calendar.date_range(START, END) if d.weekday() < 5}
		break_days = set(school_calendar.date_range(*BREAK))
		self.assertEqual(days, weekdays - {KARUME, WORKERS} - break_days)

		# A class's own event: FORM 2 is away on a Friday, FORM 1 has a make-up Saturday
		self.assertTrue(calendar.is_school_day(TRIP_FRIDAY, "_Test FORM 1"))
		self.assertFalse(calendar.is_school_day(TRIP_FRIDAY, "_Test FORM 2"))
		self.assertTrue(calendar.is_school_day(MAKEUP_SATURDAY, "_Test FORM 1"))
		self.assertFalse(calendar.is_school_day(MAKEUP_SATURDAY, "_Test FORM 2"))
		self.assertFalse(calendar.is_school_day(MAKEUP_SATURDAY))  # the school as a whole

		# Outside a term there is no school day, and the fixed holidays repeat every year
		self.assertFalse(calendar.is_school_day(END + timedelta(days=3)))
		self.assertFalse(calendar.is_school_day(date(2031, 4, 26)))  # Union Day, a Saturday anyway

	def test_saturday_setting_and_holidays_win(self):
		self.setting("saturday_is_school_day", 1)
		calendar = SchoolCalendar()
		self.assertTrue(calendar.is_school_day(date(2031, 4, 12)))  # an ordinary Saturday
		self.assertFalse(calendar.is_school_day(date(2031, 4, 13)))  # Sunday
		# A school-day event does not cancel a holiday
		event("_Test Exams", KARUME, KARUME + timedelta(days=2), is_school_day=1, event_type="Exam Period")
		self.assertFalse(SchoolCalendar().is_school_day(KARUME))

	def test_attendance_is_counted_on_school_days_only(self):
		records = [
			frappe._dict(date=date(2031, 4, 2), status="Absent", **{"class": "_Test FORM 1"}),
			frappe._dict(date=date(2031, 4, 3), status="Late", **{"class": "_Test FORM 1"}),
			frappe._dict(date=date(2031, 4, 8), status="Present", **{"class": "_Test FORM 1"}),
			frappe._dict(date=date(2031, 4, 9), status="Excused", **{"class": "_Test FORM 1"}),
			frappe._dict(date=KARUME, status="Absent", **{"class": "_Test FORM 1"}),  # holiday
			frappe._dict(date=date(2031, 4, 6), status="Absent", **{"class": "_Test FORM 1"}),  # Sunday
			frappe._dict(date=TRIP_FRIDAY, status="Absent", **{"class": "_Test FORM 2"}),  # FORM 2's trip
		]
		counts = count_attendance(records)
		self.assertEqual((counts.days, counts.absent, counts.late, counts.not_counted), (4, 1, 1, 3))
		self.assertAlmostEqual(counts.absence_rate, 37.5)  # (1 + 0.5) / 4
		self.assertAlmostEqual(counts.attended_rate, 50.0)  # Present and Late over 4


class TestCalendarItems(CalendarTestCase):
	def test_terms_and_exams_follow_their_own_dates(self):
		exam = make_exam("_Test Cal Exam", TERM, "_Test FORM 1")
		no_dates = make_exam("_Test Cal Undated", TERM, "_Test FORM 1")
		doc = frappe.get_doc("Exam", exam)
		doc.start_date = date(2031, 5, 20)
		doc.save(ignore_permissions=True)
		self.assertEqual(getdate(doc.end_date), date(2031, 5, 20))  # one day when only the start is set

		items = calendar_items(START, END)
		kinds = {(i.kind, i.name, i.start) for i in items}
		self.assertIn(("Term", TERM, START), kinds)
		self.assertIn(("Term", TERM, END), kinds)
		self.assertIn(("Exam", exam, date(2031, 5, 20)), kinds)
		self.assertNotIn(no_dates, {i.name for i in items})
		self.assertIn(("Public Holiday", KARUME), {(i.kind, i.start) for i in items})

		# Change the dates on the term or the exam: the calendar follows (nothing was copied)
		frappe.db.set_value("Term", TERM, "end_date", date(2031, 5, 29))
		doc.start_date, doc.end_date = date(2031, 5, 21), date(2031, 5, 23)
		doc.save(ignore_permissions=True)
		items = calendar_items(START, END)
		self.assertIn(("Term", date(2031, 5, 29)), {(i.kind, i.start) for i in items if i.name == TERM})
		self.assertEqual(
			[(i.start, i.end) for i in items if i.name == exam], [(date(2031, 5, 21), date(2031, 5, 23))]
		)
		frappe.db.set_value("Term", TERM, "end_date", END)

		doc.end_date = date(2031, 5, 1)
		self.assertRaises(frappe.ValidationError, doc.save, ignore_permissions=True)

	def test_event_rules(self):
		self.assertRaises(frappe.ValidationError, event, "_Test Bad", date(2031, 4, 10), date(2031, 4, 9))
		bad = frappe.get_doc(
			{"doctype": "School Event", "title": "_Test", "event_type": "Other", "start_date": date(2031, 4, 10), "audience": "Specific Classes"}
		)
		self.assertRaises(frappe.ValidationError, bad.insert, ignore_permissions=True)
		self.assertRaises(frappe.ValidationError, event, "_Test Yearly SMS", date(2031, 6, 1), repeat_every_year=1, sms_reminder=1)
		self.assertRaises(frappe.ValidationError, event, "_Test Hidden SMS", date(2031, 6, 1), show_on_portal=0, sms_reminder=1)

	def test_desk_calendar(self):
		with as_user(TEACHER_1):
			events = school_calendar.get_calendar_events("2031-04-01", "2031-05-31")
		by_doctype = {e["doctype"] for e in events}
		self.assertEqual(by_doctype, {"School Event", "Term"})
		karume = next(e for e in events if e["start_date"] == str(KARUME))
		self.assertEqual((karume["derived"], karume["color"]), (1, school_calendar.COLORS["Public Holiday"]))
		with as_user(PARENT_1):
			self.assertRaises(frappe.PermissionError, school_calendar.get_calendar_events, "2031-04-01", "2031-05-31")

	def test_fixed_holidays_are_installed(self):
		holidays = frappe.get_all("School Event", filters={"repeat_every_year": 1, "event_type": "Public Holiday"}, pluck="title")
		self.assertEqual(sorted(holidays), sorted(t for t, _, _ in school_calendar.FIXED_HOLIDAYS))


class TestAttendanceCompleteness(CalendarTestCase):
	def test_summary_completeness_and_early_warning_note(self):
		from smart_school.an_intergrated_academic_management_system.report.attendance_summary import attendance_summary
		from smart_school.an_intergrated_academic_management_system.report.early_warning import early_warning

		calendar = SchoolCalendar()
		term_days = calendar.term_school_days("_Test T2", "_Test FORM 1")
		weekend = next(
			d for d in school_calendar.date_range(*frappe.db.get_value("Term", "_Test T2", ["start_date", "end_date"])) if d.weekday() == 6
		)
		for day, status in ((term_days[0], "Absent"), (term_days[1], "Present"), (weekend, "Absent")):
			frappe.get_doc({"doctype": "Attendance", "student": self.s["a"], "date": day, "status": status}).insert(
				ignore_permissions=True
			)

		_, rows = attendance_summary.execute({"term": "_Test T2", "class": "_Test FORM 1"})
		row = rows[0]
		self.assertEqual((row["school_days"], row["days"], row["absent"], row["not_counted"]), (len(term_days), 2, 1, 1))
		self.assertAlmostEqual(row["completeness"], round(2 / len(term_days) * 100, 1))
		self.assertAlmostEqual(row["absence_rate"], 50.0)

		note = early_warning.completeness_note({"_Test FORM 1"}, "_Test T2")
		self.assertIn("_Test FORM 1", note)
		self.setting("attendance_completeness_min", 1)
		self.assertEqual(early_warning.completeness_note({"_Test FORM 1"}, "_Test T2"), "")

		with enforce_roles(), as_user(HEADMASTER):
			card = get_attendance_completeness()
		self.assertEqual(card["fieldtype"], "Percent")


class TestPortalCalendar(CalendarTestCase):
	def test_parents_see_their_childrens_calendar_in_swahili(self):
		soon = add_days(today(), 10)
		mine = make_exam("_Test Cal Portal Mine", "_Test T3", "_Test FORM 1")
		theirs = make_exam("_Test Cal Portal Theirs", "_Test T3", "_Test FORM 2")
		for exam in (mine, theirs):
			frappe.db.set_value("Exam", exam, {"start_date": soon, "end_date": soon})
		event("_Test Mkutano FORM 2", soon, classes=["_Test FORM 2"], event_type="Parents Meeting")
		event("_Test Siri", soon, show_on_portal=0)
		event("_Test Michezo", soon, event_type="Sports Day")

		with as_user(PARENT_1):  # two children in _Test FORM 1
			status, body, _ = render("parent-portal/kalenda")
		self.assertEqual(status, 200)
		for text in ("Kalenda ya Shule", "Yanayokuja", "_Test Michezo", "Mtihani wa _Test Cal Portal Mine (_Test FORM 1)", "Michezo"):
			self.assertIn(text, body)
		for text in ("_Test Cal Portal Theirs", "_Test Mkutano FORM 2", "_Test Siri"):
			self.assertNotIn(text, body)

		with as_user(PARENT_2):  # one child in _Test FORM 2
			_, body, _ = render("parent-portal/kalenda")
		self.assertIn("_Test Mkutano FORM 2", body)

		with as_user(PARENT_1):
			_, body, _ = render("parent-portal/kalenda", mwezi="2031-04")
			self.assertIn("Aprili 2031", body)
			self.assertIn("Siku ya Karume", body)
			self.assertIn("Hakuna masomo", body)
			_, body, _ = render("parent-portal/kalenda", mwezi="<script>")
			self.assertNotIn("<script>", body.split("sp-month-nav")[1][:300])
		with as_user("Guest"):
			status, _, location = render("parent-portal/kalenda")
		self.assertIn("/login", location or "")


class TestEventReminderSMS(CalendarTestCase):
	def setUp(self):
		super().setUp()
		for fieldname, value in {**sms.DEFAULTS, "sms_mode": sms.TEST, "sms_school_name": "Mwanga SS"}.items():
			self.setting(fieldname, value)
		self.addCleanup(frappe.clear_document_cache, "Smart School Settings", "Smart School Settings")
		frappe.clear_document_cache("Smart School Settings", "Smart School Settings")
		self.p1 = frappe.db.get_value("Guardian", {"email": PARENT_1})
		self.p2 = frappe.db.get_value("Guardian", {"email": PARENT_2})
		for guardian in (self.p1, self.p2):
			previous = frappe.db.get_value("Guardian", guardian, "sms_opt_in")
			self.addCleanup(frappe.db.set_value, "Guardian", guardian, "sms_opt_in", previous)
			frappe.db.set_value("Guardian", guardian, "sms_opt_in", 1)

	def test_reminder_once_for_the_events_classes(self):
		day = add_days(today(), 5)
		doc = event("_Test Mkutano wa Wazazi", day, classes=["_Test FORM 1"], event_type="Parents Meeting", sms_reminder=1, sms_days_before=2)
		outbox = lambda: frappe.get_all("SMS Outbox", filters={"reference_name": doc.name}, fields=["guardian", "message", "segments"])

		sms.send_event_reminders(add_days(day, -3))  # too early
		self.assertEqual(outbox(), [])
		sms.send_event_reminders(add_days(day, -2))
		rows = outbox()
		self.assertEqual([r.guardian for r in rows], [self.p1])  # FORM 1's parents only
		self.assertIn("Kumbusho - _Test Mkutano wa Wazazi", rows[0].message)
		self.assertTrue(rows[0].message.endswith("/kalenda"))
		self.assertEqual(rows[0].segments, 1)
		sms.send_event_reminders(add_days(day, -1))  # the next day: not again
		self.assertEqual(len(outbox()), 1)

		with enforce_roles(), as_user(HEADMASTER):
			p = sms.preview_event_reminder(audience="All School")
		self.assertEqual((p.mode, p.messages), (sms.TEST, 2))
		with enforce_roles(), as_user(TEACHER_1):
			self.assertRaises(frappe.PermissionError, sms.preview_event_reminder, audience="All School")
