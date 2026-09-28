"""Student interventions: who may see and change them, the Early Warning snapshot, follow-up reminders, the
Early Warning "Hatua" column, and the Intervention Outcomes comparison (matching, both designs, intervals)."""

import random
from unittest.mock import patch

import frappe
from frappe.utils import add_days, today

from smart_school import intervention_outcomes as io
from smart_school import interventions
from smart_school.reports import EMERGING
from smart_school.risk_model import FEATURE_SET_VERSION
from smart_school.tests.factory import (
	ACCOUNTANT,
	HEADMASTER,
	PARENT_2,
	TEACHER_1,
	TEACHER_2,
	SchoolTestCase,
	as_user,
	call,
	enforce_roles,
	render,
)

CREATE = "smart_school.interventions.create_from_early_warning"
EARLY_WARNING = (
	"smart_school.an_intergrated_academic_management_system.report.early_warning.early_warning.execute"
)
OUTCOMES = (
	"smart_school.an_intergrated_academic_management_system.report.intervention_outcomes."
	"intervention_outcomes.execute"
)
MARKER = "Private note for the class teacher only"


def synthetic_rows(seed=1, effect=4.0, completed_share=0.8, students=600, terms=("T-A", "T-B")):
	"""Rows like collect_rows(): risk drives both selection (more often chosen) and the change (weaker students
	bounce back: regression to the mean); Completed interventions add `effect` to the change."""
	rng = random.Random(seed)
	rows = []
	for term in terms:
		for n in range(students):
			score = rng.random()
			chosen = rng.random() < 0.05 + 0.7 * score**2
			status = ("Completed" if rng.random() < completed_share else "Cancelled") if chosen else None
			kind = rng.choice(["Counseling", "Parent Meeting"]) if chosen else None
			change = 8 * score + rng.gauss(0, 4) + (effect if status == "Completed" else 0)
			rows.append(
				frappe._dict(
					student=f"S{n}",
					term=term,
					score=score,
					avg_t=60 - 40 * score,
					absence_t=0.05 + 0.2 * score,
					positive=int(rng.random() < 0.6 * score),
					change=change,
					interventions=[frappe._dict(status=status, intervention_type=kind)] if chosen else [],
				)
			)
	io.assign_deciles(rows)
	return rows


class TestInterventionAnalysis(SchoolTestCase):
	def test_matching_finds_the_planted_effect_and_raw_comparison_does_not(self):
		rows = synthetic_rows()
		result = io.analyse(rows, min_sample=20)
		pp = result["designs"]["per_protocol"]["outcomes"]["change"]
		itt = result["designs"]["itt"]["outcomes"]["change"]
		self.assertTrue(pp["ci"][0] <= 4 <= pp["ci"][1], pp)
		share = sum(1 for r in rows for i in r.interventions if i.status == "Completed") / sum(
			1 for r in rows if r.interventions
		)
		self.assertTrue(itt["ci"][0] <= 4 * share <= itt["ci"][1], itt)
		self.assertLess(itt["effect"], pp["effect"])  # cancelled interventions dilute it
		self.assertGreater(pp["raw"], pp["ci"][1])  # regression to the mean inflates the raw difference

		balance = result["balance"]["per_protocol"]["avg_t"]
		self.assertGreater(abs(balance["treated"] - balance["comparison_before"]), 10)
		self.assertLess(abs(balance["treated"] - balance["comparison_after"]), 3)

	def test_comparison_group_is_same_term_same_decile_no_intervention(self):
		done = frappe._dict(status="Completed", intervention_type="Counseling")
		cancelled = frappe._dict(status="Cancelled", intervention_type="Counseling")
		row = lambda interventions: frappe._dict(interventions=interventions)
		self.assertEqual(io.arm(row([]), "per_protocol"), 0)
		self.assertEqual(io.arm(row([cancelled]), "per_protocol"), None)  # left out of per-protocol
		self.assertEqual(io.arm(row([cancelled]), "itt"), 1)
		self.assertEqual(io.arm(row([done]), "per_protocol", "Parent Meeting"), None)

		rows = synthetic_rows(students=100)
		self.assertEqual({r.decile for r in rows if r.term == "T-A"}, set(range(1, 11)))
		# a treated student alone in a stratum is left out and counted
		lonely = frappe._dict(
			student="X", term="T-C", score=1, avg_t=0, absence_t=0, positive=1, change=0, decile=1,
			interventions=[done],
		)
		counts = io.Design([*rows, lonely], "per_protocol").counts()
		self.assertEqual(counts["treated_left_out"], 1)

	def test_types_need_the_minimum_sample(self):
		result = io.analyse(synthetic_rows(students=150), min_sample=10_000)
		self.assertTrue(result["types"])
		self.assertFalse(any(t["enough"] for t in result["types"].values()))

	def test_report_warns_and_shows_both_designs(self):
		with patch.object(io, "collect_rows", return_value=(synthetic_rows(), "model RM-TEST")), patch(
			"smart_school.an_intergrated_academic_management_system.report.intervention_outcomes."
			"intervention_outcomes.collect_rows",
			return_value=(synthetic_rows(), "model RM-TEST"),
		), as_user(HEADMASTER), enforce_roles():
			columns, data, message = frappe.get_attr(OUTCOMES)({})
		self.assertIn("An observational comparison, not proof that interventions work", message)
		self.assertIn("regression to the mean", message)
		sections = {r["section"] for r in data}
		self.assertTrue({"Per-protocol (Completed)", "Intention-to-treat (all interventions)", "Balance"} <= sections)
		by_type = [r for r in data if r["section"] == "By type (per-protocol)"]
		self.assertTrue(by_type)
		self.assertTrue(all("by chance" in r["note"] or "no estimate" in r["note"] for r in by_type))
		for user in (TEACHER_2, ACCOUNTANT):
			with as_user(user), enforce_roles():
				self.assertRaises(frappe.PermissionError, frappe.get_attr(OUTCOMES), {})


class TestInterventions(SchoolTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.model = frappe.get_doc(
			{"doctype": "Risk Model", "status": "Active", "feature_set_version": FEATURE_SET_VERSION}
		).insert(ignore_permissions=True).name
		frappe.get_doc(
			{
				"doctype": "Risk Prediction",
				"student": cls.s["e"],
				"class": "_Test FORM 2",
				"term": "_Test T3",
				"feature_term": "_Test T2",
				"probability": 45,
				"probability_level": "Medium",
				"at_risk_now": 0,
				"reasons": "Average of 40% (school average 55%)",
				"rule_score": 20,
				"rule_level": "Low",
				"risk_model": cls.model,
			}
		).insert(ignore_permissions=True)

	def create(self, user, student=None, **values):
		args = dict(
			student=student or self.s["e"],
			term="_Test T3",
			intervention_type="Counseling",
			responsible=TEACHER_1,
			follow_up_date=add_days(today(), 14),
			description=MARKER,
		)
		args.update(values)
		with as_user(user), enforce_roles():
			return frappe.get_doc("Student Intervention", call(CREATE, **args))

	def visible(self, user):
		with as_user(user):
			try:
				return set(frappe.get_list("Student Intervention", pluck="name"))
			except frappe.PermissionError:
				return set()

	def test_snapshot_from_the_early_warning(self):
		doc = self.create(TEACHER_2)  # class teacher of _Test FORM 2
		self.assertEqual(
			(doc.probability, doc.probability_level, doc.rule_score, doc.early_warning_group, doc.risk_model),
			(45, "Medium", 20, EMERGING, self.model),
		)
		self.assertEqual((doc.baseline_term, doc.source, doc.get("class")), ("_Test T2", "Early Warning", "_Test FORM 2"))

		doc.probability = 99
		self.assertRaises(frappe.ValidationError, doc.save, ignore_permissions=True)

		# Values sent with a new intervention are ignored: the snapshot comes from the Early Warning
		manual = frappe.get_doc(
			{
				"doctype": "Student Intervention",
				"student": self.s["a"],
				"term": "_Test T3",
				"intervention_type": "Other",
				"responsible": HEADMASTER,
				"probability": 99,
			}
		).insert(ignore_permissions=True)
		self.assertFalse(manual.probability)
		self.assertEqual(manual.baseline_term, "_Test T2")

	def test_who_sees_and_changes_what(self):
		mine = self.create(TEACHER_2, responsible=TEACHER_1)  # class teacher creates, Teacher One responsible
		by_hm = self.create(HEADMASTER, responsible=HEADMASTER)
		other_class = self.create(HEADMASTER, student=self.s["a"], responsible=HEADMASTER)

		self.assertEqual(self.visible(HEADMASTER) >= {mine.name, by_hm.name, other_class.name}, True)
		self.assertEqual(self.visible(TEACHER_2) & {mine.name, by_hm.name, other_class.name}, {mine.name, by_hm.name})
		self.assertEqual(self.visible(TEACHER_1) & {mine.name, by_hm.name, other_class.name}, {mine.name})
		for user in (ACCOUNTANT, PARENT_2):
			self.assertEqual(self.visible(user), set())
			self.assertFalse(frappe.has_permission("Student Intervention", "read", doc=mine.name, user=user))

		has = lambda ptype, doc, user: frappe.has_permission("Student Intervention", ptype, doc=doc, user=user)
		self.assertTrue(has("write", mine.name, TEACHER_2))  # created it
		self.assertFalse(has("write", by_hm.name, TEACHER_2))  # reads, does not edit
		self.assertTrue(has("write", mine.name, TEACHER_1))  # responsible
		self.assertFalse(has("delete", mine.name, TEACHER_2))
		with as_user(TEACHER_1):  # the responsible teacher updates it
			doc = frappe.get_doc("Student Intervention", mine.name)
			doc.status = "In Progress"
			doc.save()

		# Only for the class teacher's own class, and not by being named responsible
		self.assertRaises(frappe.PermissionError, self.create, TEACHER_2, student=self.s["a"])
		self.assertRaises(frappe.PermissionError, self.create, TEACHER_1, responsible=TEACHER_1)
		self.assertRaises(frappe.ValidationError, self.create, HEADMASTER, responsible=PARENT_2)  # not staff

	def test_parents_see_nothing(self):
		self.create(TEACHER_2)
		with as_user(PARENT_2):
			for path, args in (("parent-portal", {}), ("parent-portal/student", {"student": self.s["e"]})):
				status, body, _ = render(path, **args)
				self.assertEqual(status, 200)
				self.assertNotIn(MARKER, body)
				self.assertNotIn("Counseling", body)

	def test_follow_up_reminders_and_card(self):
		due = self.create(HEADMASTER, responsible=TEACHER_1, follow_up_date=today(), start_date=add_days(today(), -7))
		later = self.create(HEADMASTER, responsible=TEACHER_1, follow_up_date=add_days(today(), 5))
		done = self.create(HEADMASTER, responsible=TEACHER_1, follow_up_date=today(), start_date=add_days(today(), -7))
		frappe.db.set_value("Student Intervention", done.name, "status", "Completed")

		todos = lambda doc: frappe.db.count(
			"ToDo", {"reference_type": "Student Intervention", "reference_name": doc.name, "allocated_to": TEACHER_1}
		)
		interventions.send_follow_up_reminders()
		interventions.send_follow_up_reminders()  # a second night: no second ToDo
		self.assertEqual((todos(due), todos(later), todos(done)), (1, 0, 0))

		with as_user(TEACHER_1), enforce_roles():
			self.assertGreaterEqual(interventions.get_follow_ups_due()["value"], 1)
		with as_user(HEADMASTER), enforce_roles():
			self.assertGreaterEqual(interventions.get_follow_ups_due()["value"], 1)
		with as_user(PARENT_2), enforce_roles():
			self.assertRaises(frappe.PermissionError, interventions.get_follow_ups_due)

		# A new follow-up date gets its own reminder when it comes
		doc = frappe.get_doc("Student Intervention", due.name)
		doc.follow_up_date = add_days(today(), 3)
		doc.save(ignore_permissions=True)
		self.assertIsNone(doc.reminder_sent_on)

	def test_early_warning_shows_the_interventions(self):
		self.create(TEACHER_2, intervention_type="Parent Meeting")
		with as_user(HEADMASTER), enforce_roles():
			_, data, *_ = frappe.get_attr(EARLY_WARNING)({})
		row = next(r for r in data if r["student"] == self.s["e"])
		self.assertIn("Parent Meeting (Planned)", row["interventions"])
		self.assertEqual(row["term"], "_Test T3")  # the "Weka hatua" button needs it
