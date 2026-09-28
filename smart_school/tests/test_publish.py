"""#12, #15, D4: publishing exams, what parents see, and one notification per student."""

from unittest.mock import patch

import frappe

from smart_school import results
from smart_school.results import get_portal_results
from smart_school.tests.factory import (
	HEADMASTER,
	PARENT_1,
	TEACHER_1,
	SchoolTestCase,
	add_result,
	as_user,
	enforce_roles,
	call,
	make_exam,
	render,
)

PUBLISH = "smart_school.results.publish_exam_results"


class TestPublishing(SchoolTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.mid = make_exam("_Test Pub Mid", "_Test T1", "_Test FORM 1", weight=40)
		cls.final = make_exam("_Test Pub Final", "_Test T1", "_Test FORM 1", weight=60)
		for student in (cls.s["a"], cls.s["b"]):
			for subject in ("_T MATH", "_T ENGLISH"):
				add_result(student, cls.mid, subject, 60)
				add_result(student, cls.final, subject, 60)

	def publish(self, exam, user=HEADMASTER):
		with as_user(user), enforce_roles(), patch("frappe.enqueue") as enqueue:
			call(PUBLISH, exam=exam)
		return enqueue

	def test_only_headmaster_or_system_manager_publish(self):
		for user in (PARENT_1, TEACHER_1):
			self.assertRaises(frappe.PermissionError, self.publish, self.mid, user)

	def test_parent_sees_published_exams_only_and_summary_when_all_published(self):
		with as_user(PARENT_1):
			self.assertEqual([t.term for t in get_portal_results(self.s["a"])], [])

		enqueue = self.publish(self.mid)
		enqueue.assert_called_once()
		self.assertEqual(enqueue.call_args.kwargs["exam"], self.mid)
		self.assertRaises(frappe.ValidationError, self.publish, self.mid)  # already published

		with as_user(PARENT_1):
			term = get_portal_results(self.s["a"])[0]
			self.assertEqual([e.exam_name for e in term.exams], ["_Test Pub Mid"])
			self.assertEqual([r.score for r in term.rows], [None, None])  # no term score before all are published
			self.assertIsNone(term.summary)
			status, body, _ = render("parent-portal/results", student=self.s["a"])
			self.assertIn("_Test Pub Mid", body)
			self.assertNotIn("_Test Pub Final", body)

		self.publish(self.final)
		with as_user(PARENT_1):
			self.assertIsNotNone(get_portal_results(self.s["a"])[0].summary)

	def test_publish_requires_weights_to_add_up(self):
		exam = make_exam("_Test Pub Half", "_Test T1", "_Test FORM 2", weight=50)
		self.assertRaises(frappe.ValidationError, self.publish, exam)

	def test_one_notification_per_student(self):
		with patch("smart_school.notifications.send_notification") as send:
			results.notify_published_exam(self.mid)
		students = [c.args[0] for c in send.call_args_list]
		with_results = frappe.get_all(
			"Exam Result", filters={"exam": self.mid, "docstatus": 1}, pluck="student", distinct=True
		)
		self.assertEqual(sorted(students), sorted(with_results))  # exactly one message each
		self.assertIn("_T ENGLISH", send.call_args_list[0].args[1])
		self.assertIn("_T MATH", send.call_args_list[0].args[1])

	def test_no_notification_per_result(self):
		with patch("smart_school.notifications.send_notification") as send:
			add_result(self.s["c"], self.mid, "_T MATH", 55)
		send.assert_not_called()

	def test_portal_table_has_one_row_per_subject(self):
		for exam in (self.mid, self.final):  # another test may have published them already
			if not frappe.db.get_value("Exam", exam, "results_published"):
				self.publish(exam)
		single = make_exam("_Test Pub Single", "_Test T2", "_Test FORM 1")
		add_result(self.s["a"], single, "_T MATH", 72)
		self.publish(single)

		with as_user(PARENT_1):
			by_term = {t.term: t for t in get_portal_results(self.s["a"])}
			weighted, one = by_term["_Test T1"], by_term["_Test T2"]
			self.assertEqual([e.exam_name for e in weighted.exams], ["_Test Pub Mid", "_Test Pub Final"])
			math = next(r for r in weighted.rows if r.subject == "_T MATH")
			self.assertEqual((math.marks, math.score, math.grade, math.points), ([60, 60], 60, "C", 3))
			self.assertEqual(
				weighted.weights_note,
				"Alama ya term = _Test Pub Mid 40% + _Test Pub Final 60% (kwa asilimia ya kila mtihani).",
			)
			self.assertEqual([e.exam_name for e in one.exams], ["_Test Pub Single"])  # one exam: one column
			self.assertEqual(one.weights_note, "Alama ya term ni alama ya _Test Pub Single.")

			status, body, _ = render("parent-portal/results", student=self.s["a"])
			self.assertEqual(status, 200)
			self.assertIn("Alama ya Term", body)
			self.assertIn("_Test Pub Mid 40% + _Test Pub Final 60%", body)
