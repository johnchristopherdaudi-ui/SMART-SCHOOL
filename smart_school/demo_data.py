"""Synthetic demo school: three academic years of a Form 1-4 school (about 300 students at a time) with
exams, attendance, discipline and fee payments, generated from a seed.

The numbers are linked the way they are in a real school: absences and discipline problems lower marks
in the same term and in the next one; a "difficult term" (illness, family trouble) raises absences and
discipline incidents and lowers results; some students slowly decline; how fees are paid follows the
family's means. Gender has no effect on any outcome. A few marks problems are planted so the marks
alerts have something to find; the manifest lists them.

Only for an empty demo site:
    bench --site demo.localhost execute smart_school.demo_data.generate --kwargs "{'seed': 42}"

It refuses jonbale, any site whose name does not start with "demo." (unless its site config sets
allow_demo_data), a site that already has students or academic years, and a site that could really send
email or SMS. The same seed and as_of date give the same school.

build_plan() makes the whole school in memory (no database), write_plan() saves it through the app."""

import json
import math
import random
from datetime import date, datetime, timedelta

import frappe
from frappe.utils import cint, getdate

PROTECTED_SITES = ("jonbale",)
DOMAIN = "demo.smartschool.test"
STUDENTS_PER_FORM = 75
FORMS = (1, 2, 3, 4)

# name: (NECTA code, difficulty in percentage points)
SUBJECTS = {
	"CIVICS": ("011", 3),
	"HISTORY": ("012", 0),
	"GEOGRAPHY": ("013", -3),
	"KISWAHILI": ("021", 8),
	"ENGLISH": ("022", -2),
	"PHYSICS": ("031", -8),
	"CHEMISTRY": ("032", -6),
	"BIOLOGY": ("033", -3),
	"MATHEMATICS": ("041", -10),
}
# Term number: (start month, day), (end month, day)
TERM_DATES = {1: ((1, 8), (4, 3)), 2: ((4, 22), (7, 31)), 3: ((8, 19), (11, 27))}
# The school's one main exam in each term, out of 100, near the end of the term
MAIN_EXAMS = {1: "Midterm", 2: "Terminal", 3: "Annual"}
MAIN_EXAM_DAYS_BEFORE_END = 10
MAX_MARKS = 100
# External exams (district, region, the Form 4 mock) join a term when they happen and count with weights:
# (term, form): (exam name, days after the term starts, weight of the main exam, its weight, difficulty in points)
EXTERNAL_EXAMS = {
	(1, 2): ("District Exam", 42, 60, 40, -3),
	(2, 4): ("Mock", 42, 70, 30, -4),
}
PUBLISH_AFTER_DAYS = 7
MAIN_EXAM_SCHOOL_DAYS = 5  # the main exam's papers take a week
# The school calendar, as the Headmaster would enter it (the fixed national holidays come with the app). Holidays
# that move, on the dates announced for Tanzania (Eid dates depend on the moon: approximate here).
MOVING_HOLIDAYS = {
	2024: (("Ijumaa Kuu", 3, 29), ("Jumatatu ya Pasaka", 4, 1), ("Idd el Fitr", 4, 10), ("Idd el Hajj", 6, 17), ("Maulid", 9, 16)),
	2025: (("Idd el Fitr", 3, 31), ("Ijumaa Kuu", 4, 18), ("Jumatatu ya Pasaka", 4, 21), ("Idd el Hajj", 6, 6), ("Maulid", 9, 5)),
	2026: (("Idd el Fitr", 3, 20), ("Ijumaa Kuu", 4, 3), ("Jumatatu ya Pasaka", 4, 6), ("Idd el Hajj", 5, 27), ("Maulid", 8, 26)),
}
UPCOMING_MEETING_DAYS = 11  # a Form 4 parents' meeting this many days after as_of, with an SMS reminder
# Interventions (2nd and 3rd year): chosen at the start of a term from the term before, more often the more at risk
# the student looks (deliberate selection bias). A Completed one adds INTERVENTION_EFFECT points to every mark of the
# term (planted, to check the Intervention Outcomes report); a Cancelled one adds nothing.
INTERVENTION_EFFECT = 4
INTERVENTION_COMPLETED_SHARE = 0.8
INTERVENTION_TYPES = {
	"Counseling": 25,
	"Parent Meeting": 25,
	"Extra Classes": 20,
	"Teacher Follow-up": 20,
	"Referral": 5,
	"Other": 5,
}
PRESENT_FLOOR = 4  # percent: below this a student who sat the exam gets 2-8%; exact zeros are only planted
BASE_FEES = {1: (350000, 300000, 300000), 2: (350000, 300000, 300000), 3: (400000, 350000, 350000)}
BASE_FEES[4] = BASE_FEES[3]
FEE_GROWTH = 0.05  # per year

SEVERITY_POINTS = {"Minor": 1, "Moderate": 2, "Serious": 4}
INCIDENTS = {
	"Minor": ["Lateness", "Uniform Violation", "Prohibited Items", "Other"],
	"Moderate": ["Truancy", "Disrespect to Staff", "Bullying", "Prohibited Items"],
	"Serious": ["Fighting", "Exam Malpractice", "Property Damage", "Theft", "Bullying"],
}
ACTIONS = {
	"Minor": ["Verbal warning", "Written warning", "Cleaning duty"],
	"Moderate": ["Parent called", "Detention", "Written warning"],
	"Serious": ["Suspension (3 days)", "Parent meeting", "Suspension (7 days)"],
}

MALE_NAMES = (
	"Juma Baraka Emmanuel Joseph John Daudi Hassan Omari Ramadhani Salim Frank Kelvin Brian Elia Isaya "
	"Godfrey Peter Michael Amani Faraji Idrisa Hamisi Abdallah Musa Yusuph Erick Dickson Nassoro Paulo Rashidi"
).split()
FEMALE_NAMES = (
	"Neema Rehema Zawadi Upendo Asha Mwanaisha Grace Joyce Faraja Esther Halima Zainabu Rose Agnes Happy "
	"Glory Winfrida Anna Mary Aisha Saida Tumaini Imani Sabina Lucy Jesca Veronica Rahma Salma Pendo"
).split()
SURNAMES = (
	"Mwakalinga Mushi Massawe Kimaro Mrema Lyimo Swai Temba Shirima Mollel Laizer Kombo Mbwana Mfinanga "
	"Nyerere Mwita Chacha Magesa Mwakyusa Mwambene Kapinga Komba Ngonyani Haule Mbilinyi Kisanga Msuya "
	"Shayo Minja Urassa Njau Kweka Mallya Tarimo Mtei Mapunda Ndunguru Luoga Mhina Nkya"
).split()


# ---------- guard ----------


def assert_demo_site():
	assert_demo_name()
	site = frappe.local.site
	if frappe.db.count("Student") or frappe.db.count("Academic Year"):
		frappe.throw(f"{site} already has students or academic years; demo data needs an empty site")
	if pending_patches():
		frappe.throw(f"{site} has patches that have not run; run bench --site {site} migrate first")
	assert_nobody_messaged()


def assert_demo_name():
	site = frappe.local.site
	if site in PROTECTED_SITES:
		frappe.throw(f"Demo data must never be generated on {site}")
	if not (site.startswith("demo.") or frappe.conf.get("allow_demo_data")):
		frappe.throw(f"Demo data is only generated on a demo site (demo.*), not on {site}")


def assert_nobody_messaged():
	from smart_school.notifications import has_outgoing_email_account

	if (
		has_outgoing_email_account()
		or frappe.db.get_single_value("SMS Settings", "sms_gateway_url")
		or frappe.db.get_single_value("Smart School Settings", "sms_mode") == "Live"
	):
		frappe.throw("Turn off outgoing email and SMS before generating demo data, so no one is messaged")


def pending_patches():
	from frappe.modules.patch_handler import executed, get_patches_from_app

	return [p for p in get_patches_from_app("smart_school") if not executed(p)]


# ---------- the plan (no database) ----------


def sigmoid(x):
	return 1 / (1 + math.exp(-x))


def clamp(x, low, high):
	return max(low, min(high, x))


def half_up(x):
	return int(math.floor(x + 0.5))


def poisson(rng, lam):
	limit, k, p = math.exp(-lam), 0, 1.0
	while True:
		p *= rng.random()
		if p <= limit:
			return k
		k += 1


def school_days(start, end, as_of, off=frozenset()):
	"""Monday to Friday, without holidays and breaks (the app's rule for a school without Saturday classes)."""
	day, days = start, []
	while day <= min(end, as_of):
		if day.weekday() < 5 and day not in off:
			days.append(day)
		day += timedelta(days=1)
	return days


def next_school_day(day, off):
	while day.weekday() >= 5 or day in off:
		day += timedelta(days=1)
	return day


def add_event(plan, title, kind, start, end=None, is_school_day=0, forms=None, description=None, **values):
	plan.events.append(
		{
			"title": title,
			"type": kind,
			"start": start,
			"end": end or start,
			"is_school_day": is_school_day,
			"forms": forms,
			"description": description,
			**values,
		}
	)


def holidays(plan, year):
	"""Days off in a year: the fixed national holidays (from the app) and the moving ones (entered as events)."""
	from smart_school.school_calendar import FIXED_HOLIDAYS

	off = {date(year, m, d) for _, m, d in FIXED_HOLIDAYS}
	for title, m, d in MOVING_HOLIDAYS.get(year, ()):
		add_event(plan, title, "Public Holiday", date(year, m, d), description="Sikukuu ya kitaifa: hakuna masomo.")
		off.add(date(year, m, d))
	return off


def build_plan(seed=42, as_of=None, students_per_form=STUDENTS_PER_FORM):
	"""The whole school as plain data. Deterministic for a seed and an as_of date."""
	as_of = getdate(as_of) if as_of else date.today()
	rng = random.Random(seed)
	last_year = as_of.year
	years = [last_year - 2, last_year - 1, last_year]
	plan = frappe._dict(
		seed=seed,
		as_of=as_of,
		years=years,
		terms=[],
		exams=[],
		teachers=[],
		students=[],
		guardians=[],
		enrolments={},  # (student, year) -> form
		results={},  # (exam, student, subject) -> [marks, owner teacher]
		interventions=[],
		events=[],  # the school calendar (School Event), without the fixed holidays the app installs
		without_intervention={},  # (exam, student, subject) -> (marks, marks the student would have had without it)
		attendance=[],  # (student, date, status, term, form)
		discipline=[],  # (student, date, incident, severity, action)
		payments=[],  # (student, term, amount, date, method)
		fees={},  # (form, term) -> amount
		plants=[],
	)

	make_calendar(plan)
	make_teachers(plan, rng)
	make_students(plan, rng, students_per_form)

	effects = {
		"teacher": {(s, f): rng.gauss(0, 3) for s in SUBJECTS for f in FORMS},
		"exam": {},
	}
	state = {s["key"]: {"shock": False, "rate": s["base_absence"], "debt": 0} for s in plan.students}
	for term in plan.terms:
		simulate_term(plan, rng, term, state, effects)
		if term["number"] == 3 and term["year"] != last_year:
			end_of_year(plan, rng, term["year"], state)

	plant_marks_problems(plan, rng)
	return plan


def make_calendar(plan):
	index = 0
	for year in plan.years:
		off_year = holidays(plan, year)
		for number, ((sm, sd), (em, ed)) in TERM_DATES.items():
			start, end = date(year, sm, sd), date(year, em, ed)
			off = off_year | term_events(plan, number, start, end, off_year)
			term = {
				"name": f"Term {number} {year}",
				"number": number,
				"year": year,
				"start": start,
				"end": end,
				"index": index,
				"days": school_days(start, end, plan.as_of, off),
				"off": off,
			}
			index += 1
			if start > plan.as_of:
				term["days"] = []
			plan.terms.append(term)
			growth = (1 + FEE_GROWTH) ** plan.years.index(year)
			for form in FORMS:
				plan.fees[(form, term["name"])] = half_up(BASE_FEES[form][number - 1] * growth / 5000) * 5000
			for form in FORMS:
				external = EXTERNAL_EXAMS.get((number, form))
				main_weight = None
				if external:  # set before the main exam, as it is sat first
					name, after_start, main_weight, weight, shift = external
					day = next_school_day(start + timedelta(days=after_start), off)
					add_exam(plan, term, form, name, "external", day, weight, shift, last_day=day)
				main_day = next_school_day(end - timedelta(days=MAIN_EXAM_DAYS_BEFORE_END), off)
				papers = school_days(main_day, end, end, off)[:MAIN_EXAM_SCHOOL_DAYS]
				add_exam(plan, term, form, MAIN_EXAMS[number], "main", main_day, main_weight, 0, last_day=papers[-1])


def term_events(plan, number, start, end, off):
	"""A term's events: a week's midterm break (no school), and school-day events: a parents' meeting (terms 1
	and 3), sports day (term 2), Form 4 graduation (term 3). Returns the break's days."""
	middle = start + (end - start) / 2
	break_start = middle - timedelta(days=middle.weekday())
	break_days = {break_start + timedelta(days=i) for i in range(5)}
	add_event(
		plan, "Mapumziko ya katikati ya muhula", "Midterm Break", break_start, break_start + timedelta(days=4),
		description="Wanafunzi wako nyumbani wiki hii; masomo yanaendelea Jumatatu inayofuata.",
	)
	friday = lambda day: next_school_day(day + timedelta(days=(4 - day.weekday()) % 7), off | break_days)
	if number in (1, 3):
		add_event(
			plan, "Mkutano wa wazazi na walimu", "Parents Meeting", friday(start + timedelta(days=14)), is_school_day=1,
			description="Saa 8 mchana, ukumbi wa shule. Wazazi wote mnakaribishwa.",
		)
	if number == 2:
		add_event(
			plan, "Siku ya michezo", "Sports Day", friday(break_start + timedelta(days=21)), is_school_day=1,
			description="Michezo ya mabweni yote uwanjani; wazazi mnakaribishwa.",
		)
	if number == 3:
		add_event(
			plan, "Mahafali ya Kidato cha Nne", "Graduation", friday(end - timedelta(days=21)), is_school_day=1,
			forms=[4], description="Sherehe ya kuwaaga wanafunzi wa Kidato cha Nne.",
		)
		meeting = plan.as_of + timedelta(days=UPCOMING_MEETING_DAYS)
		if start <= meeting <= end and plan.as_of.year == start.year:
			add_event(
				plan, "Mkutano wa wazazi wa Kidato cha Nne", "Parents Meeting", friday(meeting), is_school_day=1,
				forms=[4], sms_reminder=1, sms_days_before=3,
				description="Maandalizi ya mtihani wa taifa (CSEE). Saa 4 asubuhi, ukumbi wa shule.",
			)
	return break_days


def add_exam(plan, term, form, exam_name, kind, day, weight, shift, last_day=None):
	published = day + timedelta(days=PUBLISH_AFTER_DAYS)
	plan.exams.append(
		{
			"key": f"{exam_name}|{form}|{term['name']}",
			"exam_name": exam_name,
			"kind": kind,
			"form": form,
			"term": term["name"],
			"year": term["year"],
			"max_marks": MAX_MARKS,
			"weight": weight,
			"shift": shift,
			"date": day,
			"last_day": last_day or day,
			"sat": day <= plan.as_of,
			"published_on": published if published <= plan.as_of else None,
		}
	)


def make_teachers(plan, rng):
	"""Two teachers per subject: one for Forms 1-2, one for Forms 3-4. Four of them are class teachers."""
	used = set()
	for i, subject in enumerate(SUBJECTS):
		for forms in ((1, 2), (3, 4)):
			n = len(plan.teachers) + 1
			gender = rng.choice(("Male", "Female"))
			full_name = unique_name(rng, gender, used, middle=False)
			plan.teachers.append(
				{
					"key": f"T{n:02d}",
					"full_name": ("Mr. " if gender == "Male" else "Ms. ") + full_name,
					"email": f"teacher{n:02d}@{DOMAIN}",
					"phone": phone(rng),
					"assignments": [(subject, f) for f in forms],
				}
			)
	# Each class teacher teaches in their class: CIVICS / HISTORY in Forms 1-2, GEOGRAPHY / KISWAHILI in 3-4
	plan.class_teachers = {form: plan.teachers[i]["key"] for form, i in zip(FORMS, (0, 2, 5, 7))}


def teacher_for(plan, subject, form):
	return next(t["key"] for t in plan.teachers if (subject, form) in t["assignments"])


def unique_name(rng, gender, used, middle=True):
	names = MALE_NAMES if gender == "Male" else FEMALE_NAMES
	while True:
		parts = [rng.choice(names)]
		if middle:
			parts.append(rng.choice(MALE_NAMES))  # father's name
		parts.append(rng.choice(SURNAMES))
		name = " ".join(parts)
		if name not in used:
			used.add(name)
			return name


def phone(rng):
	return f"+255 7{rng.choice('1345678')}{rng.randint(0, 9)} {rng.randint(100, 999)} {rng.randint(100, 999)}"


def make_students(plan, rng, per_form):
	"""Cohorts that are in Forms 1-4 during the three years: entry years first_year-3 .. last_year."""
	used, n = set(), 0
	first_year = plan.years[0]
	for entry_year in range(first_year - 3, plan.years[-1] + 1):
		size = per_form + rng.randint(-4, 4)
		for _ in range(size):
			n += 1
			gender = rng.choice(("Male", "Female"))
			ses = rng.gauss(0, 1)
			engagement = rng.gauss(0, 1)
			decline = None
			if rng.random() < 0.12:
				decline = {"start": rng.randint(0, 8), "slope": rng.uniform(2, 4)}
			student = {
				"key": f"S{n:04d}",
				"full_name": unique_name(rng, gender, used),
				"gender": gender,
				"entry_year": entry_year,
				"admission_date": date(entry_year, 1, 8),
				"date_of_birth": date(entry_year - 14, rng.randint(1, 12), rng.randint(1, 28)),
				"ability": rng.gauss(0, 1),
				"engagement": engagement,
				"ses": ses,
				"aptitude": {s: rng.gauss(0, 1) for s in SUBJECTS},
				"base_absence": sigmoid(-3.4 - 0.9 * engagement - 0.4 * ses),
				"base_late": 0.02 + 0.05 * sigmoid(-engagement),
				"decline": decline,
				"status": "Active",
				"left_after": None,  # year after which the student left
				"section": rng.choice("AB"),
			}
			plan.students.append(student)
			for year in plan.years:
				form = year - entry_year + 1
				if form in FORMS:
					plan.enrolments[(student["key"], year)] = form

	# Guardians: one per family; about one family in ten has two children at the school
	families = []
	for student in plan.students:
		if families and rng.random() < 0.1:
			families[rng.randrange(len(families))].append(student)
		else:
			families.append([student])
	for i, family in enumerate(families, start=1):
		gender = rng.choice(("Male", "Female"))
		surname = family[0]["full_name"].split()[-1]
		first = rng.choice(MALE_NAMES if gender == "Male" else FEMALE_NAMES)
		plan.guardians.append(
			{
				"key": f"G{i:04d}",
				"full_name": f"{first} {surname}",
				"phone": phone(rng),
				"email": f"parent{i:04d}@{DOMAIN}" if rng.random() < 0.6 else None,
				"students": [
					(s["key"], "Father" if gender == "Male" else rng.choice(("Mother", "Guardian"))) for s in family
				],
			}
		)


def active_in(plan, student, year):
	if (student["key"], year) not in plan.enrolments:
		return False
	return student["left_after"] is None or year <= student["left_after"]


def simulate_term(plan, rng, term, state, effects):
	year, t = term["year"], term["index"]
	exams = [e for e in plan.exams if e["term"] == term["name"] and e["sat"]]
	previous = plan.terms[t - 1] if t else None
	previous_averages = term_averages(plan, previous["name"]) if previous and year >= plan.years[1] else {}
	for student in plan.students:
		if not active_in(plan, student, year) or not term["days"]:
			continue
		key, form = student["key"], plan.enrolments[(student["key"], year)]
		s = state[key]
		previous_rate, previous_shock = s["rate"], s["shock"]
		intervention = None
		if key in previous_averages:
			intervention = maybe_intervene(plan, rng, key, term, previous, form, previous_averages[key], previous_rate)
		shock = rng.random() < (0.35 if previous_shock else 0.06)
		declining = 0
		if student["decline"] and t >= student["decline"]["start"]:
			declining = t - student["decline"]["start"] + 1

		# Attendance: absences, late (counts half) and excused (does not count)
		absent_p = clamp(
			student["base_absence"] + 0.18 * shock + 0.035 * declining + rng.gauss(0, 0.015), 0.005, 0.7
		)
		late_p = student["base_late"]
		counts = {"Absent": 0, "Late": 0}
		for day in term["days"]:
			u = rng.random()
			if u < absent_p:
				status = "Absent"
			elif u < absent_p + late_p:
				status = "Late"
			elif u < absent_p + late_p + 0.012:
				status = "Excused"
			else:
				status = "Present"
			counts[status] = counts.get(status, 0) + 1
			plan.attendance.append((key, day, status, term["name"], form))
		rate = (counts["Absent"] + 0.5 * counts["Late"]) / len(term["days"])

		# Discipline: more incidents, and more serious ones, with low engagement and in a difficult term
		lam = 0.10 * math.exp(-0.8 * student["engagement"]) + 0.8 * shock + 0.25 * min(declining, 3)
		weights = (0.45, 0.35, 0.20) if shock else (0.65, 0.27, 0.08)
		points = 0
		for _ in range(poisson(rng, lam)):
			severity = rng.choices(("Minor", "Moderate", "Serious"), weights)[0]
			incidents = INCIDENTS[severity]
			incident = "Truancy" if severity == "Moderate" and rate > 0.15 else rng.choice(incidents)
			plan.discipline.append(
				(key, rng.choice(term["days"]), incident, severity, rng.choice(ACTIONS[severity]))
			)
			points += SEVERITY_POINTS[severity]

		# Marks: ability and aptitude, minus this term's and last term's absences, discipline and trouble
		base = (
			61
			+ 12 * student["ability"]
			- 50 * rate
			- 50 * previous_rate
			- 2.0 * min(points, 8)
			- 8 * shock
			- 8 * previous_shock
			+ rng.gauss(0, 4)  # how this term went for the student, in every subject
		)
		if declining:
			base -= student["decline"]["slope"] * declining
		# Planted: a Completed intervention adds INTERVENTION_EFFECT to every mark of the term. The marks without it
		# (same noise) are kept too, so the manifest can state the effect that really reached the data.
		boost = INTERVENTION_EFFECT if intervention and intervention["status"] == "Completed" else 0
		for exam in exams:
			if exam["form"] != form or rng.random() < 0.01 + 0.3 * rate:
				continue  # missed the exam
			for subject, (_, difficulty) in SUBJECTS.items():
				exam_effect = effects["exam"].setdefault((exam["key"], subject), rng.gauss(0, 3))
				raw = (
					base
					+ 6 * student["aptitude"][subject]
					+ difficulty
					+ effects["teacher"][(subject, form)]
					+ exam_effect
					+ exam["shift"]
					+ rng.gauss(0, 7)
				)
				without = clamp(raw, 0, 100)
				if without < PRESENT_FLOOR:  # a student who sat the exam writes something: a few marks, not exactly 0
					without = rng.uniform(PRESENT_FLOOR / 2, PRESENT_FLOOR * 2)
				pct = min(without + boost, 100)  # added after the floor, so the weakest students get all of it
				marks = half_up(pct / 100 * exam["max_marks"])
				plan.results[(exam["key"], key, subject)] = [marks, teacher_for(plan, subject, form)]
				if boost:
					plan.without_intervention[(exam["key"], key, subject)] = (marks, half_up(without / 100 * exam["max_marks"]))

		pay_fees(plan, rng, student, term, form, shock, s)
		s.update({"shock": shock, "rate": rate})


def term_averages(plan, term_name):
	"""{student: average percentage of their marks in the term} (close to the term result's average)."""
	exams = {e["key"]: e["max_marks"] for e in plan.exams if e["term"] == term_name}
	totals = {}
	for (key, student, _), (marks, _) in plan.results.items():
		if key in exams:
			total = totals.setdefault(student, [0.0, 0])
			total[0] += marks / exams[key] * 100
			total[1] += 1
	return {student: total / count for student, (total, count) in totals.items()}


def maybe_intervene(plan, rng, student, term, previous, form, average, absence):
	"""At the start of a term the school acts for some students it sees at risk from the term before (an
	average below 35, or a model-like risk of 30% or more): the higher the risk, the likelier."""
	risk = sigmoid(-0.18 * (average - 38) + 8 * (absence - 0.09))
	at_risk = average < 35
	if not (at_risk or risk >= 0.3) or rng.random() >= 0.15 + 0.5 * risk:
		return None
	start = term["start"] + timedelta(days=rng.randint(7, 21))
	follow_up = start + timedelta(days=rng.randint(14, 35))
	if term["end"] < plan.as_of:
		status = "Completed" if rng.random() < INTERVENTION_COMPLETED_SHARE else "Cancelled"
	else:
		status = "Planned" if start > plan.as_of else "In Progress"
	intervention = {
		"student": student,
		"term": term["name"],
		"baseline_term": previous["name"],
		"form": form,
		"type": rng.choices(list(INTERVENTION_TYPES), list(INTERVENTION_TYPES.values()))[0],
		"responsible": rng.choice(
			[plan.class_teachers[form], teacher_for(plan, rng.choice(list(SUBJECTS)), form)]
		),
		"start": start,
		"follow_up": follow_up,
		"status": status,
		"parent_informed": rng.random() < 0.6,
		"risk": risk,
		"average": average,
		"absence": absence,
		"at_risk": at_risk,
	}
	plan.interventions.append(intervention)
	return intervention


def pay_fees(plan, rng, student, term, form, shock, s):
	"""Families with more means pay in full and early; others pay part, sometimes clearing old debt later."""
	fee = plan.fees[(form, term["name"])]
	due = fee + s["debt"]
	if rng.random() < sigmoid(0.8 + 1.3 * student["ses"] - 1.5 * shock):
		total = due if s["debt"] and rng.random() < 0.6 else fee
	elif shock and rng.random() < 0.3:
		total = 0
	else:
		total = half_up(fee * rng.uniform(0.3, 0.9) / 5000) * 5000
	s["debt"] = max(due - total, 0)

	instalments = 1 if total == fee and student["ses"] > 0.5 and rng.random() < 0.6 else rng.choice((1, 2, 2, 3))
	amounts = split_amount(rng, total, instalments)
	span = (term["end"] - term["start"]).days - 5
	for i, amount in enumerate(amounts):
		offset = rng.randint(-14, 10) if i == 0 else rng.randint(20, span)
		day = term["start"] + timedelta(days=offset)
		if day <= plan.as_of:
			method = rng.choices(
				("Mobile Money", "Bank Transfer", "Cash"), (0.6, 0.15 + 0.1 * (student["ses"] > 0), 0.15)
			)[0]
			plan.payments.append((student["key"], term["name"], amount, day, method))


def split_amount(rng, total, parts):
	if total <= 0:
		return []
	if parts == 1 or total < 10000 * parts:
		return [total]
	cuts = sorted(half_up(total * rng.uniform(0.2, 0.8) / 5000) * 5000 for _ in range(parts - 1))
	amounts = [b - a for a, b in zip([0, *cuts], [*cuts, total])]
	return [a for a in amounts if a > 0]


def end_of_year(plan, rng, year, state):
	"""Form 4 graduates; a few others leave, more often those who were often absent."""
	for student in plan.students:
		if not active_in(plan, student, year):
			continue
		form = plan.enrolments[(student["key"], year)]
		if form == 4:
			student["status"], student["left_after"] = "Graduated", year
		elif rng.random() < min(0.01 + 0.6 * max(state[student["key"]]["rate"] - 0.08, 0), 0.25):
			student["status"], student["left_after"] = "Dropped", year
		elif rng.random() < 0.01:
			student["status"], student["left_after"] = "Transferred", year


# ---------- planted marks problems ----------

AFTER_PUBLISHING = ("Changed After Publish", "Results Unpublished")


def exam_key(plan, year_offset, number, form):
	"""The main exam of a term for a form."""
	year = plan.years[year_offset]
	return next(
		e["key"]
		for e in plan.exams
		if e["year"] == year and e["term"] == f"Term {number} {year}" and e["kind"] == "main" and e["form"] == form
	)


def previous_percentages(plan, key, subject):
	"""{student: percentage in their latest exam of the subject before this one}."""
	exams = {e["key"]: e for e in plan.exams}
	day, latest = exams[key]["date"], {}
	for (k, student, s), (marks, _) in plan.results.items():
		if s == subject and exams[k]["date"] < day:
			if student not in latest or exams[k]["date"] > latest[student][0]:
				latest[student] = (exams[k]["date"], marks / exams[k]["max_marks"] * 100)
	return {student: pct for student, (_, pct) in latest.items()}


def exam_rows(plan, key, subject):
	return sorted((student, row) for (e, student, s), row in plan.results.items() if e == key and s == subject)


def plant_marks_problems(plan, rng):
	"""Each plant is changed here in the marks (statistical ones and the unassigned entry) or later by
	write_plan through the app (changes after publishing, unpublishing)."""
	# In the main exams. Many zeros and the swapped marks sit in the Form 2 Terminal exam of the last year that
	# the Headmaster unpublishes: they show up when it is published again.
	planted = [
		("Many Identical Marks", 1, 2, 2, "GEOGRAPHY"),
		("Many Round Numbers", 2, 2, 3, "HISTORY"),
		("Very Low Spread", 0, 3, 1, "CIVICS"),
		("Many Zero Marks", 2, 2, 2, "BIOLOGY"),
		("Unusual Class Average", 2, 2, 4, "CHEMISTRY"),
		("Unusual Student Change", 2, 2, 2, "MATHEMATICS"),
		("Dropped To Zero", 2, 2, 4, "BIOLOGY"),
		("Entered By Unassigned User", 2, 2, 3, "KISWAHILI"),
		("Changed After Publish", 2, 2, 1, "ENGLISH"),
		("Results Unpublished", 2, 2, 2, "PHYSICS"),
	]
	for alert_type, year_offset, number, form, subject in planted:
		key = exam_key(plan, year_offset, number, form)
		exam = next(e for e in plan.exams if e["key"] == key)
		rows = exam_rows(plan, key, subject)
		# Not yet possible on this as_of date: the exam was not sat, or (for changes after publishing) not published
		done = bool(rows) and (alert_type not in AFTER_PUBLISHING or exam["published_on"] is not None)
		plant = {"alert_type": alert_type, "exam": key, "subject": subject, "students": [], "done": done}
		plan.plants.append(plant)
		if not done:
			continue
		max_marks = exam["max_marks"]

		if alert_type == "Many Identical Marks":
			for student, row in rng.sample(rows, len(rows) // 2):
				row[0] = 55
		elif alert_type == "Many Round Numbers":
			for _, row in rows:
				row[0] = min(half_up(row[0] / 5) * 5, max_marks)
		elif alert_type == "Very Low Spread":
			for _, row in rows:
				row[0] = 60 + rng.choice((-1, 0, 1))
		elif alert_type == "Many Zero Marks":
			for _, row in rng.sample(rows, round(len(rows) * 0.3)):
				row[0] = 0
		elif alert_type == "Unusual Class Average":
			for _, row in rows:
				row[0] = min(row[0] + 25, max_marks)
		elif alert_type == "Unusual Student Change":
			# Marks typed against the wrong names: the two weakest swap with the two strongest
			ranked = sorted(rows, key=lambda r: (r[1][0], r[0]))
			for (weak, weak_row), (strong, strong_row) in zip(ranked[:2], ranked[-2:]):
				weak_row[0], strong_row[0] = strong_row[0], weak_row[0]
				plant["students"] += [weak, strong]
		elif alert_type == "Dropped To Zero":
			# Two marks never entered (typed as 0) for students who had at least 50% in their previous exam
			earlier = previous_percentages(plan, key, subject)
			good = [(student, row) for student, row in rows if earlier.get(student, 0) >= 50]
			for student, row in rng.sample(good, min(2, len(good))):
				row[0] = 0
				plant["students"].append(student)
		elif alert_type == "Entered By Unassigned User":
			other = teacher_for(plan, "HISTORY", form)
			for _, row in rows:
				row[1] = other
			plant["entered_by"] = other
		elif alert_type == "Changed After Publish":
			plant["students"] = [student for student, _ in rng.sample(rows, 2)]
		elif alert_type == "Results Unpublished":
			plant["students"] = [rng.choice(rows)[0]]


# ---------- writing the plan ----------

HEADMASTER = ("headmaster@" + DOMAIN, "Mr. Joseph Massawe")
ACCOUNTANT = ("bursar@" + DOMAIN, "Ms. Grace Temba")


def generate(seed=42, as_of=None, students_per_form=STUDENTS_PER_FORM):
	"""Entry point for bench execute: check the site, finish the setup wizard, build the school, save it
	and commit. Passwords are not set: the owner sets them with bench set-password."""
	assert_demo_site()
	as_of = getdate(as_of or frappe.utils.today())
	if as_of > getdate(frappe.utils.today()):
		frappe.throw("as_of cannot be in the future")

	frappe.flags.mute_emails = True
	complete_setup_wizard()
	plan = build_plan(seed, as_of, cint(students_per_form))
	manifest = write_plan(plan)
	frappe.db.commit()
	manifest["sms"] = write_sms_demo(plan.seed, plan.as_of)
	manifest["leave"] = write_leave_demo(plan.seed, plan.as_of)
	frappe.db.commit()
	save_manifest(manifest)
	return manifest


def manifest_path():
	return frappe.get_site_path("private", "demo_data_manifest.json")


def save_manifest(manifest):
	with open(manifest_path(), "w") as f:
		json.dump(manifest, f, indent=1, default=str)
	log(f"Manifest saved to {manifest_path()}")


# ---------- SMS (Test mode) ----------

SMS_CONSENT_SHARE = 0.85  # guardians who ticked the SMS box on the admission form
SMS_BAD_NUMBERS = 3  # of those, numbers typed with a digit missing: their SMS fail, with the reason
SMS_RECEIPT_DAYS = 14  # receipts of the payments of the last two weeks


def add_sms_demo():
	"""SMS on a demo made before SMS existed: bench --site demo.localhost execute smart_school.demo_data.add_sms_demo.
	Test mode only (nothing is sent), and its own random numbers, so the rest of the demo does not change."""
	assert_demo_name()
	assert_nobody_messaged()
	if frappe.db.count("SMS Outbox"):
		frappe.throw("This demo already has SMS messages")
	with open(manifest_path()) as f:
		manifest = json.load(f)
	manifest["sms"] = write_sms_demo(manifest["seed"], getdate(manifest["as_of"]))
	frappe.db.commit()
	save_manifest(manifest)
	return manifest["sms"]


LEAVE_REASONS = (
	"Mgonjwa, ana homa na kikohozi",
	"Msiba wa familia kijijini",
	"Amelazwa hospitali, cheti cha daktari kitaletwa",
	"Safari ya kifamilia ya dharura",
	"Ana malaria, anapumzika nyumbani",
	"Harusi ya kaka yake",
	"Kliniki ya meno",
)
# (status, first day as days after as_of, school days long)
LEAVE_PLAN = (
	("Approved", -18, 2),
	("Approved", -15, 1),
	("Approved", -11, 3),
	("Approved", -8, 2),
	("Approved", -4, 1),
	("Approved", -2, 2),
	("Rejected", -13, 1),
	("Rejected", -6, 2),
	("Cancelled", -9, 1),
	("Pending", 1, 2),
	("Pending", 3, 1),
	("Pending", 6, 3),
)


def add_leave_demo():
	"""Leave requests on a demo made before them: bench --site demo.localhost execute smart_school.demo_data.add_leave_demo.
	Their own random numbers, so the rest of the demo does not change (apart from the days they excuse)."""
	assert_demo_name()
	assert_nobody_messaged()
	if frappe.db.count("Leave Request"):
		frappe.throw("This demo already has leave requests")
	with open(manifest_path()) as f:
		manifest = json.load(f)
	manifest["leave"] = write_leave_demo(manifest["seed"], getdate(manifest["as_of"]))
	frappe.db.commit()
	save_manifest(manifest)
	return manifest["leave"]


def write_leave_demo(seed, as_of):
	"""Parents with a portal account ask leave for their children; the class teachers decide through the app, so
	approved days become Excused and the parents who agreed get an SMS (Test mode). Does not commit."""
	from smart_school import leave
	from smart_school.school_calendar import SchoolCalendar
	from smart_school.sms import send_due

	rng = random.Random(f"{seed}-leave")
	calendar = SchoolCalendar()
	links = frappe.get_all(
		"Guardian Student Link", filters={"parenttype": "Guardian"}, fields=["parent", "student"], order_by="parent, student"
	)
	portal = set(frappe.get_all("Guardian", filters={"user": ["is", "set"]}, pluck="name"))
	active = dict(frappe.get_all("Student", filters={"status": "Active"}, fields=["name", "current_class"], as_list=True))
	candidates = [l for l in links if l.parent in portal and l.student in active]
	chosen = rng.sample(candidates, min(len(LEAVE_PLAN), len(candidates)))
	counts, excused = {}, 0
	for (status, offset, length), link in zip(LEAVE_PLAN, chosen):
		class_name = active[link.student]
		days = calendar.school_days(as_of + timedelta(days=offset), as_of + timedelta(days=offset + 21), class_name)
		days = days[:length] or [as_of + timedelta(days=offset)]
		doc = frappe.get_doc(
			{
				"doctype": "Leave Request",
				"student": link.student,
				"class": class_name,
				"guardian": link.parent,
				"from_date": days[0],
				"to_date": days[-1],
				"reason": rng.choice(LEAVE_REASONS),
				"status": "Pending",
			}
		)
		doc.flags.from_portal = True
		doc.insert(ignore_permissions=True)
		leave.notify_deciders(doc)
		if status in ("Approved", "Rejected"):
			teacher = frappe.db.get_value("Class", class_name, "class_teacher")
			frappe.set_user(frappe.db.get_value("Teacher", teacher, "user") or "Administrator")
			try:
				note = "Apone haraka." if status == "Approved" else "Siku hizo ni za mitihani; afike shuleni."
				leave.decide(doc.name, status, note)
			finally:
				frappe.set_user("Administrator")
			if status == "Approved":
				excused += frappe.db.count("Attendance", {"leave_request": doc.name})
		elif status == "Cancelled":
			doc.status = "Cancelled"
			doc.flags.from_portal = True
			doc.save(ignore_permissions=True)
			leave.close_todos(doc)
		counts[status] = counts.get(status, 0) + 1
	send_due()  # the decision SMS, recorded in Test mode (in the quiet hours they wait for 07:00)
	log(f"Leave requests: {sum(counts.values())}, {excused} attendance days excused")
	return {"requests": dict(sorted(counts.items())), "attendance_excused": excused}


def write_sms_demo(seed, as_of):
	"""Test mode; consent for most guardians (a few numbers mistyped); the SMS of the results published in the
	last finished term and of the last two weeks' receipts, written and recorded as Test. Does not commit."""
	from smart_school import sms

	rng = random.Random(f"{seed}-sms")
	frappe.flags.mute_emails = True
	settings = {**sms.DEFAULTS, "sms_mode": sms.TEST, "sms_school_name": "Mwanga SS"}
	for fieldname, value in settings.items():
		frappe.db.set_single_value("Smart School Settings", fieldname, value)
	frappe.clear_document_cache("Smart School Settings", "Smart School Settings")

	guardians = frappe.get_all("Guardian", fields=["name", "phone", "creation"], order_by="name asc")
	agreed = [g for g in guardians if rng.random() < SMS_CONSENT_SHARE]
	for g in agreed:
		frappe.db.set_value(
			"Guardian",
			g.name,
			{
				"sms_opt_in": 1,
				"sms_opt_in_source": "Admission",
				"sms_opt_in_date": getdate(g.creation),
				"sms_opt_in_by": "Administrator",
			},
			update_modified=False,
		)
	mistyped = []
	for g in rng.sample([g for g in agreed if g.phone], min(SMS_BAD_NUMBERS, len(agreed))):
		wrong = g.phone[:-1]  # a digit missing
		frappe.db.set_value("Guardian", g.name, "phone", wrong, update_modified=False)
		mistyped.append({"guardian": g.name, "phone": wrong})

	terms = frappe.get_all(
		"Term", filters={"end_date": ["<", as_of]}, fields=["name"], order_by="end_date desc", limit=1
	)
	exams = (
		frappe.get_all("Exam", filters={"term": terms[0].name, "results_published": 1}, pluck="name", order_by="name")
		if terms
		else []
	)
	for exam in exams:
		sms.queue_exam_results(exam)
	payments = frappe.get_all(
		"Fee Payment",
		filters={"docstatus": 1, "payment_date": ["between", [as_of - timedelta(days=SMS_RECEIPT_DAYS), as_of]]},
		pluck="name",
		order_by="payment_date asc, name asc",
	)
	for payment in payments:
		sms.queue_payment_receipt(payment)
	sms.send_due()  # in the quiet hours they stay Queued until 07:00 (the scheduler sends them)
	log(f"SMS (Test mode): {len(exams)} exams, {len(payments)} payments")

	outbox = frappe.get_all("SMS Outbox", fields=["message_type", "status", "segments"])
	counts = {}
	for row in outbox:
		key = f"{row.message_type} / {row.status}"
		counts[key] = counts.get(key, 0) + 1
	return {
		"mode": sms.TEST,
		"guardians": len(guardians),
		"consent": len(agreed),
		"mistyped_numbers": mistyped,
		"results_exams": exams,
		"receipt_payments": len(payments),
		"messages": dict(sorted(counts.items())),
		"sms_parts": sum(r.segments for r in outbox),
		"multi_part_messages": sum(1 for r in outbox if r.segments > 1),
	}


def complete_setup_wizard():
	"""Frappe's own setup wizard, without creating a user (no email is given; it commits). A new site may
	already count as set up, so the regional settings are applied with Frappe's functions either way."""
	from frappe.desk.page.setup_wizard.setup_wizard import set_timezone, setup_complete, update_system_settings

	args = frappe._dict(language="English", country="Tanzania", timezone="Africa/Dar_es_Salaam", currency="TZS")
	log("Setup wizard: Tanzania, TZS, Africa/Dar_es_Salaam, English")
	frappe.db.set_value("Currency", "TZS", "enabled", 1)
	if not frappe.is_setup_complete():
		setup_complete(dict(args))
	update_system_settings(args)
	set_timezone(args)
	frappe.db.set_single_value("System Settings", "setup_complete", 1)


def log(message):
	print(f"[{datetime.now():%H:%M:%S}] {message}", flush=True)


def write_plan(plan, fees=True):
	"""Save the plan through the app (doc API for people and payments, bulk insert for the large tables)
	and return the manifest. Does not commit. Tests that do not need fees can skip them (the slowest part)."""
	ctx = frappe._dict(plan=plan, names=random.Random(f"{plan.seed}-names"))
	try:
		write_school(ctx)
		write_calendar(ctx)
		write_people(ctx)
		write_exams(ctx)
		write_attendance_and_discipline(ctx)
		write_interventions(ctx)
		if fees:
			write_fees(ctx)
		publish_exams(ctx)
		apply_integrity_plants(ctx)
		run_daily_jobs(ctx)
	finally:
		frappe.set_user("Administrator")
	return make_manifest(ctx)


def insert(values, name=None):
	return frappe.get_doc(values).insert(ignore_permissions=True, set_name=name)


def row_name(ctx):
	"""Name for bulk-inserted rows of hash-named doctypes, reproducible from the seed."""
	return f"{ctx.names.getrandbits(40):010x}"


def reserve_series(prefix, count):
	"""Names prefix00001... for a bulk insert, moving the naming series on so the app continues after them."""
	current = frappe.db.sql("select current from `tabSeries` where name = %s for update", prefix)
	start = cint(current[0][0]) if current else 0
	if current:
		frappe.db.sql("update `tabSeries` set current = %s where name = %s", (start + count, prefix))
	else:
		frappe.db.sql("insert into `tabSeries` (name, current) values (%s, %s)", (prefix, count))
	return [f"{prefix}{n:05d}" for n in range(start + 1, start + count + 1)]


def make_user(email, full_name, role):
	"""Frappe throttles user creation (60 a minute); in_import is its switch for bulk imports,
	turned on only while the user is created."""
	from smart_school.users import ensure_user_with_role

	previous = frappe.flags.in_import
	frappe.flags.in_import = True
	try:
		return ensure_user_with_role(email, full_name, role, send_welcome_email=False)
	finally:
		frappe.flags.in_import = previous


def class_name(form):
	return f"FORM {form}"


def write_school(ctx):
	plan = ctx.plan
	log("School, calendar, subjects and staff")
	settings = frappe.get_single("Smart School Settings")
	settings.update(
		{
			"school_name": "Mwanga Secondary School (Demo)",
			"school_motto": "Elimu ni Ufunguo",
			"school_address": "P.O. Box 100, Moshi, Kilimanjaro",
			"school_phone": "+255 754 000 100",
			"school_email": f"info@{DOMAIN}",
		}
	)
	settings.save(ignore_permissions=True)

	for year in plan.years:
		insert(
			{"doctype": "Academic Year", "year": str(year), "start_date": date(year, 1, 1), "end_date": date(year, 12, 31)},
			str(year),
		)
	for term in plan.terms:
		insert(
			{
				"doctype": "Term",
				"term_name": f"Term {term['number']}",
				"academic_year": str(term["year"]),
				"start_date": term["start"],
				"end_date": term["end"],
			},
			term["name"],
		)
	for form in FORMS:
		insert({"doctype": "Class", "class_name": class_name(form), "level": form})
		for letter in "AB":
			insert({"doctype": "Section", "section_name": letter, "class": class_name(form)}, f"{class_name(form)} {letter}")
	for subject, (code, _) in SUBJECTS.items():
		insert({"doctype": "Subject", "subject_name": subject.title(), "subject_code": code}, subject)
		for form in FORMS:
			insert(
				{
					"doctype": "Class Subject Mapping",
					"class": class_name(form),
					"subject": subject,
					"subject_scope": "All Combinations",
				}
			)

	ctx.headmaster = make_user(*HEADMASTER, "Headmaster")
	ctx.accountant = make_user(*ACCOUNTANT, "Accountant")
	ctx.teacher_names, ctx.teacher_users = {}, {}
	for t in plan.teachers:
		user = make_user(t["email"], t["full_name"], "Teacher")
		doc = insert(
			{
				"doctype": "Teacher",
				"full_name": t["full_name"],
				"email": t["email"],
				"phone": t["phone"],
				"user": user,
				"subjects_taught": [{"subject": s, "class": class_name(f)} for s, f in t["assignments"]],
			}
		)
		ctx.teacher_names[t["key"]], ctx.teacher_users[t["key"]] = doc.name, user
	for form, teacher in plan.class_teachers.items():
		frappe.db.set_value("Class", class_name(form), "class_teacher", ctx.teacher_names[teacher])


def last_form(plan, student):
	year = student["left_after"] or plan.years[-1]
	return max(plan.enrolments[(student["key"], y)] for y in plan.years if y <= year and (student["key"], y) in plan.enrolments)


def exit_date(plan, student):
	"""Students leave at the end of the year: the day Term 3 ends."""
	if not student["left_after"]:
		return None
	return next(t["end"] for t in plan.terms if t["year"] == student["left_after"] and t["number"] == 3)


def write_people(ctx):
	from frappe.model.naming import make_autoname

	plan = ctx.plan
	log(f"{len(plan.students)} students and {len(plan.guardians)} guardians")
	ctx.student_names = {}
	for s in plan.students:
		form = last_form(plan, s)
		doc = insert(
			{
				"doctype": "Student",
				"full_name": s["full_name"],
				"gender": s["gender"],
				"date_of_birth": s["date_of_birth"],
				"admission_date": s["admission_date"],
				"current_class": class_name(form),
				"current_section": f"{class_name(form)} {s['section']}" if s["status"] == "Active" else None,
				"status": s["status"],
				"exit_date": exit_date(plan, s),
			},
			make_autoname(f"STU-{s['entry_year']}-.#####"),
		)
		ctx.student_names[s["key"]] = doc.name

	for g in plan.guardians:
		user = g["email"] and make_user(g["email"], g["full_name"], "Parent")
		insert(
			{
				"doctype": "Guardian",
				"full_name": g["full_name"],
				"phone": g["phone"],
				"email": g["email"],
				"user": user or None,
				"students": [
					{"student": ctx.student_names[s], "relationship": relationship} for s, relationship in g["students"]
				],
			}
		)


def load_grades():
	rows = frappe.get_all("Grading System", fields=["grade", "minimum_mark", "maximum_mark"])
	return lambda score: next(r.grade for r in rows if r.minimum_mark <= score <= r.maximum_mark)


def write_calendar(ctx):
	"""The plan's School Events (the fixed national holidays are already there: the app installs them)."""
	plan = ctx.plan
	log(f"{len(plan.events)} school calendar events")
	for e in plan.events:
		insert(
			{
				"doctype": "School Event",
				"title": e["title"],
				"event_type": e["type"],
				"start_date": e["start"],
				"end_date": e["end"],
				"is_school_day": e["is_school_day"],
				"audience": "Specific Classes" if e["forms"] else "All School",
				"classes": [{"class": class_name(f)} for f in e["forms"] or []],
				"show_on_portal": 1,
				"description": e["description"],
				"sms_reminder": e.get("sms_reminder", 0),
				"sms_days_before": e.get("sms_days_before", 2),
			}
		)


def write_exams(ctx):
	from smart_school.results import recompute_student_term_result, round_half_up
	from smart_school.tasks import ensure_academic_record

	from smart_school.patches.create_external_exam_types import ensure_type

	plan = ctx.plan
	log(f"{len(plan.exams)} exams and {len(plan.results)} exam results")
	exams = {e["key"]: e for e in plan.exams}
	for name in sorted({e["exam_name"] for e in plan.exams if e["kind"] == "external"}):
		ensure_type(name)  # District Exam and Mock are among the defaults of a fresh site
	ctx.exam_names = {}
	for e in plan.exams:
		doc = insert(
			{
				"doctype": "Exam",
				"exam_name": e["exam_name"],
				"term": e["term"],
				"academic_year": str(e["year"]),
				"class": class_name(e["form"]),
				"max_marks": e["max_marks"],
				"weight": e["weight"],
				"is_external": e["kind"] == "external",
				"external_exam_type": e["exam_name"] if e["kind"] == "external" else None,
				"start_date": e["date"],
				"end_date": e["last_day"],
			}
		)
		ctx.exam_names[e["key"]] = doc.name

	grade = load_grades()
	ordered = sorted(plan.results.items(), key=lambda item: (exams[item[0][0]]["date"], item[0]))
	names = {}
	for year in plan.years:
		count = sum(1 for (key, _, _), _ in ordered if exams[key]["year"] == year)
		names[year] = iter(reserve_series(f"EXR-{year}-", count))

	rows = []
	for (key, student, subject), (marks, teacher) in ordered:
		exam = exams[key]
		entered = datetime.combine(exam["date"], datetime.min.time()) + timedelta(
			days=ctx.names.randint(0, 2), hours=ctx.names.randint(9, 17), minutes=ctx.names.randint(0, 59)
		)
		user = ctx.teacher_users[teacher]
		percentage = marks / exam["max_marks"] * 100
		rows.append(
			(
				next(names[exam["year"]]),
				entered,
				entered,
				user,
				user,
				1,
				0,
				ctx.student_names[student],
				subject,
				ctx.exam_names[key],
				marks,
				grade(round_half_up(percentage)),
				ctx.teacher_names[teacher],
				percentage,
			)
		)
	fields = ["name", "creation", "modified", "modified_by", "owner", "docstatus", "idx"]
	fields += ["student", "subject", "exam", "marks", "grade", "teacher", "percentage"]
	frappe.db.bulk_insert("Exam Result", fields, rows)

	pairs = sorted({(student, exams[key]["term"]) for key, student, _ in plan.results})
	log(f"{len(pairs)} student term results")
	for student, term in pairs:
		recompute_student_term_result(ctx.student_names[student], term)

	for year in plan.years:
		if date(year, 12, 31) >= plan.as_of:
			continue  # academic records are made when a year has ended
		for s in plan.students:
			if active_in(plan, s, year):
				ensure_academic_record(ctx.student_names[s["key"]], str(year), class_name(plan.enrolments[(s["key"], year)]))


def write_attendance_and_discipline(ctx):
	plan = ctx.plan
	log(f"{len(plan.attendance)} attendance and {len(plan.discipline)} discipline records")
	class_teacher_users = {form: ctx.teacher_users[t] for form, t in plan.class_teachers.items()}
	rows = []
	for student, day, status, term, form in plan.attendance:
		at = datetime.combine(day, datetime.min.time()) + timedelta(hours=8, minutes=ctx.names.randint(0, 40))
		user = class_teacher_users[form]
		rows.append((row_name(ctx), at, at, user, user, 0, 0, ctx.student_names[student], day, class_name(form), status, term))
	fields = ["name", "creation", "modified", "modified_by", "owner", "docstatus", "idx"]
	frappe.db.bulk_insert("Attendance", [*fields, "student", "date", "class", "status", "term"], rows)

	rows = []
	for student, day, incident, severity, action in plan.discipline:
		at = datetime.combine(day, datetime.min.time()) + timedelta(hours=ctx.names.randint(9, 15))
		user = class_teacher_users[plan.enrolments[(student, day.year)]]
		rows.append(
			(row_name(ctx), at, at, user, user, 0, 0, ctx.student_names[student], day, incident, severity, action)
		)
	frappe.db.bulk_insert(
		"Discipline Record", [*fields, "student", "date", "incident_type", "severity", "action_taken"], rows
	)


def write_fees(ctx):
	"""Fee Payments go through the app (their status and balance come from the fee statement), oldest first."""
	from frappe.model.naming import make_autoname

	plan = ctx.plan
	for (form, term), amount in plan.fees.items():
		insert({"doctype": "Fee Structure", "class": class_name(form), "term": term, "amount": amount})

	payments = sorted(plan.payments, key=lambda p: (p[3], p[0], p[1]))
	log(f"{len(payments)} fee payments (the slowest part)")
	for i, (student, term, amount, day, method) in enumerate(payments, start=1):
		doc = frappe.get_doc(
			{
				"doctype": "Fee Payment",
				"student": ctx.student_names[student],
				"term": term,
				"amount_paid": amount,
				"payment_date": day,
				"payment_method": method,
				"status": "Partial",
			}
		)
		doc.insert(ignore_permissions=True, set_name=make_autoname(f"RCPT-{day.year}-.#####"))
		doc.submit()
		if i % 1000 == 0:
			log(f"  {i} payments")


def publish_exams(ctx):
	"""Exams are published a week after they were sat (without notifying anyone)."""
	for e in ctx.plan.exams:
		if e["published_on"]:
			at = datetime.combine(e["published_on"], datetime.min.time()) + timedelta(hours=10)
			frappe.db.set_value(
				"Exam",
				ctx.exam_names[e["key"]],
				{"results_published": 1, "published_on": at, "first_published_on": at},
				update_modified=False,
			)


def result_name(ctx, plant, student):
	return frappe.db.get_value(
		"Exam Result",
		{"exam": ctx.exam_names[plant["exam"]], "subject": plant["subject"], "student": ctx.student_names[student], "docstatus": 1},
		"name",
	)


def amend(result, change, user):
	"""Cancel a submitted Exam Result and submit a corrected copy, as `user`, through the app."""
	frappe.set_user(user)
	doc = frappe.get_doc("Exam Result", result)
	doc.flags.ignore_permissions = True
	doc.cancel()
	new = frappe.copy_doc(doc)
	new.docstatus = 0
	new.amended_from = doc.name
	max_marks = frappe.db.get_value("Exam", doc.exam, "max_marks")
	new.marks = clamp(doc.marks + change, 0, max_marks)
	new.insert(ignore_permissions=True)
	new.submit()
	frappe.set_user("Administrator")
	return new


def apply_integrity_plants(ctx):
	from smart_school.results import unpublish_exam_results

	plan = ctx.plan
	for plant in plan.plants:
		if not plant["done"]:
			continue
		exam = next(e for e in plan.exams if e["key"] == plant["exam"])
		teacher = ctx.teacher_users[teacher_for(plan, plant["subject"], exam["form"])]
		if plant["alert_type"] == "Changed After Publish":
			first, second = plant["students"]
			amend(result_name(ctx, plant, first), 8, teacher)
			amend(result_name(ctx, plant, second), -5, ctx.headmaster)
		elif plant["alert_type"] == "Results Unpublished":
			# The Headmaster unpublishes the exam to correct a mark; it is left for them to publish again
			frappe.set_user(ctx.headmaster)
			unpublish_exam_results(ctx.exam_names[plant["exam"]])
			amend(result_name(ctx, plant, plant["students"][0]), 10, teacher)


def write_interventions(ctx):
	"""Through the app, with the Early Warning snapshot the generator saw (no model exists yet at this point)."""
	from smart_school.reports import ALREADY_AT_RISK, EMERGING
	from smart_school.risk_model import get_probability_level
	from smart_school.tasks import get_risk_score

	plan = ctx.plan
	log(f"{len(plan.interventions)} interventions")
	settings = frappe.get_cached_doc("Smart School Settings")
	terms = {t.name: t for t in frappe.get_all("Term", fields=["name", "start_date", "end_date"])}
	outcomes = {
		"Completed": "Done as planned; followed up with the student.",
		"Cancelled": "Could not be arranged this term.",
	}
	for i in plan.interventions:
		student = ctx.student_names[i["student"]]
		probability = round(i["risk"] * 100, 1)
		rule_score, rule_level, _ = get_risk_score(student, terms[i["baseline_term"]], settings)
		reasons = [f"Average of {i['average']:.0f}% in {i['baseline_term']}"]
		if i["absence"] > 0.09:
			reasons.append(f"Missed {i['absence']:.0%} of school days in {i['baseline_term']}")
		doc = frappe.get_doc(
			{
				"doctype": "Student Intervention",
				"student": student,
				"class": class_name(i["form"]),
				"term": i["term"],
				"baseline_term": i["baseline_term"],
				"source": "Early Warning",
				"intervention_type": i["type"],
				"responsible": ctx.teacher_users[i["responsible"]],
				"start_date": i["start"],
				"follow_up_date": i["follow_up"],
				"status": i["status"],
				"outcome": outcomes.get(i["status"]),
				"parent_informed": i["parent_informed"],
				"description": f"{i['type']} after the Early Warning of {i['term']}.",
				"probability": probability,
				"probability_level": get_probability_level(probability, settings),
				"early_warning_group": ALREADY_AT_RISK if i["at_risk"] else EMERGING,
				"rule_score": rule_score,
				"rule_level": rule_level,
				"reasons": "\n".join(reasons),
			}
		)
		doc.flags.keep_snapshot = True
		doc.insert(ignore_permissions=True)


def run_daily_jobs(ctx):
	from smart_school import interventions, marks_alerts, tasks

	log("Risk scores, performance insights and marks checks")
	tasks.calculate_all_risk_scores()
	tasks.generate_performance_insights()
	marks_alerts.find_changes_after_publish()
	settings = marks_alerts.get_settings()
	for exam in ctx.exam_names.values():
		marks_alerts.run_exam_checks(exam, settings)
	interventions.send_follow_up_reminders()


def intervention_summary(plan):
	"""What was planted, so the Intervention Outcomes report can be checked against it."""
	counts = lambda key: {v: sum(1 for i in plan.interventions if i[key] == v) for v in sorted({i[key] for i in plan.interventions})}
	finished = [i for i in plan.interventions if i["status"] in ("Completed", "Cancelled")]
	completed_share = sum(1 for i in finished if i["status"] == "Completed") / len(finished) if finished else 0
	realized = [realized_effect(plan, i) for i in finished]
	realized_completed = [r for i, r in zip(finished, realized) if i["status"] == "Completed" and r is not None]
	return {
		"planted_effect_points": INTERVENTION_EFFECT,
		"effect_applies_to": "every mark of the intervention's term, for Completed interventions only",
		"total": len(plan.interventions),
		"by_status": counts("status"),
		"by_type": counts("type"),
		"by_term": counts("term"),
		"completed_share_in_finished_terms": round(completed_share, 3),
		"expected_per_protocol": INTERVENTION_EFFECT,
		"expected_itt": round(INTERVENTION_EFFECT * completed_share, 2),
		# What reached the term averages (rounding of marks and the 100 cap make it differ a little from the plant)
		"realized_per_protocol": round(sum(realized_completed) / len(realized_completed), 2) if realized_completed else None,
		"realized_itt": round(sum(r for r in realized if r is not None) / len([r for r in realized if r is not None]), 2)
		if any(r is not None for r in realized)
		else None,
	}


def calendar_summary(plan):
	"""The calendar events the demo added, and the school days of each started term (holidays and breaks out)."""
	kinds = {}
	for e in plan.events:
		kinds[e["type"]] = kinds.get(e["type"], 0) + 1
	return {
		"events": dict(sorted(kinds.items())),
		"school_days": {t["name"]: len(t["days"]) for t in plan.terms if t["days"]},
		"weekdays_off": {
			t["name"]: sum(1 for d in t["off"] if d.weekday() < 5 and t["start"] <= d <= min(t["end"], plan.as_of))
			for t in plan.terms
			if t["days"]
		},
	}


def realized_effect(plan, intervention):
	"""The intervention term's average with the planted effect minus the same average without it."""
	exams = {e["key"]: e for e in plan.exams if e["term"] == intervention["term"]}
	with_effect, without = {}, {}
	for (key, student, subject), (marks, _) in plan.results.items():
		if student == intervention["student"] and key in exams:
			exam = exams[key]
			simulated, original = plan.without_intervention.get((key, student, subject), (marks, marks))
			if marks != simulated:  # a planted marks problem replaced the mark, whatever the intervention did
				original = marks
			with_effect.setdefault(subject, []).append((marks / exam["max_marks"] * 100, exam["weight"] or 0))
			without.setdefault(subject, []).append((original / exam["max_marks"] * 100, exam["weight"] or 0))
	if not with_effect:
		return None  # sat no exam that term
	if intervention["status"] != "Completed":
		return 0.0
	return term_average(with_effect) - term_average(without)


def term_average(by_subject):
	"""Like the app's term average: each subject's (weighted) percentage rounded half up, then their mean."""
	scores = []
	for rows in by_subject.values():
		if all(w for _, w in rows):
			scores.append(half_up(sum(p * w for p, w in rows) / sum(w for _, w in rows)))
		else:
			scores.append(half_up(sum(p for p, _ in rows) / len(rows)))
	return sum(scores) / len(scores)


def get_demo_parent(ctx):
	"""A guardian with a portal user and more than one active child at the school."""
	for guardian in frappe.get_all("Guardian", filters={"user": ["is", "set"]}, fields=["name", "user"], order_by="name asc"):
		children = frappe.get_all("Guardian Student Link", filters={"parent": guardian.name}, pluck="student")
		if frappe.db.count("Student", {"name": ["in", children], "status": "Active"}) > 1:
			return {"user": guardian.user, "guardian": guardian.name, "children": children}
	return None


def make_manifest(ctx):
	plan = ctx.plan
	statuses = {}
	for s in plan.students:
		statuses[s["status"]] = statuses.get(s["status"], 0) + 1

	plants = []
	for plant in plan.plants:
		exam = ctx.exam_names[plant["exam"]]
		# Swapped marks send the strong students to 0: they get the Dropped To Zero alert instead
		types = [plant["alert_type"]]
		if plant["alert_type"] == "Unusual Student Change":
			types.append("Dropped To Zero")
		filters = {"alert_type": ["in", types], "exam": exam}
		if plant["alert_type"] != "Results Unpublished":
			filters["subject"] = plant["subject"]
		found = frappe.get_all("Marks Alert", filters=filters, pluck="student")
		students = [ctx.student_names[s] for s in plant["students"]]
		if plant["alert_type"] in ("Unusual Student Change", "Dropped To Zero"):
			detected = sorted(s for s in found if s in students) == sorted(students)
		else:
			detected = bool(found)
		plants.append(
			{
				"alert_type": plant["alert_type"],
				"exam": exam,
				"subject": plant["subject"],
				"students": students,
				"planted": plant["done"],
				"detected": detected if plant["done"] else None,
			}
		)

	alerts = frappe.get_all("Marks Alert", fields=["alert_type", "count(*) as count"], group_by="alert_type")
	divisions = frappe.get_all("Student Term Result", fields=["division", "count(*) as count"], group_by="division")
	class_teachers = {class_name(f): ctx.teacher_users[t] for f, t in plan.class_teachers.items()}
	return {
		"seed": plan.seed,
		"as_of": plan.as_of,
		"years": plan.years,
		"students": statuses,
		"active_by_form": {
			class_name(f): frappe.db.count("Student", {"status": "Active", "current_class": class_name(f)}) for f in FORMS
		},
		"guardians": len(plan.guardians),
		"guardians_with_portal_user": frappe.db.count("Guardian", {"user": ["is", "set"]}),
		"teachers": len(plan.teachers),
		"exams": len(plan.exams),
		"exams_published": frappe.db.count("Exam", {"results_published": 1}),
		"exam_results": frappe.db.count("Exam Result", {"docstatus": 1}),
		"student_term_results": frappe.db.count("Student Term Result"),
		"divisions": {d.division: d.count for d in divisions},
		"attendance": len(plan.attendance),
		"discipline_records": len(plan.discipline),
		"fee_payments": len(plan.payments),
		"marks_alerts": {a.alert_type: a.count for a in alerts},
		"plants": plants,
		"headmaster": ctx.headmaster,
		"accountant": ctx.accountant,
		"class_teachers": class_teachers,
		"demo_parent": get_demo_parent(ctx),
		"interventions": intervention_summary(plan),
		"calendar": calendar_summary(plan),
	}
