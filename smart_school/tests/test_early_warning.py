"""Early Warning report and Emerging Risk card: the two groups, who sees which class, the rule-based fallback,
and that parents never see anything of the model."""

import frappe

from smart_school import reports
from smart_school.risk_model import FEATURE_SET_VERSION
from smart_school.tests.factory import (
	ACCOUNTANT,
	HEADMASTER,
	PARENT_1,
	TEACHER_1,
	TEACHER_2,
	SchoolTestCase,
	as_user,
	enforce_roles,
	render,
)

EARLY_WARNING = (
	"smart_school.an_intergrated_academic_management_system.report.early_warning.early_warning.execute"
)
MODEL_PERFORMANCE = (
	"smart_school.an_intergrated_academic_management_system.report.model_performance.model_performance.execute"
)
MARKER = "Marker reason only staff may read"


class TestEarlyWarning(SchoolTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.model = frappe.get_doc(
			{
				"doctype": "Risk Model",
				"status": "Active",
				"feature_set_version": FEATURE_SET_VERSION,
				"trained_on": frappe.utils.now_datetime(),
			}
		).insert(ignore_permissions=True).name
		s = cls.s
		for student, class_name, probability, level, at_risk_now in (
			(s["a"], "_Test FORM 1", 75, "High", 0),  # not at risk yet, model high: emerging
			(s["b"], "_Test FORM 1", 45, "Medium", 1),  # already at risk
			(s["c"], "_Test FORM 1", 10, "Low", 0),  # neither
			(s["e"], "_Test FORM 2", 40, "Medium", 0),  # emerging, in the other class
		):
			frappe.get_doc(
				{
					"doctype": "Risk Prediction",
					"student": student,
					"class": class_name,
					"term": "_Test T3",
					"feature_term": "_Test T2",
					"probability": probability,
					"probability_level": level,
					"at_risk_now": at_risk_now,
					"reasons": f"{MARKER}\nSecond reason",
					"rule_score": 20,
					"rule_level": "Low",
					"risk_model": cls.model,
				}
			).insert(ignore_permissions=True)

	def run_report(self, user, **filters):
		with as_user(user), enforce_roles():
			return frappe.get_attr(EARLY_WARNING)(filters)

	def test_headmaster_sees_both_groups_in_every_class(self):
		columns, data, message, _, summary = self.run_report(HEADMASTER)
		self.assertEqual(
			[(r["student"], r["section"]) for r in data],
			[
				(self.s["a"], reports.EMERGING),
				(self.s["e"], reports.EMERGING),
				(self.s["b"], reports.ALREADY_AT_RISK),
			],
		)
		self.assertEqual([c["value"] for c in summary], [2, 1])
		self.assertEqual((data[0]["probability"], data[0]["level"], data[0]["reason_1"]), (75, "High", MARKER))
		self.assertEqual(data[0]["rule_score"], 20)  # the rule-based score beside it
		self.assertIn("_Test T3", message)

		_, data, *_ = self.run_report(HEADMASTER, section=reports.ALREADY_AT_RISK)
		self.assertEqual([r["student"] for r in data], [self.s["b"]])
		_, data, *_ = self.run_report(HEADMASTER, level="Medium")
		self.assertEqual([r["student"] for r in data], [self.s["e"], self.s["b"]])

	def test_class_teacher_sees_only_their_class(self):
		_, data, *_ = self.run_report(TEACHER_2)  # class teacher of _Test FORM 2
		self.assertEqual([r["student"] for r in data], [self.s["e"]])
		self.assertRaises(frappe.PermissionError, self.run_report, TEACHER_2, **{"class": "_Test FORM 1"})

	def test_others_are_refused(self):
		for user in (TEACHER_1, PARENT_1, ACCOUNTANT):  # Teacher One is not a class teacher
			with self.subTest(user=user):
				self.assertRaises(frappe.PermissionError, self.run_report, user)
		for user in (TEACHER_2, PARENT_1, ACCOUNTANT):
			with self.subTest(user=user), as_user(user), enforce_roles():
				self.assertRaises(frappe.PermissionError, reports.get_emerging_risk_count)
				self.assertRaises(frappe.PermissionError, frappe.get_attr(MODEL_PERFORMANCE), {})

	def test_emerging_risk_card(self):
		with as_user(HEADMASTER), enforce_roles():
			self.assertEqual(reports.get_emerging_risk_count()["value"], 2)

	def test_rule_based_when_no_model_is_in_use(self):
		frappe.db.set_value("Risk Model", self.model, {"status": "Rejected", "decision": "Not better."})
		self.addCleanup(frappe.db.set_value, "Risk Model", self.model, "status", "Active")
		frappe.db.set_value("Student", self.s["e"], {"risk_score": 65, "risk_level": "High"})
		frappe.db.set_value("Student", self.s["a"], {"risk_score": 40, "risk_level": "Medium"})

		_, data, message = self.run_report(HEADMASTER)
		self.assertIn("No prediction model is in use. Not better.", message)
		self.assertEqual([(r["student"], r["section"]) for r in data], [(self.s["e"], "Rule-based"), (self.s["a"], "Rule-based")])
		_, data, _ = self.run_report(TEACHER_2)
		self.assertEqual([r["student"] for r in data], [self.s["e"]])
		with as_user(HEADMASTER), enforce_roles():
			self.assertEqual(reports.get_emerging_risk_count()["value"], 0)

	def test_parents_see_nothing_of_the_model(self):
		self.assertFalse(frappe.has_permission("Risk Prediction", "read", user=PARENT_1))
		with as_user(PARENT_1):
			for path, args in (
				("parent-portal", {}),
				("parent-portal/student", {"student": self.s["a"]}),
				("parent-portal/results", {"student": self.s["a"]}),
			):
				with self.subTest(path=path):
					status, body, _ = render(path, **args)
					self.assertEqual(status, 200)
					self.assertNotIn(MARKER, body)
					self.assertNotIn("Probability", body)
					self.assertNotIn("Wanaoanza kushuka", body)
