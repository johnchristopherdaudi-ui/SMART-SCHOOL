"""Report card verification: random tokens, one token per unchanged card, the public page (valid, changed,
invalid, rate limited, nothing extra), revoking, drafts without a QR, and the QR in the PDF."""

import base64
import io
import re
from unittest.mock import patch

import frappe
from pypdf import PdfReader

from smart_school import report_card, verification
from smart_school.tests.factory import (
	HEADMASTER,
	PARENT_1,
	SUBJECTS,
	TEACHER_1,
	SchoolTestCase,
	add_result,
	as_user,
	call,
	enforce_roles,
	make_exam,
	render,
)

REVOKE = "smart_school.verification.revoke"


class TestReportCardVerification(SchoolTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.mid = make_exam("_Test RV Mid", "_Test T1", "_Test FORM 1", max_marks=50, weight=40, published=1)
		cls.final = make_exam("_Test RV Final", "_Test T1", "_Test FORM 1", weight=60, published=1)
		cls.finals = {}
		for key, mark in (("a", 80), ("b", 60)):
			for subject in SUBJECTS[:7]:
				add_result(cls.s[key], cls.mid, subject, mark / 2)
				cls.finals[(key, subject)] = add_result(cls.s[key], cls.final, subject, mark)
		result = lambda key: frappe.db.get_value("Student Term Result", {"student": cls.s[key], "term": "_Test T1"}, "name")
		cls.result, cls.result_b = result("a"), result("b")

	def setUp(self):
		super().setUp()
		frappe.cache.delete(frappe.cache.make_key("smart_school:verify:unknown"))  # the rate limit counter

	def issue(self, result=None):
		return verification.get_verification(frappe.get_doc("Student Term Result", result or self.result))

	def unpublish_final(self):
		frappe.db.set_value("Exam", self.final, "results_published", 0)
		self.addCleanup(frappe.db.set_value, "Exam", self.final, "results_published", 1)

	def page(self, token):
		"""(status, the verification part of the page): Frappe's own template carries icons and scripts."""
		with as_user("Guest"):
			status, body, _ = render(f"verify/{token}")
		if "<!-- /verification -->" not in body:  # not this page at all (e.g. Frappe's own 404)
			return status, body, body
		return status, body[body.index('<div class="vf">') : body.index("<!-- /verification -->")], body

	def change_mark(self, key, subject, marks):
		"""Amend a Final exam mark (a correction after publishing). Each test changes its own student or subject."""
		old = self.finals[(key, subject)]
		old.reload()
		old.flags.ignore_permissions = True
		old.cancel()
		new = frappe.copy_doc(old)
		new.docstatus, new.amended_from, new.marks = 0, old.name, marks
		new.insert(ignore_permissions=True)
		new.submit()
		self.finals[(key, subject)] = new

	def test_tokens_are_long_random_and_say_nothing(self):
		tokens = {verification.new_token() for _ in range(1000)}
		self.assertEqual(len(tokens), 1000)
		self.assertTrue(all(verification.TOKEN_PATTERN.match(t) and len(t) >= 20 for t in tokens))
		token = self.issue().token
		for hint in (self.s["a"], "_Test Student A", "_Test T1", self.result):
			self.assertNotIn(hint.lower(), token.lower())

	def test_same_card_keeps_its_token_and_a_hidden_mark_change_is_seen(self):
		first = self.issue().token
		records = frappe.db.count("Report Card Verification")
		self.assertEqual(self.issue().token, first)  # printed again, results unchanged
		self.assertEqual(frappe.db.count("Report Card Verification"), records)

		# 80 -> 81 in the Final: maths goes from 80.0% to 80.6%, still an A
		self.change_mark("a", "_T MATH", 81)
		second = self.issue().token
		self.assertNotEqual(second, first)

		view = verification.get_verification_view(first)
		self.assertEqual(view.status, "changed")
		math = lambda results: next(s for s in results["subjects"] if s["subject"] == "_T MATH")
		self.assertEqual((math(view.issued.results)["score"], math(view.issued.results)["grade"]), (80.0, "A"))
		self.assertEqual((math(view.current)["score"], math(view.current)["grade"]), (80.6, "A"))
		status, body, _ = self.page(first)
		self.assertIn("Matokeo yamebadilika", body)
		self.assertIn("80.0", body)
		self.assertIn("80.6", body)
		self.assertEqual(verification.get_verification_view(second).status, "valid")

	def test_changed_results_are_hidden_until_published(self):
		token = self.issue(self.result_b).token
		self.change_mark("b", "_T ENGLISH", 90)
		self.unpublish_final()
		view = verification.get_verification_view(token)
		self.assertEqual((view.status, view.current, view.current_hidden), ("changed", None, True))
		status, body, _ = self.page(token)
		self.assertIn("Shule inarekebisha matokeo haya", body)
		self.assertIn("60.0", body)  # what the card showed
		self.assertNotIn("78.0", body)  # the unpublished new score: 40% x 60 + 60% x 90

	def test_valid_page_shows_only_what_the_card_certifies(self):
		token = self.issue().token
		status, body, whole = self.page(token)
		self.assertEqual(status, 200)
		self.assertIn('<meta name="robots" content="noindex, nofollow">', whole)
		for text in (
			"Report card hii ni halali",
			"_Test Student A",
			"_Test FORM 1",
			"Term 1",
			"_T MATH",
			"80.0",
			frappe.db.get_value("Student Term Result", self.result, "division_display"),
		):
			self.assertIn(text, body)
		for private in (  # nothing else about the student, in the page or in Frappe's template around it
			self.s["a"],  # admission number
			"+255 754 000 101",  # guardian phone
			PARENT_1,
			"TZS",
			"Ada",
			"Nidhamu",
			"Position",
			"Mahudhurio",
		):
			self.assertNotIn(private, whole)

	def test_unknown_or_revoked_token_is_not_valid(self):
		status, body, _ = self.page(verification.new_token())
		self.assertEqual(status, 404)
		self.assertIn("Report card hii si halali", body)
		self.assertEqual(self.page("../../etc")[0], 404)

		record = frappe.get_doc("Report Card Verification", {"token": self.issue().token})
		for user in (TEACHER_1, PARENT_1):
			with self.subTest(user=user), as_user(user), enforce_roles():
				self.assertRaises(frappe.PermissionError, call, REVOKE, name=record.name, reason="x")
				self.assertFalse(frappe.has_permission("Report Card Verification", "read", user=user))
		with as_user(HEADMASTER), enforce_roles():
			self.assertRaises(frappe.ValidationError, call, REVOKE, name=record.name, reason=" ")
			call(REVOKE, name=record.name, reason="Printed with a typo")
		record.reload()
		self.assertEqual((record.revoked, record.revoked_by), (1, HEADMASTER))
		self.assertEqual(self.page(record.token)[0], 404)
		self.assertNotEqual(self.issue().token, record.token)  # a reprint gets a new token

	def test_draft_before_every_exam_is_published(self):
		records = frappe.db.count("Report Card Verification")
		self.unpublish_final()
		rc = report_card.get_report_card_data(self.result)
		self.assertTrue(rc.is_draft)
		self.assertIsNone(rc.qr)
		html = frappe.get_print("Student Term Result", self.result, "Report Card")
		self.assertIn("RASIMU / DRAFT", html)
		self.assertNotIn("/verify/", html)
		self.assertEqual(frappe.db.count("Report Card Verification"), records)  # no record for a draft

	def test_qr_code_is_in_the_pdf(self):
		from pyqrcode import create

		rc = report_card.get_report_card_data(self.result)
		self.assertFalse(rc.is_draft)
		self.assertTrue(rc.verify_url.endswith(f"/verify/{rc.verify_url.rsplit('/', 1)[1]}"))
		svg = base64.b64decode(rc.qr.split(",", 1)[1]).decode()
		expected = io.BytesIO()
		create(rc.verify_url, error="M").svg(expected, scale=3, module_color="#000", background="#fff", xmldecl=False)
		self.assertEqual(svg, expected.getvalue().decode())  # the QR encodes the verification address

		html = frappe.get_print("Student Term Result", self.result, "Report Card")
		self.assertIn(rc.qr, html)
		pdf = PdfReader(io.BytesIO(report_card.render_pdf(self.result)))
		text = re.sub(r"\s+", "", "".join(page.extract_text() for page in pdf.pages))
		self.assertIn(rc.verify_url.rsplit("/", 1)[1], text)  # the address printed under the QR code

	def test_portal_download_records_the_channel(self):
		# An unchanged card keeps the record of its first issue, so start without one
		frappe.db.set_value("Report Card Verification", {"student": self.s["a"]}, "revoked", 1)
		with as_user(PARENT_1):
			frappe.local.response = frappe._dict()
			call("smart_school.report_card.download_report_card", student=self.s["a"], term="_Test T1")
		latest = frappe.get_all(
			"Report Card Verification", filters={"student": self.s["a"]}, pluck="issued_via", order_by="creation desc"
		)
		self.assertIn("Portal PDF", latest)
		self.assertIsNone(frappe.flags.report_card_channel)

	def test_rate_limit(self):
		token = self.issue().token
		with patch.object(verification, "RATE_LIMIT", 2):
			self.assertEqual(self.page(token)[0], 200)
			self.assertEqual(self.page(token)[0], 200)
			status, body, _ = self.page(token)
		self.assertEqual(status, 429)
		self.assertIn("Maombi mengi mno", body)
		self.assertNotIn("_Test Student A", body)
