import ast
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, getdate, today

from smart_school import sms
from smart_school.sms_providers import SendResult
from smart_school.tests.factory import (
	ACCOUNTANT,
	HEADMASTER,
	PARENT_1,
	PARENT_2,
	TEACHER_1,
	SchoolTestCase,
	add_result,
	as_user,
	enforce_roles,
	make_exam,
	make_user,
	pay,
)

DAY = datetime.combine(getdate(today()), datetime.min.time())
TEN_AM = DAY.replace(hour=10)


class FakeProvider:
	"""Answers from a list, one per message; records what it was asked to send."""

	name = "Fake"

	def __init__(self, *answers):
		self.answers = list(answers)
		self.sent = []

	def send(self, phone, text):
		self.sent.append((phone, text))
		return self.answers.pop(0) if self.answers else SendResult(True, message_id="ok")


class TestSMSText(FrappeTestCase):
	def test_characters_and_sms_parts(self):
		self.assertEqual(sms.measure("a" * 160), (160, 1, "GSM-7"))
		self.assertEqual(sms.measure("a" * 161), (161, 2, "GSM-7"))
		self.assertEqual(sms.measure("a" * 306)[1], 2)  # 153 per part
		self.assertEqual(sms.measure("a" * 307)[1], 3)
		self.assertEqual(sms.measure("{" * 80), (160, 1, "GSM-7"))  # extension characters count 2
		self.assertEqual(sms.measure("{" * 81)[1], 2)
		self.assertEqual(sms.measure("a" * 69 + "’"), (70, 1, "UCS-2"))  # a curly quote is not GSM-7
		self.assertEqual(sms.measure("a" * 70 + "’"), (71, 2, "UCS-2"))
		self.assertEqual(sms.measure("😀")[0], 2)

	def test_only_named_placeholders_are_filled(self):
		template = "{shule} {x.__class__} {kiungo} {haipo}"
		self.assertEqual(
			sms.render(template, {"shule": "Shule", "kiungo": "L"}), "Shule {x.__class__} L "
		)
		self.assertEqual(sms.unknown_placeholders(sms.ANNOUNCEMENT, template), ["haipo"])

	def test_results_message_fits_one_sms_with_long_names(self):
		values = {
			"shule": "Shule ya Sekondari M",  # the 20 characters allowed
			"kiungo": "https://shule-ya-sekondari-mfano.ac.tz/matokeo",
			"mwanafunzi": "Anastazia Nyamizi Mwakalinga Mushi Kimaro",
			"mtihani": "District Exam",
			"muhula": "Term 2 2026",
			"wastani": "100.0",
			"division": ", Division III",
		}
		template = sms.DEFAULT_TEMPLATES[sms.RESULTS]
		text = sms.compose(sms.RESULTS, values, template)
		self.assertEqual(sms.measure(text)[1], 1, text)
		self.assertIn("wastani 100.0%, Division III.", text)
		self.assertIn("Anastazia Kimaro", text)  # first and last name when the full name would need 2 SMS

		short = sms.compose(sms.RESULTS, {**values, "mwanafunzi": "Neema Juma"}, template)
		self.assertIn("Neema Juma - District Exam: wastani 100.0%, Division III. Zaidi: https://", short)
		# no division until the term result is complete: nothing shows
		self.assertIn("wastani 58.3%. Zaidi:", sms.compose(sms.RESULTS, {**values, "wastani": "58.3", "division": ""}, template))

	def test_announcement_title_is_cut_to_fit(self):
		text = sms.compose(
			sms.ANNOUNCEMENT,
			{"shule": "Mwanga SS", "kiungo": "https://mwanga.ac.tz/matangazo", "kichwa": "Mkutano " * 30},
			sms.DEFAULT_TEMPLATES[sms.ANNOUNCEMENT],
		)
		self.assertEqual(sms.measure(text)[1], 1)
		self.assertIn("...", text)

	def test_quiet_hours(self):
		settings = frappe._dict(quiet_start=datetime.strptime("21:00", "%H:%M").time(), quiet_end=datetime.strptime("07:00", "%H:%M").time())
		at = lambda h, m: DAY.replace(hour=h, minute=m)
		self.assertFalse(sms.in_quiet_hours(at(20, 59), settings))
		self.assertTrue(sms.in_quiet_hours(at(21, 0), settings))
		self.assertTrue(sms.in_quiet_hours(at(6, 59), settings))
		self.assertFalse(sms.in_quiet_hours(at(7, 0), settings))
		self.assertEqual(sms.next_send_time(at(22, 30), settings), at(7, 0) + timedelta(days=1))
		self.assertEqual(sms.next_send_time(at(5, 0), settings), at(7, 0))
		self.assertEqual(sms.next_send_time(at(12, 0), settings), at(12, 0))


class SMSTestCase(SchoolTestCase):
	def setUp(self):
		super().setUp()
		clock = patch("smart_school.sms.now_datetime", return_value=TEN_AM)  # messages are written at 10:00
		clock.start()
		self.addCleanup(clock.stop)
		self.p1 = frappe.db.get_value("Guardian", {"email": PARENT_1})
		self.p2 = frappe.db.get_value("Guardian", {"email": PARENT_2})
		self.settings(sms_mode=sms.TEST, sms_school_name="Mwanga SS", **{k: v for k, v in sms.DEFAULTS.items() if k != "sms_mode"})
		for guardian in (self.p1, self.p2):
			self.guardian(guardian, sms_opt_in=0)
		# a clean queue: what earlier tests left waiting would go first
		frappe.db.sql("update `tabSMS Outbox` set status = 'Skipped' where status = 'Queued'")

	def settings(self, **values):
		self.addCleanup(frappe.clear_document_cache, "Smart School Settings", "Smart School Settings")
		for fieldname, value in values.items():
			previous = frappe.db.get_single_value("Smart School Settings", fieldname)
			self.addCleanup(frappe.db.set_single_value, "Smart School Settings", fieldname, previous)
			frappe.db.set_single_value("Smart School Settings", fieldname, value)
		frappe.clear_document_cache("Smart School Settings", "Smart School Settings")

	def guardian(self, name, **values):
		previous = frappe.db.get_value("Guardian", name, list(values), as_dict=True)
		self.addCleanup(frappe.db.set_value, "Guardian", name, previous)
		frappe.db.set_value("Guardian", name, values)

	def outbox(self, **filters):
		return frappe.get_all(
			"SMS Outbox",
			filters=filters,
			fields=["name", "status", "error", "phone", "message", "message_type", "guardian", "student", "segments", "send_after", "attempts"],
			order_by="creation asc",
		)

	def receipt(self, student="a", amount=1000):
		payment = pay(self.s[student], "_Test T3", amount)  # on submit: email, and the SMS receipt
		return payment, self.outbox(reference_name=payment.name)


class TestSMSOutbox(SMSTestCase):
	def test_off_writes_nothing(self):
		self.settings(sms_mode=sms.OFF)
		self.guardian(self.p1, sms_opt_in=1)
		_, rows = self.receipt()
		self.assertEqual(rows, [])

	def test_consent_and_numbers(self):
		_, rows = self.receipt()
		self.assertEqual([(r.status, r.error) for r in rows], [(sms.SKIPPED, "The guardian has not agreed to receive SMS")])

		self.guardian(self.p1, sms_opt_in=1)
		for entered in ("+255 754 000 101", "0754000101", "754000101", "255754000101", "+255-754-000-101"):
			self.guardian(self.p1, phone=entered)
			_, rows = self.receipt()
			self.assertEqual((rows[0].status, rows[0].phone), (sms.QUEUED, "255754000101"), entered)
		for entered, reason in (
			("0754 00010", "Not a Tanzanian mobile number: 0754 00010"),
			("+255 22 211 0000", "Not a Tanzanian mobile number: +255 22 211 0000"),  # a landline
			("", "No phone number"),
		):
			self.guardian(self.p1, phone=entered)
			_, rows = self.receipt()
			self.assertEqual((rows[0].status, rows[0].error), (sms.FAILED, reason))

	def test_test_mode_records_without_sending(self):
		self.guardian(self.p1, sms_opt_in=1)
		payment, rows = self.receipt(amount=250000)
		self.assertEqual(rows[0].status, sms.QUEUED)
		self.assertEqual(
			rows[0].message,
			f"Mwanga SS: Tumepokea TZS 250,000 ada ya _Test Student A (_Test T3). Risiti {payment.receipt_number or payment.name}. "
			f"Salio TZS {payment.balance:,.0f}.",
		)
		with patch("smart_school.sms.get_provider", side_effect=AssertionError("Test mode must not send")):
			sms.send_due(TEN_AM)
		self.assertEqual(self.outbox(name=rows[0].name)[0].status, sms.TESTED)

	def test_live_mode_sends_and_tries_again(self):
		self.settings(sms_mode=sms.LIVE)
		self.guardian(self.p1, sms_opt_in=1)
		_, rows = self.receipt()
		provider = FakeProvider(SendResult(False, error="Gateway not reached: Timeout", retryable=True))
		with patch("smart_school.sms.get_provider", return_value=provider):
			sms.send_due(TEN_AM)
			row = self.outbox(name=rows[0].name)[0]
			self.assertEqual((row.status, row.attempts, row.send_after), (sms.QUEUED, 1, TEN_AM + timedelta(minutes=5)))
			sms.send_due(TEN_AM + timedelta(minutes=3))  # not due yet
			self.assertEqual(len(provider.sent), 1)
			sms.send_due(TEN_AM + timedelta(minutes=6))
		self.assertEqual(self.outbox(name=rows[0].name)[0].status, sms.SENT)
		self.assertEqual(provider.sent[-1][0], "255754000101")

		_, rows = self.receipt()
		refused = FakeProvider(SendResult(False, error="Gateway answered 400: bad sender"))
		with patch("smart_school.sms.get_provider", return_value=refused):
			sms.send_due(TEN_AM)
		self.assertEqual(self.outbox(name=rows[0].name)[0].status, sms.FAILED)  # not worth trying again

		_, rows = self.receipt()
		down = FakeProvider(*[SendResult(False, error="Gateway answered 503", retryable=True)] * 3)
		with patch("smart_school.sms.get_provider", return_value=down):
			for minutes in (0, 6, 40):
				sms.send_due(TEN_AM + timedelta(minutes=minutes))
		row = self.outbox(name=rows[0].name)[0]
		self.assertEqual((row.status, row.attempts, row.error), (sms.FAILED, 3, "Gateway answered 503"))

	def test_quiet_hours_hold_messages_until_morning(self):
		self.guardian(self.p1, sms_opt_in=1)
		night = DAY.replace(hour=22, minute=15)
		with patch("smart_school.sms.now_datetime", return_value=night):
			_, rows = self.receipt()
		self.assertEqual(rows[0].send_after, DAY.replace(hour=7) + timedelta(days=1))
		sms.send_due(night + timedelta(minutes=30))
		self.assertEqual(self.outbox(name=rows[0].name)[0].status, sms.QUEUED)
		sms.send_due(DAY.replace(hour=7, minute=5) + timedelta(days=1))
		self.assertEqual(self.outbox(name=rows[0].name)[0].status, sms.TESTED)

	def test_daily_and_monthly_limits(self):
		self.guardian(self.p1, sms_opt_in=1)
		self.guardian(self.p2, sms_opt_in=1)
		used_today, _ = sms.usage(TEN_AM)
		self.settings(sms_daily_limit=used_today + 2)
		names = [self.receipt(s)[1][0].name for s in ("a", "b", "e")]
		sms.send_due(TEN_AM)
		rows = [self.outbox(name=n)[0] for n in names]
		self.assertEqual([r.status for r in rows], [sms.TESTED, sms.TESTED, sms.QUEUED])
		self.assertEqual((rows[2].error, rows[2].send_after), ("Daily SMS limit reached", DAY.replace(hour=7) + timedelta(days=1)))

		# A bulk send that does not fit in what is left of the month cannot be confirmed
		_, used_month = sms.usage(TEN_AM)
		self.settings(sms_monthly_limit=used_month + 1, sms_daily_limit=used_month + 1)
		announcement = self.announcement()
		check = sms.preview(sms.ANNOUNCEMENT, announcement, sms.announcement_recipients(announcement))
		self.assertEqual((check.messages, check.fits_month), (2, False))
		with enforce_roles(), as_user(HEADMASTER):
			self.assertRaisesRegex(frappe.ValidationError, "only 0 are left this month", sms.send_announcement, announcement)

	def test_old_messages_expire_and_off_skips_the_queue(self):
		self.guardian(self.p1, sms_opt_in=1)
		_, rows = self.receipt()
		frappe.db.set_value("SMS Outbox", rows[0].name, "creation", TEN_AM - timedelta(hours=80), update_modified=False)
		sms.send_due(TEN_AM)
		self.assertEqual(self.outbox(name=rows[0].name)[0].error, "Expired: not sent within 72 hours")

		_, rows = self.receipt()
		self.settings(sms_mode=sms.OFF)
		sms.send_due(TEN_AM)
		self.assertEqual(self.outbox(name=rows[0].name)[0].status, sms.SKIPPED)

	def test_withdrawn_consent_before_sending(self):
		self.guardian(self.p1, sms_opt_in=1)
		_, rows = self.receipt()
		frappe.db.set_value("Guardian", self.p1, "sms_opt_in", 0)
		sms.send_due(TEN_AM)
		row = self.outbox(name=rows[0].name)[0]
		self.assertEqual((row.status, row.error), (sms.SKIPPED, "The guardian withdrew consent before it was sent"))

	def test_try_again_uses_the_current_number(self):
		self.guardian(self.p1, sms_opt_in=1, phone="0754 00010")
		_, rows = self.receipt()
		self.assertEqual(rows[0].status, sms.FAILED)
		frappe.db.set_value("Guardian", self.p1, "phone", "0754 000 111")
		with enforce_roles(), as_user(HEADMASTER):
			self.assertEqual(sms.retry([rows[0].name]), 1)
		self.assertEqual((self.outbox(name=rows[0].name)[0].status, self.outbox(name=rows[0].name)[0].phone), (sms.QUEUED, "255754000111"))
		with enforce_roles(), as_user(ACCOUNTANT):
			self.assertRaises(frappe.PermissionError, sms.retry, [rows[0].name])

	def test_templates_are_checked_and_can_be_switched_off(self):
		template = frappe.get_doc("SMS Template", sms.RECEIPT)
		template.message = "{shule}: {mwanafunzi} {jina_la_mzazi}"
		self.assertRaisesRegex(frappe.ValidationError, "jina_la_mzazi", template.save)

		self.addCleanup(frappe.db.set_value, "SMS Template", sms.RECEIPT, "enabled", 1)
		frappe.db.set_value("SMS Template", sms.RECEIPT, "enabled", 0)
		self.guardian(self.p1, sms_opt_in=1)
		_, rows = self.receipt()
		self.assertEqual(rows, [])

	def announcement(self):
		return (
			frappe.get_doc(
				{"doctype": "Announcement", "title": "Mkutano wa wazazi", "message": "Jumamosi saa 3", "audience": "All School", "date": today()}
			)
			.insert(ignore_permissions=True)
			.name
		)


class TestResultsSMS(SMSTestCase):
	def test_results_once_per_student_with_average_and_division_when_complete(self):
		self.guardian(self.p1, sms_opt_in=1)
		main = make_exam("_Test SMS Main", "_Test T1", "_Test FORM 1")
		other = make_exam("_Test SMS Other", "_Test T1", "_Test FORM 1")
		for subject, marks in (("_T MATH", 60), ("_T ENGLISH", 55)):
			add_result(self.s["a"], main, subject, marks)
		term_result = frappe.db.get_value("Student Term Result", {"student": self.s["a"], "term": "_Test T1"})
		frappe.db.set_value("Student Term Result", term_result, "division", "Division II")

		recipients = sms.exam_result_recipients(main)
		values = [v for g, v, s in recipients if s == self.s["a"]][0]
		self.assertEqual((values["wastani"], values["division"]), ("57.5", ""))  # the other exam is not published

		frappe.db.set_value("Exam", other, "results_published", 1)
		self.assertEqual(sms.queue_exam_results(main), [n.name for n in self.outbox(reference_name=main)])
		row = self.outbox(reference_name=main, student=self.s["a"])[0]
		self.assertTrue(row.message.startswith("Mwanga SS: _Test Student A - _Test SMS Main: wastani 57.5%, Division II. Zaidi: "), row.message)
		self.assertTrue(row.message.endswith("/matokeo"))
		self.assertEqual(row.segments, 1)

		# published again after a correction: no second SMS
		self.assertEqual(sms.queue_exam_results(main), [])

	def test_publish_dialog_counts(self):
		self.guardian(self.p1, sms_opt_in=1)
		self.guardian(self.p2, sms_opt_in=0)
		exam = make_exam("_Test SMS Count", "_Test T2", "_Test FORM 1")
		for student in ("a", "b"):
			add_result(self.s[student], exam, "_T MATH", 70)
		with enforce_roles(), as_user(HEADMASTER):
			p = sms.preview_exam_results(exam)
		self.assertEqual((p.mode, p.messages, p.sms, p.cost, p.skipped, p.failed), (sms.TEST, 2, 2, 50, 0, 0))
		self.assertTrue(p.fits_month)
		self.assertEqual(self.outbox(reference_name=exam), [])  # a preview writes nothing
		with enforce_roles(), as_user(TEACHER_1):
			self.assertRaises(frappe.PermissionError, sms.preview_exam_results, exam)

	def test_publishing_without_sms(self):
		self.guardian(self.p1, sms_opt_in=1)
		exam = make_exam("_Test SMS None", "_Test T2", "_Test FORM 1")
		add_result(self.s["a"], exam, "_T MATH", 70)
		with patch("smart_school.notifications.send_notification"):
			from smart_school.results import notify_published_exam

			notify_published_exam(exam, send_sms=0)
			self.assertEqual(self.outbox(reference_name=exam), [])
			notify_published_exam(exam, send_sms=1)
		self.assertEqual(len(self.outbox(reference_name=exam)), 1)


class TestFeeReminders(SMSTestCase):
	def setUp(self):
		super().setUp()
		self.guardian(self.p1, sms_opt_in=1)
		self.guardian(self.p2, sms_opt_in=1)
		# The next academic year's first term starts in 165 days; reminders here start 170 days before a term
		self.settings(sms_fee_days_before_term=170)
		self.next_term = "_Test SMS T4"
		if not frappe.db.exists("Term", self.next_term):
			frappe.get_doc(
				{
					"doctype": "Academic Year",
					"year": "_Test SMS AY",
					"start_date": add_days(today(), 161),
					"end_date": add_days(today(), 400),
				}
			).insert(ignore_permissions=True, set_name="_Test SMS AY")
			frappe.get_doc(
				{
					"doctype": "Term",
					"term_name": "Term 1",
					"academic_year": "_Test SMS AY",
					"start_date": add_days(today(), 165),
					"end_date": add_days(today(), 250),
				}
			).insert(ignore_permissions=True, set_name=self.next_term)
			for class_name in ("_Test FORM 1", "_Test FORM 2"):
				frappe.get_doc({"doctype": "Fee Structure", "class": class_name, "term": self.next_term, "amount": 500000}).insert(
					ignore_permissions=True
				)

	def leave(self, student, exit_date, status="Transferred"):
		previous = frappe.db.get_value("Student", self.s[student], ["status", "exit_date"], as_dict=True)
		self.addCleanup(frappe.db.set_value, "Student", self.s[student], previous)
		self.addCleanup(frappe.clear_document_cache, "Student", self.s[student])
		frappe.db.set_value("Student", self.s[student], {"status": status, "exit_date": exit_date})
		frappe.clear_document_cache("Student", self.s[student])

	def test_before_term_not_for_students_who_left(self):
		self.leave("b", today())
		by_term = sms.fee_reminder_recipients(sms.FEE_BEFORE_TERM)
		self.assertEqual(list(by_term), [self.next_term])
		students = {s for _, _, s in by_term[self.next_term]}
		self.assertIn(self.s["a"], students)
		self.assertNotIn(self.s["b"], students)
		values = next(v for _, v, s in by_term[self.next_term] if s == self.s["a"])
		self.assertEqual(values["kiasi"], "500,000")
		self.assertTrue(values["deni"].startswith("; deni la nyuma TZS "))

		# nothing earlier than 170 days before the term
		self.assertNotIn(self.next_term, sms.fee_reminder_recipients(sms.FEE_BEFORE_TERM, add_days(today(), -10)))

	def test_overdue_only_for_terms_before_leaving(self):
		start = getdate(frappe.db.get_value("Term", "_Test T3", "start_date"))  # a few days ago
		days = (getdate(today()) - start).days
		self.settings(sms_fee_overdue_days=days - 1)
		self.leave("b", add_days(start, -2))  # left before _Test T3 started: owes nothing for it
		by_term = sms.fee_reminder_recipients(sms.FEE_OVERDUE)
		students = {s for _, _, s in by_term["_Test T3"]}
		self.assertIn(self.s["a"], students)
		self.assertNotIn(self.s["b"], students)
		values = next(v for _, v, s in by_term["_Test T3"] if s == self.s["a"])
		self.assertEqual(values["siku"], str(days))

		self.leave("b", add_days(start, 1))  # left during _Test T3: still owes for it
		self.assertIn(self.s["b"], {s for _, _, s in sms.fee_reminder_recipients(sms.FEE_OVERDUE)["_Test T3"]})

		self.settings(sms_fee_overdue_days=days + 1)  # not yet
		self.assertNotIn("_Test T3", sms.fee_reminder_recipients(sms.FEE_OVERDUE))

	def test_only_when_switched_on_and_once(self):
		self.settings(sms_fee_reminder_before_term=0, sms_fee_reminder_overdue=0)
		sms.send_fee_reminders()
		self.assertEqual(self.outbox(message_type=sms.FEE_BEFORE_TERM), [])

		self.settings(sms_fee_reminder_before_term=1)
		with enforce_roles(), as_user(HEADMASTER):
			p = sms.preview_fee_reminders(sms.FEE_BEFORE_TERM)
		sms.send_fee_reminders()
		rows = self.outbox(message_type=sms.FEE_BEFORE_TERM)
		self.assertEqual(len(rows), p.messages)
		self.assertTrue(rows and all(r.segments == 1 for r in rows))
		sms.send_fee_reminders()  # the next day's run: no second reminder for the same term
		self.assertEqual(len(self.outbox(message_type=sms.FEE_BEFORE_TERM)), len(rows))


class TestNoSensitiveSMS(SMSTestCase):
	def test_only_the_five_types_and_never_sensitive_records(self):
		for doctype in sms.FORBIDDEN_DOCTYPES:
			self.assertRaises(frappe.ValidationError, sms.assert_allowed, sms.RESULTS, doctype)
		self.assertRaises(frappe.ValidationError, sms.assert_allowed, "Early Warning", "Risk Prediction")
		self.assertRaises(frappe.ValidationError, sms.queue_messages, "Early Warning", "x", [])
		self.assertRaises(frappe.ValidationError, sms.assert_allowed, sms.RESULTS, "Student Intervention")
		options = frappe.get_meta("SMS Outbox").get_field("message_type").options.split("\n")
		self.assertEqual(tuple(options), sms.MESSAGE_TYPES)
		self.assertFalse(set(sms.REFERENCE_DOCTYPE.values()) & set(sms.FORBIDDEN_DOCTYPES))

	def test_discipline_and_interventions_write_no_sms(self):
		self.guardian(self.p1, sms_opt_in=1)
		before = frappe.db.count("SMS Outbox")
		frappe.get_doc(
			{"doctype": "Discipline Record", "student": self.s["a"], "date": today(), "incident_type": "Fighting", "severity": "Serious"}
		).insert(ignore_permissions=True)
		frappe.get_doc(
			{
				"doctype": "Student Intervention",
				"student": self.s["a"],
				"term": "_Test T3",
				"intervention_type": "Counseling",
				"responsible": HEADMASTER,
				"start_date": today(),
				"status": "Planned",
			}
		).insert(ignore_permissions=True)
		self.assertEqual(frappe.db.count("SMS Outbox"), before)

	def test_sms_are_only_written_from_the_sms_module(self):
		"""queue_messages is called only inside smart_school/sms.py, whose callers are the five types."""
		app = Path(frappe.get_app_path("smart_school"))
		callers = []
		for path in app.rglob("*.py"):
			if "tests" in path.parts or path.name == "sms.py":
				continue
			for node in ast.walk(ast.parse(path.read_text())):
				if isinstance(node, ast.Call) and getattr(node.func, "attr", getattr(node.func, "id", None)) == "queue_messages":
					callers.append(str(path))
		self.assertEqual(callers, [])


class TestConsent(SMSTestCase):
	def test_admission_portal_and_paper(self):
		admission = frappe.get_doc(
			{
				"doctype": "Student Admission",
				"full_name": "_Test SMS Applicant",
				"gender": "Female",
				"date_of_birth": "2012-01-01",
				"class_applying": "_Test FORM 1",
				"parent_name": "_Test SMS Parent",
				"phone_number": "+255-754999001",
				"sms_opt_in": 1,
				"birth_certificate_verified": 1,
			}
		).insert(ignore_permissions=True)
		admission.status = "Approved"
		admission.save(ignore_permissions=True)
		guardian = frappe.get_doc("Guardian", {"phone": "+255-754999001"})
		self.assertEqual((guardian.sms_opt_in, guardian.sms_opt_in_source), (1, "Admission"))

		# The parent's own switch on the portal: only their own record
		with as_user(PARENT_1):
			sms.set_my_consent(1)
		self.assertEqual(frappe.db.get_value("Guardian", self.p1, ["sms_opt_in", "sms_opt_in_source"]), (1, "Portal"))
		with as_user(PARENT_1):
			sms.set_my_consent(0)
		self.assertEqual(frappe.db.get_value("Guardian", self.p1, "sms_opt_in"), 0)
		self.assertEqual(frappe.db.get_value("Guardian", self.p2, "sms_opt_in"), 0)

		# Paper forms, many at once, by the Headmaster, with the date on the form
		paper_day = add_days(today(), -3)
		with enforce_roles(), as_user(HEADMASTER):
			self.assertEqual(sms.set_consent_for_guardians([self.p1, self.p2], 1, paper_day), 2)
			self.assertRaises(frappe.ValidationError, sms.set_consent_for_guardians, [self.p1], 1, add_days(today(), 1))
		for guardian in (self.p1, self.p2):
			self.assertEqual(
				frappe.db.get_value("Guardian", guardian, ["sms_opt_in", "sms_opt_in_source", "sms_opt_in_date", "sms_opt_in_by"]),
				(1, "Staff", getdate(paper_day), HEADMASTER),
			)
		for user in (TEACHER_1, ACCOUNTANT, PARENT_1):
			with enforce_roles(), as_user(user):
				self.assertRaises(frappe.PermissionError, sms.set_consent_for_guardians, [self.p2], 0)

	def test_portal_switch_shows_the_end_of_the_number_only(self):
		from smart_school.tests.factory import render

		with as_user(PARENT_1):
			status, body, _ = render("parent-portal")
		self.assertEqual(status, 200)
		self.assertIn('id="sms-opt-in"', body)
		self.assertIn("inayoishia <b>101</b>", body)
		self.assertNotIn("754 000 101", body)

	def test_unticked_admission_keeps_an_existing_guardians_choice(self):
		self.guardian(self.p1, sms_opt_in=1)
		phone = frappe.db.get_value("Guardian", self.p1, "phone")
		admission = frappe.get_doc(
			{
				"doctype": "Student Admission",
				"full_name": "_Test SMS Sibling",
				"date_of_birth": "2013-01-01",
				"class_applying": "_Test FORM 1",
				"parent_name": "_Test Parent One",
				"phone_number": phone,
				"birth_certificate_verified": 1,
			}
		).insert(ignore_permissions=True)
		admission.status = "Approved"
		admission.save(ignore_permissions=True)
		self.assertEqual(frappe.db.get_value("Guardian", self.p1, "sms_opt_in"), 1)


class TestSMSPermissions(SMSTestCase):
	def test_who_sees_the_outbox_and_the_report(self):
		from smart_school.an_intergrated_academic_management_system.report.sms_summary import sms_summary

		self.guardian(self.p1, sms_opt_in=1)
		self.receipt()
		announcement = TestSMSOutbox.announcement(self)
		sms.queue_messages(sms.ANNOUNCEMENT, announcement, sms.announcement_recipients(announcement))
		sms.send_due(TEN_AM)

		def visible(user):
			with as_user(user):
				try:
					return {r.message_type for r in frappe.get_list("SMS Outbox", fields=["message_type"])}
				except frappe.PermissionError:
					return set()

		self.assertEqual(visible(HEADMASTER), {sms.RECEIPT, sms.ANNOUNCEMENT})
		self.assertEqual(visible(ACCOUNTANT), {sms.RECEIPT})
		self.assertEqual(visible(TEACHER_1), set())
		self.assertEqual(visible(PARENT_1), set())

		with enforce_roles(), as_user(ACCOUNTANT):
			_, rows, _, _, summary = sms_summary.execute({})
		self.assertEqual({r.message_type for r in rows}, {sms.RECEIPT})
		self.assertEqual(summary, [])
		with enforce_roles(), as_user(HEADMASTER):
			_, rows, _, chart, summary = sms_summary.execute({})
		tested = [r for r in rows if r.status == sms.TESTED]
		self.assertTrue(tested and all(r.cost == r.sms * 25 for r in tested))
		self.assertEqual(summary[0]["value"], sms.TEST)
		with enforce_roles(), as_user(make_user("_test.sms.teacher@example.com", "Teacher")):
			self.assertRaises(frappe.PermissionError, sms_summary.execute, {})
