# Smart School — An Integrated Academic Management System

A [Frappe](https://frappeframework.com) v15 app for Tanzanian O-level secondary schools (Form 1–4). It automates
result processing (exam marks → subject scores → grades, points and divisions), gives staff reports and dashboards
for decision making, and gives parents a Swahili portal with their children's results, fees and announcements.

> The Python module and folder are named `an_intergrated_academic_management_system` (with a historical typo).
> Do not rename them: doctypes, patches and records are bound to that module name.

## Features

**Results**
- Exams per class and term, each with its own maximum marks and an optional weight (weights of a class's exams in
  a term are all set and add up to 100, or all empty).
- A subject's term score is the weighted average of the percentages of the exams the student sat (plain average when
  there are no weights), rounded half up (74.5 → 75), then graded from the **Grading System** table.
- Division from the best 7 subjects via the **Division Grading** table; fewer than 7 subjects gives *Incomplete*.
  Both tables are editable data and reject overlapping ranges.
- Marks import: JSON list, single-subject CSV, and wide CSV/XLSX (subjects by name or code, students by admission
  number or unique full name, Excel BOM handled, errors reported per row). Teachers may only enter the subjects
  and classes they are assigned to.
- Results are **published per exam** by the Headmaster; parents see published exams only, and the term summary once
  every exam of that term is published. One notification per student per published exam.
- **Report card** print format (English) with each exam's marks, term score, grade, remark, points, division,
  *Position X out of Y*, attendance, class teacher's and headmaster's comments and the next term's opening date.
  The Headmaster can print a whole class in one PDF.
- **Report card verification**: once every exam of the term is published for the class, each issued report card
  (portal PDF, class print, desk print) gets a random token and a QR code to `/verify/<token>`, a public Swahili page
  (no login, not indexed, rate limited) that shows the certified results only: valid, changed since (with both; the
  current results only if published) or not valid. Printed earlier, the card is a draft ("RASIMU / DRAFT", no QR).
  The Headmaster can revoke a token. The QR uses the site's `host_name`.

**Fees and payments**
- One fee statement per student (`smart_school.fees.get_fee_statement`): every started term priced with the class the
  student was in, submitted payments only, and overpayments paying the oldest debt first ("Salio la ziada").
- Fee Payment is submittable (`RCPT-.YYYY.-.#####`), immutable once submitted, and notifies the guardian once.
- Mobile-money **demo** payments from the portal, behind the *Enable Demo Payments* switch in Smart School Settings.
  `payment_gateway.py` is the base for a real aggregator integration.

**Parent portal** (`/parent-portal`, Swahili, mobile friendly)
- Dashboard per child: latest published results, attendance, fee balance, announcements, trend chart and gentle
  alerts (no risk scores are shown to parents).
- Results with report card PDF download, fees with payment, discipline, announcements and a notification bell.
- Parents are Website Users; they can only reach their own children's data.
- An **SMS switch** on the home page: the parent turns SMS on or off for themselves.

**SMS to parents** (see *SMS to parents* below)
- Results (the exam average and, once the term is complete, the division, with a short portal link), payment
  receipts, fee reminders (before a term and when fees are overdue) and announcements, in editable Swahili templates.
  Never early warnings, interventions, discipline or marks alerts.
- Only to guardians who agreed (admission form, parent portal, or a paper form recorded by the Headmaster).
- Off / Test / Live; daily and monthly limits, a price per SMS, quiet hours (21:00–07:00), retries, an SMS Outbox
  and an SMS Summary report.

**School calendar** (see *School calendar* below)
- School Events (holidays, breaks, exam periods, meetings, sports day, graduation...) for the whole school or some
  classes; terms and exams (their own dates) appear on the calendar by themselves. Month view on the desk; a Swahili
  "Kalenda ya Shule" page on the parent portal; optional SMS reminders.
- One rule for school days, used everywhere attendance is counted: absence is measured on school days only.

**Class attendance**
- *Class Attendance* page (Academics and Headmaster workspaces), made for a phone: pick the class and the date;
  everyone starts Present (or as already recorded, or Excused on an approved leave); tap P / A / L / E for the few
  who differ (each button explains itself) and save once. Saving again corrects, never duplicates.
- A day that is not a school day (weekend, holiday, break: the calendar says which) is saved only after a warning,
  and its records are not counted. Future days and days outside the terms are refused.
- Attendance is kept by the class teacher of the class, and by the Headmaster and System Manager for every class:
  on the doctype itself (list, form and API), not only in the page.

**Leave requests (ruhusa)**
- On the parent portal (`/parent-portal/ruhusa`, Swahili): a parent asks leave for one of their own children, for
  dates up to *Leave Requests: Days Back* (7) days back, with a short reason and optionally a doctor's note (PDF or
  picture, 5 MB at most, checked and kept private). They follow the status there, can withdraw a waiting request,
  and get an SMS with the answer if they agreed to SMS (never the reason).
- The class teacher gets a ToDo (the Headmaster when the class has none) and approves or rejects with a note for the
  parent. Approved: the school days of the leave already recorded Absent become Excused; Present and Late stay as
  they are (the child came). Class Attendance shows the students on leave as Excused. The Headmaster can withdraw an
  approved leave: only the records it changed, if still Excused, go back to Absent.
- The reason and the file are seen by the Headmaster and that class's teacher only; attendance shows "Excused".

**Staff**
- Workspaces: **Headmaster**, **Academics** (teachers), **Finance** (accountant) and **School Settings**
  (system manager), each opened by default after login.
- Script reports: Class Merit List, Subject Performance, Division Summary, Fee Collection and Defaulters,
  Attendance Summary, At-Risk Students, My Classes, Pending Report Card Comments, Early Warning and Model
  Performance (see *Analytics methodology*), plus Marks Alerts for the Headmaster. Teachers only see the classes and
  subjects they are assigned to; accountants only see fee reports.
- Daily jobs: risk score per student (attendance, discipline, low average, failed subjects, decline; weights and
  levels in Smart School Settings), performance insights per class and subject, and academic records for ended years.
- Student Promotion Tool: promote a class to the next level, keep repeaters, graduate Form 4.
- Public admission form at `/apply-online`, all in Swahili like the parent portal: labels, help, the calendar,
  error messages (checked in the browser and again on the server) and the thank-you page. Gender shows as
  Mvulana / Msichana and the class as "Kidato cha Kwanza"..., stored as before (Male / Female, the Class name);
  the phone number is checked as a Tanzanian mobile number and stored as +255-7XXXXXXXX. The Headmaster approves
  (certificate attached or verified), which creates the student and links or creates the guardian.

## Roles

| Role | Can do |
|---|---|
| System Manager | Everything, including Smart School Settings, grading tables and terms |
| Headmaster | Admissions, students, guardians, teachers, exams (publish), term results and comments, attendance of every class, school calendar, all reports, promotion |
| Teacher | Enter/import marks for assigned subjects, discipline, class teacher comments, academic reports for own classes; attendance and leave requests only as class teacher of the class |
| Accountant | Fee structures, fee payments (submit/cancel), fee reports |
| Parent | Parent portal only (Website User), including SMS consent and leave requests for their own children |

## Setup

```bash
cd ~/frappe-bench
bench get-app <repository-url> smart_school
bench --site <site> install-app smart_school
bench --site <site> migrate
bench build --app smart_school
```

`after_install` creates the roles, the provisional grading and division tables with grade remarks, the risk score
defaults, the external exam types (District Exam, Regional Exam, Mock) and the unique index on term results. Then, as System Manager:

1. **Smart School Settings**: school name, motto, logo, address; risk score weights; turn *Enable Demo Payments* on
   only for demonstrations.
2. **Academic Year** and **Terms** (terms must lie inside their year and must not overlap), **Classes** (with a level
   1–4 and a class teacher), **Subjects**, **Combinations** and **Class Subject Mapping**.
3. **Fee Structure** per class and term, **Teachers** (a user with the Teacher role is created from the email) and
   their subject assignments, **Students** and **Guardians** (a portal user is created from the email).
4. Check the provisional **Grading System** / **Division Grading** values with the academic master.
   Set `host_name` (below) before printing report cards: their QR codes use it.
5. Outgoing email: an Email Account set as default outgoing. SMS start **Off**: set up Frappe's SMS Settings (the
   provider's URL and parameters), try **Test** first (see *SMS to parents*), then **Live**.
   Set `host_name` in the site config so links in emails and the report card QR codes point to the real address,
   e.g. `bench --site <site> set-config host_name "https://school.example"`.

The app cannot share a site with ERPNext, Education or HRMS: doctype names clash (Student, Guardian, Attendance,
Fee Structure, Academic Year, Student Admission).

## Running the tests

Tests build their own "_Test" school and never need real data, but run them on a separate site:

```bash
bench new-site test.localhost --db-root-username root --admin-password <password>
bench --site test.localhost set-config allow_tests true
bench --site test.localhost install-app smart_school
bench --site test.localhost run-tests --app smart_school
```

A single suite: `bench --site test.localhost run-tests --module smart_school.tests.test_payments`.

| Suite | Covers |
|---|---|
| `test_install` | Fresh install: grading/division tables, remarks, risk defaults, roles, synced reports and workspaces |
| `test_permissions` | Guest, parent and teacher access; admission approval; comments by their owners |
| `test_imports` | Marks import roles and assignments, CSV/BOM, wide CSV, per-row errors |
| `test_payments` | Payment validation, double confirmation, demo switch, XSS, fee statement credit, Fee Payment lifecycle |
| `test_results` | Weights, 74.5 → A, Incomplete, amend after cancel, grading and weight validation |
| `test_publish` | Who publishes, what parents see, one notification per student |
| `test_reports` | Merit ranking, subject statistics, defaulters, report permissions |
| `test_report_card` | Report card data, PDF, class printing, parent download ownership and publishing |
| `test_portal` | Base template on every page, guest redirects, parent home page, dashboard, workspaces |
| `test_tasks` | Risk score, insights, promotion tool, academic records |
| `test_student_exit` | Exit date, fees only for terms that started before a student left, defaulters and portal rules |
| `test_marks_alerts` | Every marks check (swapped marks as pairs too), saving and auto-resolving alerts, publishing with warnings, who sees alerts |
| `test_demo_data` | Generator guard (never jonbale), reproducible seed, realistic links, a small school saved through the app |
| `test_risk_model` | Features, labels, time split, bootstrap, decision, model file checks, ablation, predictions, data guard |
| `test_early_warning` | Early Warning groups, class teacher scope, Emerging Risk card, rule-based fallback, nothing for parents |
| `test_report_card_verification` | Random tokens, same token for an unchanged card, valid/changed/invalid pages, nothing extra shown, revoke, drafts, rate limit, QR in the PDF |
| `test_interventions` | Snapshot, who sees and edits, reminders and card, Hatua column, matching, per-protocol and intention-to-treat, minimum sample, report warning |
| `test_school_calendar` | School days (weekends, holidays, breaks, class events, Saturdays), terms and exams from their own dates, attendance on school days, completeness and the Early Warning note, desk and portal calendars, SMS reminders |
| `test_class_attendance` | Class teacher only for their class on the doctype and the API, Headmaster everywhere; the page: classes per role, Present by default, recorded days, weekend and holiday warnings, future and between-terms days refused, saving and correcting without duplicates |
| `test_leave` | A parent asks for their own child only, Swahili messages, private and checked files, withdrawing a waiting request; who sees reasons and files; approving excuses school days only, withdrawing restores, the attendance page shows the leave; the SMS never carries the reason |
| `test_admission_form` | The public form in Swahili, values stored as before, Swahili messages for each mistake, desk entry unchanged |
| `test_sms` | SMS parts (GSM-7 / UCS-2), placeholders, one SMS with long names, modes, consent (admission, portal, paper), numbers, quiet hours, limits, retries, expiry, once per exam, fee reminders and students who left, no sensitive SMS, who sees the outbox and report |

## School calendar

Code: `smart_school/school_calendar.py`; doctype **School Event**; desk calendar (School Event > Calendar); portal
page `/parent-portal/kalenda` (short link `/kalenda`); number card **Attendance Completeness**.

- **School days**: the days of a term, Monday to Friday (*Saturday Is a School Day* in Smart School Settings adds
  Saturdays), without the days covered by a School Event that is not a school day (a holiday, a midterm break) for
  the whole school or the class. A School Event marked as a school day turns a weekend day into one (a make-up
  Saturday); it never cancels a holiday.
- **Holidays**: the fixed national holidays (New Year, Zanzibar Revolution, Karume, Union, Workers, Saba Saba, Nane
  Nane, Nyerere, Independence, Christmas, Boxing Day) are installed, repeating every year. Holidays that move (Good
  Friday, Easter Monday, Eid, Maulid) are added by the Headmaster each year.
- **Terms and exams** are read from their own dates each time (Exam has an optional start and end date): change a
  term or an exam and both calendars follow. They cannot be dragged on the calendar; they are changed on their forms.
- **Attendance on school days only**: the attendance summary, the absence chart, the parent dashboard, the report
  card, the risk score and the risk model all use `count_attendance`: records on days that are not school days are
  left out (shown as *Not School Days* in the Attendance Summary). A school day without a record is not absence: it
  lowers the **attendance completeness** (school days with attendance taken / school days so far), shown per class in
  the Attendance Summary and on the Headmaster workspace. Early Warning notes the classes below *Attendance
  Completeness Warning Below* (80%): their absence rates rest on few days.
- **Model**: the absence rate now counts school days only, so the feature set is version 5 (same features); a
  version 4 model is refused and the model must be trained again.
- **Parent portal**: coming events (60 days) and a month grid, in Swahili, for the parent's children's classes:
  events marked *Show on Parent Portal*, term openings and closings, and their classes' exams.
- **SMS reminder** (optional, per event): *Remind Parents by SMS* with *Days Before* sends one SMS per guardian of the
  event's classes through the SMS system (consent, limits, quiet hours); switching it on shows the count and cost
  first. Not for events that repeat every year.

## SMS to parents

Code: `smart_school/sms.py` (queue, consent, templates, limits), `smart_school/sms_providers.py` (the gateway);
doctypes **SMS Outbox** and **SMS Template**; report **SMS Summary** (Headmaster and Finance workspaces).

- **Modes** (Smart School Settings > SMS to Parents): *Off* writes nothing. *Test* does everything (consent,
  numbers, templates, limits, quiet hours) and records each message in the SMS Outbox as *Test* instead of sending
  it. *Live* sends through the provider; it cannot be turned on before the provider is set up.
- **Every message** is one SMS Outbox row for one guardian: type, number, text, characters, SMS parts, estimated
  cost, status (*Queued*, *Sent*, *Failed*, *Test*, *Skipped*), the reason or provider error, and the record it
  is about. Each exam, payment, reminder (per term) and announcement goes to a guardian once, even if results are
  published again.
- **Consent**: *Agrees to Receive SMS* on the Guardian, with how (Admission, Portal, Staff), when and by whom.
  Guardians who were there before SMS existed start without consent. Parents tick a box on the admission form or
  use the switch on the portal. The Headmaster records paper forms for many guardians at once (Guardian list >
  Actions > *Record SMS Consent (Paper)*, with the date on the form). Without consent a message is *Skipped*.
  Consent is checked again just before sending.
- **Numbers** are sent as 255XXXXXXXXX (a Tanzanian mobile number, 06/07); anything else is *Failed* with the
  reason, and *Try Again* uses the guardian's corrected number.
- **Templates** (SMS Template, one per type) use `{placeholders}`; unknown ones are refused. The form shows the
  characters and SMS parts as typed and for a message with long real names. One SMS is 160 characters (GSM-7; 153
  per part when longer); `^{}[]~|€\` count 2, and any other character (an emoji, a curly quote) makes it UCS-2
  (70, 67 per part). When a message would need 2 SMS the student's name is shortened (first and last name, then an
  initial) and an announcement's title is cut. Portal links are short: `/matokeo`, `/ada`, `/matangazo`.

| Type | Sent when | Default text |
|---|---|---|
| Results Published | the Headmaster publishes an exam and ticks *Also send SMS* | `{shule}: {mwanafunzi} - {mtihani}: wastani {wastani}%{division}. Zaidi: {kiungo}` |
| Payment Received | a payment is submitted | `{shule}: Tumepokea TZS {kiasi} ada ya {mwanafunzi} ({muhula}). Risiti {risiti}. Salio TZS {salio}.` |
| Fee Reminder | once, in the 7 days before a term starts, if anything is owed (switch, default off) | `{shule}: {muhula} inaanza {tarehe}. Ada ya {mwanafunzi}: TZS {kiasi}{deni}. Lipa: {kiungo}` |
| Fee Overdue | once, from 30 days after a term started (for 14 days, so old terms are not dug up), if still owed (switch, default off) | `{shule}: {mwanafunzi} ana deni la ada TZS {salio} ({muhula}, siku {siku}). Tafadhali lipa: {kiungo}` |
| Announcement | the Headmaster presses *Also Send by SMS* | `{shule}: Tangazo - {kichwa}. Soma zaidi: {kiungo}` |
| Event Reminder | daily, from *Days Before* a School Event with *Remind Parents by SMS* | `{shule}: Kumbusho - {tukio}, {tarehe}. Kalenda ya shule: {kiungo}` |
| Leave Decision | a leave request is approved or rejected (to the parent who asked) | `{shule}: Ombi la ruhusa ya {mwanafunzi} ({tarehe}) {uamuzi}. Zaidi: {kiungo}` |

  `{wastani}` is the student's average in that exam; `{division}` is ", Division II" once every exam of the term is
  published, else nothing. Before-term reminders go to active students still at school; nobody gets a reminder
  for a term that started after they left.
- **Cost and safety**: price per SMS (TZS 25), daily limit (1,500 SMS) and monthly limit (5,000), counted in SMS
  parts sent or recorded in Test mode. Before a bulk send (publishing results, an announcement) a dialog shows the
  messages, SMS, cost, how many are skipped or have a wrong number, and what is left of the limits; a batch that
  does not fit in the month cannot be confirmed, and what does not fit in the day waits for the next. Turning a
  reminder switch on first shows who would get one today and the cost. Messages written between 21:00 and 07:00
  wait for 07:00. A background job sends every 5 minutes; provider errors are tried again after 5, 30 and
  120 minutes (3 attempts), and what is still unsent after 72 hours is dropped (*Skipped*, Expired).
- **Who sees what**: the Headmaster and System Manager see every message and the report; the Accountant the fee
  messages only; teachers and parents none.
- **Another provider**: write a class with `send(phone, text)` returning `SendResult` (see `sms_providers.py`) and
  register it in an app's hooks: `smart_school_sms_providers = {"Beem": "my_app.sms.BeemProvider"}`; then choose
  it in *SMS Provider*. The queue and its rules do not change.

## Analytics methodology

Two analytics support the Headmaster: **marks alerts** point at marks that may need a second look, and the
**early-warning model** estimates which students will be at risk next term. Both were built and measured on a
synthetic school (see *Demo results*); the numbers there are not evidence about a real school.

### Marks alerts

Code: `smart_school/marks_alerts.py`; doctype **Marks Alert**, readable by the Headmaster and System Manager (a
teacher sees an alert only when it is assigned to them). The checks run before an exam is published (a warning,
never a block: the exam's timeline notes *Published with N open marks alerts*) and every night for the exams of
the current and previous term. Alert texts are neutral: they ask for a check, they never accuse.

**Statistical checks**, per subject of an exam, with the defaults of *Smart School Settings → Marks Alerts*. They
can be switched off there, and their alerts close as *Auto-resolved* when the pattern is gone.

| Alert | Rule | Severity |
|---|---|---|
| Many Identical Marks | ≥ 40% of the class has the same raw mark (0 and full marks are not counted) | Medium |
| Many Zero Marks | ≥ 20% of the class has 0 | Medium |
| Many Round Numbers | ≥ 80% of raw marks are multiples of 5 (0 and full marks not counted). Raw marks, not percentages: out of 40, percentages would change the ~20% base rate | Low |
| Very Low Spread | standard deviation of the percentages < 3 points | Medium |
| Unusual Class Average | robust z-score (median and MAD of the class averages of at least 4 earlier exams of the subject in the same Form) > 3.5 **and** at least 10 points from the usual average. School exams are compared with school exams; an external exam (*External Exam* ticked on the Exam, with its type chosen from **External Exam Type**) only with earlier external exams of the same type, e.g. a District Exam with District Exams. With too little history of its kind only this check is skipped | Medium |
| Unusual Student Change | the student's change minus the class's median change (residual): robust z > 4.5 **and** ≥ 20 points. A hard exam that lowers everyone raises nothing | Low (Medium from z ≥ 9) |
| Dropped To Zero | ≥ 30% in the previous exam and 0 now (not when the class already has Many Zero Marks); one alert per student | Medium |
| Possibly Swapped Marks | marks typed against each other's names: pairs of students, one up and one down, each with a robust z ≥ 3.5 (*Swapped Marks: z Above*) and ≥ 20 points more than the class, the smaller move at least half the larger. One alert per subject of an exam, listing every such pair (a student can be in several; the scripts tell which) | Medium |

Class checks need at least 10 students; Dropped To Zero applies to any class size.

*Why a pair check.* One swap moves two students by a similar amount in opposite directions; looking for that pair
finds what the student-by-student check misses at z 4.5 without lowering it. Measured on 30 generated schools
(seeds 1–29 and 42; each has 2 pairs swapped between the two weakest and the two strongest students of a class,
120 students in all; the same code as the app, outside a site):

| | Swapped students found | Schools with all 4 | Alerts not about the plant, 3 years | In the current and previous term |
|---|---|---|---|---|
| Unusual Student Change alone (z 4.5) | 52.5% | 5 of 30 | 10.0 | 1.8 |
| Possibly Swapped Marks (z 3.5) | 78.3% | 18 of 30 | 6.5 (at most 12) | 1.2 (at most 4) |
| Both | **79.2%** | 18 of 30 | 16.5 | 3.0 |

For comparison, lowering the general check to z 3.5 finds 81.7% but raises 73.6 other alerts over 3 years; at z
3.25 the pair check finds about 84%, with more alerts (about 24 pairs over 3 years before they are grouped into
one alert per subject). Requiring that the swapped-back
marks look ordinary, or a closer size ratio (0.7), lowered recall more than it lowered other alerts, so neither is
used. In 3 of the 30 schools neither check finds anything; the demo school (seed 42) is one of them (z 3.4 and 3.3
for the two who went up).

**Integrity checks** always run and are never closed automatically:

| Alert | Rule | Severity |
|---|---|---|
| Changed After Publish | any mark submitted, cancelled or edited after the exam was *first* published, by anyone, the Headmaster included. `first_published_on` is kept when results are unpublished, so unpublish → change → publish is still seen | High |
| Entered By Unassigned User | marks entered by a user who is not assigned to the subject in that class (Headmaster, System Manager and Administrator excepted) | Medium |
| Results Unpublished | every unpublishing, also noted on the exam's timeline | Medium |

### Early-warning model

Code: `smart_school/risk_model.py`; doctypes **Risk Model** (with coefficient and ablation tables) and **Risk
Prediction**; reports **Early Warning** and **Model Performance**; number card **Emerging Risk**.

- **Unit**: a student and two consecutive finished terms *t* and *t + 1*. Students who later left the school are
  included (their history counts); only Active students get predictions.
- **Label**: term *t + 1* ends in Division IV or 0, or with 3 or more subjects graded F. A term *t + 1* that is
  *Incomplete* (fewer than 7 subjects) is left out.
- **Features** (feature set version 5, from term *t* only): the term average and the absence rate on school days
  (Absent counts 1, Late ½, Excused 0; version 4 had the same features but counted every record). Gender is never a feature; it is used only to compare fairness. Earlier versions also had
  discipline points (v1), subjects with F and "no previous term" (up to v2), and the change in average (up to v3);
  see *Ablation*.
- **Model**: `StandardScaler` + `LogisticRegression` (L2, C = 1, no class weights, so the probabilities keep their
  meaning), trained with scikit-learn. It is saved as a **private JSON file**: ordered features, feature set
  version, scaler and coefficients. There is no pickle, a file made for another feature set is refused, and
  predictions are computed from the file without scikit-learn.
- **Split by time**: the two most recent finished target terms are the test set, everything before them trains.
  After the test, the model in use is refitted on all student-terms; the stored metrics are those of the test.
- **Data guard**: with fewer than 200 training student-terms or fewer than 20 positives no model is trained, the
  rule-based risk score stays in use and the reason is shown. While the data does not change, no new
  *Insufficient Data* record is made.
- **Comparison**: the existing rule-based risk score of the same term, on the same test rows. Measures: AUC;
  precision and recall among the 10% ranked highest in each term; confusion matrices; Brier score; calibration by
  decile; fairness by gender at the top-10% cut (warning above a 10-point gap); and **new risk**, the same measures
  on students who were not at risk in term *t* (top 10% taken within that group).
- **Bootstrap**: 1,000 resamples with seed 42. Students are resampled, not rows: a student appears in both test terms
  and those rows are not independent.
- **Becoming Active**: only when the lower end of the 95% interval of (model AUC − rule AUC) is above 0 **and** the
  model's precision in the top 10% is not lower than the rule-based score's. Otherwise the model is *Rejected* and
  the rule-based score stays in use. One model is Active at a time; the previous one becomes *Retired*.
- **Ablation**: every training retrains the model without each feature in turn and records the test AUC, overall and
  for new risk. A feature is removed (with a new feature set version) only when removing it lowers neither AUC by
  0.005 or more. The absence rate is kept whatever the result.
- **Predictions**: nightly, for Active students, from the latest finished term. The level uses the model's own
  thresholds (*Smart School Settings → Early-Warning Model Levels*: Medium from 30%, High from 60%). The reasons
  shown are the features that raise the risk most, and only when the value itself points to risk: a low average or
  a high absence rate.
- **Retraining**: weekly, and on demand with *Train Now* (System Manager).
- **Who sees what**: the Early Warning report shows every class to the Headmaster and only their own class to a class
  teacher, in two groups: *Wanaoanza kushuka* (not at risk in term *t*, model Medium or High) and *Walio tayari
  hatarini*. It shows the probability, level, reasons and the rule-based score beside them. Model Performance is
  for the Headmaster and System Manager. Parents see nothing of the model.

### Interventions and their outcomes

Code: `smart_school/interventions.py`, `smart_school/intervention_outcomes.py`; doctype **Student Intervention**;
report **Intervention Outcomes**; number card **Follow-ups Due** (Headmaster and Academics workspaces).

- **Recording**: from the Early Warning report ("Weka hatua" on a student's row) or by hand: type (Counseling,
  Parent Meeting, Extra Classes, Teacher Follow-up, Referral, Other), responsible staff member, start and follow-up
  dates, status (Planned, In Progress, Completed, Cancelled), outcome and whether the parent was informed. The
  Early Warning of that moment (probability, level, rule score, group, reasons) is copied into the intervention and
  cannot be changed. The report's *Hatua* column shows each student's interventions for the term.
- **Who sees what**: the Headmaster and System Manager see all; a class teacher creates them for their own class,
  reads them and edits the ones they created; the responsible person reads and updates theirs; other teachers,
  accountants and parents see nothing (the parent portal shows no intervention).
- **Follow-up**: on the follow-up date the responsible person gets a ToDo (with its notification), once per date.
- **Outcomes**: the term of the intervention (T) is compared with the term before (t), whose results gave the risk.
  Students with an intervention are compared with students of the same term and the same decile of risk (the Active
  model's probability from term t, recomputed for everybody; the rule-based score without a model) who had no
  intervention at all in T. Measures: at risk in T (percentage points) and change in average from t to T. The
  difference is taken within each stratum (term x decile) and averaged with the treated counts as weights;
  95% intervals from 1,000 bootstrap resamples of students. Two estimates:
  - *per-protocol*: completed interventions only;
  - *intention-to-treat*: every intervention of a finished term, completed or not (usually smaller).
  The report also shows the raw difference (no matching), a balance table (term t average and absence before and
  after matching) and, per type, estimates when at least *Minimum Students per Type* (Smart School Settings,
  default 20) are matched, with a warning that many comparisons show differences by chance. A notice at the top
  says what it is: an observational comparison, not proof of cause (selection bias, regression to the mean).

### Demo results

The demo school is made by `smart_school/demo_data.py`:
`bench --site demo.localhost execute smart_school.demo_data.generate --kwargs "{'seed': 42}"`. It refuses to run on
jonbale, on sites not named `demo.*`, on sites with data or pending patches, and on sites that can send email or
SMS. It follows the school's exam structure: one main exam per term, out of 100 (Term 1 *Midterm*, Term 2
*Terminal*, Term 3 *Annual*), plus external exams that join a term with weights: a *District Exam* for Form 2 in
Term 1 (Midterm 60%, District 40%) and the Form 4 *Mock* in Term 2 (Terminal 70%, Mock 30%). In the generator,
absence and difficult terms lower results in the same and the next term, students who sat an exam never score
exactly 0, and gender has no effect. The school calendar is filled in as a Headmaster would: the moving holidays
(Easter, Eid, Maulid), a week's midterm break in every term, parents' meetings, sports day and Form 4 graduation,
exam dates (a week of papers for the main exam), and an upcoming Form 4 parents' meeting with an SMS reminder.
Attendance is recorded on school days only.

Interventions in the demo are chosen with a deliberate selection bias: from the second year on, at the start of a
term, the school acts for some students who looked at risk in the term before (an average below 35 or a high
model-like risk), and the higher the risk, the likelier. About 80% of those in finished terms are Completed, the
rest Cancelled; the current term's are Planned or In Progress. **The effect is planted**: a Completed intervention
adds 4 points to every mark of its term (added after the few-marks floor, so the weakest students get all of it),
and nothing else changes. The demo's manifest records it (`interventions`: planted effect, expected per-protocol 4
and intention-to-treat 4 x the completed share, and the effect that really reached the term averages). This only
checks that the Intervention Outcomes report can find a known effect through the bias; it says nothing about
whether interventions help real students.

The run of 2026-09-30 (seed 42) made 449 students (281 active) over 2024–2026, 42 exams (37 published, each with its
dates), 23,715 exam results, 150,595 attendance days (school days only), 603 discipline records, 4,462 fee payments,
316 interventions and 37 school calendar events besides the 11 fixed holidays.

**Calendar**: school days per term 54–56 (Term 1), 65 (Term 2) and 66 (Term 3); holidays and the midterm break take
6–8 weekdays out of each term. The school takes attendance on every school day, so completeness is 100% in every
class (the Attendance Completeness card shows 100%) and Early Warning shows no completeness note.

**Marks alerts**: 33 alerts (25, and 8 *Possibly Swapped Marks* since that check was added); every planted problem
was found except the swapped marks:

| Planted | Found |
|---|---|
| Identical marks, round numbers, low spread, many zeros, unusual class average | yes (each) |
| Dropped to zero (2 students) | 2 of 2 |
| Marks typed against the wrong names (2 pairs swapped, Form 2 Mathematics, Term 2 2026) | **0 of 4** |
| Entered by an unassigned teacher; changed after publishing (teacher and Headmaster); results unpublished | yes (each) |

The swapped marks were missed again: the four students' robust z were 3.4, 3.3, −2.6 and −4.2, under 4.5 for the
general check and, for the two who went up, just under 3.5 for the pair check (MAD 10 points in Mathematics, 7–9 in
the other subjects); the 30 schools above show this happens in about 1 school in 10. The pair check raised 8
alerts over three years in other classes (none in Term 2 or 3 2026). Not planted: 12 *Unusual Student Change* alerts over three years (1 in 2026) and one *Unusual Class
Average* (Form 1 Kiswahili, Annual 2025: 44.2% against a median of 54.3% over 5 earlier exams); no *Dropped To Zero*.
One *Changed After Publish* (Physics) follows from the mark corrected while the Form 2 Terminal exam was unpublished.

**Model** (RM-00001 on the demo site, feature set 5: term average and absence rate on school days; trained on target
terms Term 2 2024 to Term 3 2025, 1,294 student-terms, 419 at risk; tested on Term 1 and Term 2 2026, 460
student-terms, 148 at risk, base rate 32.2%):

| Measure | Model | Rule-based | Difference (95% CI) |
|---|---|---|---|
| AUC | 0.904 | 0.858 | +0.047 (+0.025 to +0.070) |
| Precision @ top 10% | 97.9% | 87.2% | |
| Recall @ top 10% | 31.1% | 27.7% | |
| Brier score | 0.116 | | |
| New risk: AUC (312 students, 43 fell) | 0.852 (0.788–0.906) | 0.728 (0.648–0.808) | +0.061 to +0.188 |
| New risk: precision @ top 10% | 50.0% (31.3–65.6) | 34.4% (15.2–53.1) | −3.1 to +31.3 points |
| New risk: recall @ top 10% | 37.2% (16 of 43) | 25.6% (11 of 43) | |

Calibration (predicted against observed, by decile of predicted risk, 46 students each):

| Decile | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 |
|---|---|---|---|---|---|---|---|---|---|---|
| Predicted | 1% | 3% | 6% | 11% | 19% | 31% | 44% | 61% | 79% | 95% |
| Observed | 0% | 0% | 4% | 7% | 17% | 33% | 33% | 61% | 72% | 96% |

Fairness at the top-10% cut (no warning: both gaps are under 10 points):

| | Students | At risk | Listed | Precision | Recall |
|---|---|---|---|---|---|
| Female, model | 239 | 76 | 27 | 100% | 36% |
| Male, model | 221 | 72 | 20 | 95% | 26% |
| Female, rule-based | 239 | 76 | 28 | 86% | 32% |
| Male, rule-based | 221 | 72 | 19 | 89% | 24% |

**Early Warning** (Term 3 2026, from Term 2 2026): 114 students, 89 already at risk (69 High, 20 Medium) and 25
emerging (23 Medium, 2 High); 57 of them have an intervention. Predictions for the 271 active students with results:
High 71, Medium 43, Low 157.

Ablation (change in test AUC when a feature is removed; negative means the feature helps). The rows for feature sets
1–3 were measured on the earlier demo data, which had two exams in every term:

| Feature set | Removed | Overall | New risk | Decision |
|---|---|---|---|---|
| v1 | discipline points | 0.0000 | (not measured yet) | removed in v2 |
| v2 | subjects with F | +0.002 | +0.004 | removed in v3 |
| v2 | no previous term | −0.001 | −0.002 | removed in v3 |
| v3 | change in average | −0.002 | −0.004 | removed in v4 by decision (AUC 0.897 → 0.896, new risk 0.746 → 0.743) |
| v5 | term average | −0.180 | −0.153 | kept |
| v5 | absence rate | −0.002 | −0.012 | kept (always kept, by decision) |

**Interventions** (the effect is planted, see above): 316 interventions, 259 in finished terms (205 Completed,
54 Cancelled: completed share 0.792) and 57 In Progress in Term 3 2026; 37 have reached their follow-up date and
their responsible teachers have a ToDo. The manifest says what to expect: per-protocol 4 (3.93 reached the term
averages), intention-to-treat 4 x 0.792 = 3.17 (3.13 reached them). Intervention Outcomes on the demo site (risk
by RM-00001; terms T from Term 1 2025 to Term 2 2026):

| | With intervention | Matched comparison | Difference (95% CI) | Raw difference |
|---|---|---|---|---|
| Per-protocol: change in average (points) | +3.6 (200) | −1.0 (275) | **+4.6 (+2.3 to +7.0)** | +5.7 |
| Per-protocol: at risk in T | 66.5% | 79.9% | −13.4 points (−21.8 to −5.1) | +42.3 points |
| Intention-to-treat: change in average (points) | +3.2 (251) | −1.0 (293) | **+4.2 (+2.2 to +6.3)** | +5.2 |
| Intention-to-treat: at risk in T | 68.1% | 80.4% | −12.2 points (−19.6 to −4.7) | +43.9 points |

Balance (per-protocol): term t average 29.7 for treated students against 51.5 for the comparison before matching
and 29.8 after; absence 15.9% against 6.7% before and 14.5% after. No treated student was left out.

Both intervals contain what reached the averages (3.93 and 3.13). The raw differences are too large (regression to
the mean), and the raw at-risk difference points the wrong way (+42 points: the school chose students already at
risk); matching turns it into −13 points. By type (per-protocol): Counseling +4.2, Extra Classes +4.2, Parent
Meeting +4.1, Teacher Follow-up +5.4 points, each with an interval 7–9 points wide; Other (13) and Referral (5) are
under the minimum of 20. Every type got the same planted +4, so their differences (and the at-risk differences,
from −4 to −24 points) are chance: what the report's warning about many comparisons is for.

**Checking the method on 30 schools.** The same generator and the same estimator (`intervention_outcomes.analyse`)
were run outside a site on 30 generated schools (seeds 1–29 and 42). There the risk deciles come from a fixed
model-like score of term t's average and absence instead of a trained model, and grades and divisions are
recomputed the way the app does. The planted effect that reached the term averages was measured in each school
by comparing every mark with the mark the student would have had without the intervention.

| Change in average from t to T (points) | Per-protocol | Intention-to-treat |
|---|---|---|
| Planted effect that reached the averages (mean of 30) | +3.94 | +3.16 |
| Matched estimate: mean of 30 (SD) | +3.92 (1.05) | +3.21 (1.00) |
| Matched estimate: lowest to highest | +1.64 (seed 28) to +5.27 (seed 21) | +1.21 (seed 28) to +5.19 (seed 17) |
| 95% interval contains the effect that reached the averages | 30 of 30 | 30 of 30 |
| Width of the 95% interval (mean) | 4.9 | 4.6 |
| Raw difference, no matching: mean (range) | +6.5 (+5.0 to +8.1) | +5.8 (+4.2 to +7.0) |
| At risk in T, matched: mean (range) | −10.5 (−19.5 to −5.5) points | −8.4 (−15.2 to −4.0) points |
| At risk in T, raw: mean (range) | +41.4 (+29.8 to +51.5) points | +43.7 (+36.5 to +49.8) points |

Balance, per-protocol, mean of 30: term t average 29.0 for treated students against 52.0 for all comparison
students before matching and 29.6 after; absence 16.3% against 7.3% before and 15.4% after.

What this shows:
- **Matching removes the bias here.** On average the matched estimates land on the planted effect (3.92 against
  3.94, 3.21 against 3.16). The raw differences are too large in every school (regression to the mean), and the
  raw at-risk difference points the wrong way. In the generator the school chooses only on what the risk score
  sees; in a real school it also sees things the score does not, and matching cannot remove those.
- **One school is one draw.** The estimate moves from school to school by about 1 point (SD) around the truth, so
  a single school can be 2–3 points off. A 95% interval is built to miss the true value in about 1 school in 20.
  This time none of the 30 missed; with the generator before the school calendar (other random draws) 2 of 30 did,
  and one of them was the demo school (+1.0, interval −1.5 to +3.1). The demo is reported as it comes out each
  time, without choosing the seed or the size of the data.

**SMS** (Test mode: nothing is sent): 344 of 410 guardians agreed on the admission form (85%), and 3 of their numbers
were typed with a digit missing. The results of the 4 exams published in Term 2 2026 (Form 1, 3 and 4 Terminal,
Form 4 Mock) and the receipts of the last 14 days' 37 payments gave 301 messages:

| | Test (recorded, not sent) | Skipped (no consent) | Failed (wrong number) |
|---|---|---|---|
| Results Published | 235 | 27 | 2 |
| Payment Received | 29 | 8 | 0 |

Every message fits in one SMS (103 characters on average, 123 at most), so 264 SMS would have cost TZS 6,600. A
results message reads: *Mwanga SS: Abdallah Paulo Haule - Mock: wastani 56.6%, Division I. Zaidi:
&lt;host_name&gt;/matokeo* (the division shows because every exam of that term is published). The link uses the site's
`host_name`: set it to the address parents use. The Form 4 parents' meeting of 16 October 2026 has an SMS reminder 3
days before; the daily job writes it on 13 October.

**Leave requests** (`demo_data.add_leave_demo`, own random numbers): 12 requests from parents with a portal account.
Nine are for days the child was away: a run of 2–3 school days in a row recorded Absent in the last six weeks (32
children had one). The class teachers decided them through the app: 6 approved (12 Absent days became Excused), 2
rejected (their days stay Absent), 1 withdrawn by the parent. Three more wait for days ahead, and their class
teachers have a ToDo. The 8 decisions gave 8 SMS in Test mode.

### Limitations

- **Synthetic data.** The links between absence, results and next term were written into the generator, so the
  model partly rediscovers them. The results say that the method works, not that it will work as well in a real
  school; it must be measured again on real data before anyone relies on it.
- **Small new-risk sample.** Only 43 students who were not at risk became at risk in the test terms. The model's
  new-risk AUC is better (interval +0.061 to +0.188), but the precision difference runs from −3 to +31 points, so
  it is not shown to flag them more precisely than the rule-based score.
- **Calibration in the middle.** The probabilities are close at both ends and in deciles 5, 6 and 8; decile 7 says
  44% where 33% happened, and deciles 2–4 are a little high. Each decile has only 46 students, and the level
  thresholds (30% and 60%) fall in that region.
- **Fairness on small groups.** At the top-10% cut 27 girls and 20 boys are listed; the gaps (recall 9 points for
  the model, 8 for the rule-based score) stay under the 10-point warning, and the generator gives gender no effect.
  The previous run, with other random draws, crossed it; the check must be repeated on real data.
- **Top-10% precision** is high for both (98% and 87%) because the students ranked first are the obvious cases;
  the new-risk measures are the harder test.
- **Intervention outcomes are one draw.** In a school of this size the estimate moves by about 1 point from school
  to school around the truth, and 1 interval in 20 is expected to miss it (the demo school did in the run before
  the school calendar). In a real school, add selection on things the risk score does not see, which no matching
  removes: the report is a reason to look closer, not a verdict on a type of intervention.
- **Attendance completeness in the demo** is 100%: the generator records every school day, so the completeness
  note of Early Warning is shown only by the tests. A real school's first terms will show it.
- **External exams in the class-average check.** An external exam is compared only with earlier external exams of
  the same type in the same Form. A school usually sits one or two of a kind a year, so it takes several years
  before there are 4 to compare with; until then the class-average check is skipped for them (the other checks
  still run). The type is chosen from the **External Exam Type** list (District Exam, Regional Exam and Mock to
  start with; the Headmaster can add more, and spellings that differ only in case or spaces are refused), so the
  history of a kind is not split by typing.
- **Marks alerts** were tuned on synthetic data. The student-change check (z 4.5, left there by decision) finds
  about half of the swapped students; with the pair check about 4 in 5, for about 2 more alerts a year in a
  300-student school. The planted swaps are the easiest kind (the weakest and the strongest students); a swap
  between two students with similar marks cannot be seen by any statistics, and does little harm.

## Demo accounts (site `jonbale`)

Passwords are set by the system owner and are not stored here.

| Role | User | Notes |
|---|---|---|
| System Manager | Administrator | |
| Headmaster | jacksonandrea2002+hm@gmail.com | Demo Headmaster |
| Accountant | jacksonandrea2002+acc@gmail.com | Demo Accountant |
| Teacher | jacksonandrea2002+mwalimu1@gmail.com | Inncoent Rungu |
| Teacher | alotaconstand+mwalimu2@gmail.com | Wayne Rooney (Form 1) |
| Teacher | balejunior0502+mwalimu3@gmail.com | Pretta Emmanuel |
| Teacher | jacksonandrea2002+mwalimu4@gmail.com | Bageni Mtaka (Form 2) |
| Teacher | alotaconstand+mwalimu5@gmail.com | Fransis Matata |
| Teacher | balejunior0502+mwalimu6@gmail.com | Xavier Thomas |
| Teacher | jacksonandrea2002+mwalimu7@gmail.com | Maria Db |
| Teacher | alotaconstand+mwalimu8@gmail.com | Luka Modric |
| Teacher | balejunior0502+mwalimu9@gmail.com | Ibrahim Ibrahim |
| Parent | raymondgoesberty2023@gmail.com | Jenifer Robert, four children |
| Parent | balejunior0502+mzazi1@gmail.com | Noel Bale Junior, two children |

## License

MIT
