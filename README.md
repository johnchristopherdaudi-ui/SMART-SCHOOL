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
- Public admission form at `/apply-online`; the Headmaster approves (certificate attached or verified), which
  creates the student and links or creates the guardian.

## Roles

| Role | Can do |
|---|---|
| System Manager | Everything, including Smart School Settings, grading tables and terms |
| Headmaster | Admissions, students, guardians, teachers, exams (publish), term results and comments, all reports, promotion |
| Teacher | Enter/import marks for assigned subjects, attendance, discipline, class teacher comments, academic reports for own classes |
| Accountant | Fee structures, fee payments (submit/cancel), fee reports |
| Parent | Parent portal only (Website User) |

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
| `test_marks_alerts` | Every marks check, saving and auto-resolving alerts, publishing with warnings, who sees alerts |
| `test_demo_data` | Generator guard (never jonbale), reproducible seed, realistic links, a small school saved through the app |
| `test_risk_model` | Features, labels, time split, bootstrap, decision, model file checks, ablation, predictions, data guard |
| `test_early_warning` | Early Warning groups, class teacher scope, Emerging Risk card, rule-based fallback, nothing for parents |
| `test_report_card_verification` | Random tokens, same token for an unchanged card, valid/changed/invalid pages, nothing extra shown, revoke, drafts, rate limit, QR in the PDF |
| `test_interventions` | Snapshot, who sees and edits, reminders and card, Hatua column, matching, per-protocol and intention-to-treat, minimum sample, report warning |
| `test_sms` | SMS parts (GSM-7 / UCS-2), placeholders, one SMS with long names, modes, consent (admission, portal, paper), numbers, quiet hours, limits, retries, expiry, once per exam, fee reminders and students who left, no sensitive SMS, who sees the outbox and report |

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

Class checks need at least 10 students; Dropped To Zero applies to any class size.

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
- **Features** (feature set version 4, from term *t* only): the term average and the absence rate (Absent counts 1,
  Late ½, Excused 0). Gender is never a feature; it is used only to compare fairness. Earlier versions also had
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
exactly 0, and gender has no effect.

Interventions in the demo are chosen with a deliberate selection bias: from the second year on, at the start of a
term, the school acts for some students who looked at risk in the term before (an average below 35 or a high
model-like risk), and the higher the risk, the likelier. About 80% of those in finished terms are Completed, the
rest Cancelled; the current term's are Planned or In Progress. **The effect is planted**: a Completed intervention
adds 4 points to every mark of its term (added after the few-marks floor, so the weakest students get all of it),
and nothing else changes. The demo's manifest records it (`interventions`: planted effect, expected per-protocol 4
and intention-to-treat 4 x the completed share, and the effect that really reached the term averages). This only
checks that the Intervention Outcomes report can find a known effect through the bias; it says nothing about
whether interventions help real students.

The run of 2026-09-28 (seed 42) made 449 students (280 active) over 2024–2026, 42 exams (37 published), 23,643 exam
results, 167,271 attendance days, 662 discipline records, 4,396 fee payments and 265 interventions.

**Marks alerts**: 26 alerts; every planted problem was found except the swapped marks:

| Planted | Found |
|---|---|
| Identical marks, round numbers, low spread, many zeros, unusual class average | yes (each) |
| Dropped to zero (2 students) | 2 of 2 |
| Marks typed against the wrong names (2 pairs swapped, Form 2 Mathematics, Term 2 2026) | **0 of 4** |
| Entered by an unassigned teacher; changed after publishing (teacher and Headmaster); results unpublished | yes (each) |

The swapped marks were missed because that class's changes in Mathematics varied unusually widely this time (MAD 13
points, against 8–11 in the other subjects of the exam, Biology with its planted zeros aside): the four students'
robust z were 3.0 to 3.6, under the
threshold of 4.5. The previous run (other random marks) found all 4. Not planted: 13 *Unusual Student Change*
alerts over three years (6 in 2026); no *Dropped To Zero* and no *Unusual Class Average*. One *Many Identical Marks*
(Civics, Form 1, Term 3 2024) follows from the planted low spread (marks of 59–61), and one *Changed After
Publish* (Physics) from the mark corrected while the Form 2 Terminal exam was unpublished. External exams are
compared only with earlier exams of the same type, fewer than 4 so far, so the class-average check skips them.

**Model** (RM-00001 on the demo site, feature set 4: term average and absence rate; trained on target terms Term 2
2024 to Term 3 2025, 1,287 student-terms, 404 at risk; tested on Term 1 and Term 2 2026, 450 student-terms, 126 at
risk, base rate 28.0%):

| Measure | Model | Rule-based | Difference (95% CI) |
|---|---|---|---|
| AUC | 0.890 | 0.836 | +0.054 (+0.031 to +0.080) |
| Precision @ top 10% | 89.1% | 87.0% | |
| Recall @ top 10% | 32.5% | 31.7% | |
| Brier score | 0.117 | | |
| New risk: AUC (322 students, 38 fell) | 0.796 (0.725–0.858) | 0.670 (0.582–0.752) | +0.063 to +0.190 |
| New risk: precision @ top 10% | 27.3% (12.5–44.1) | 18.2% (6.1–32.4) | −3.1 to +24.2 points |
| New risk: recall @ top 10% | 23.7% | 15.8% | |

Calibration (predicted against observed, by decile of predicted risk, 45 students each):

| Decile | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 |
|---|---|---|---|---|---|---|---|---|---|---|
| Predicted | 1% | 4% | 7% | 10% | 16% | 25% | 37% | 53% | 77% | 97% |
| Observed | 0% | 2% | 2% | 7% | 13% | 24% | 31% | 36% | 71% | 93% |

Fairness at the top-10% cut:

| | Students | At risk | Listed | Precision | Recall |
|---|---|---|---|---|---|
| Female, model | 212 | 50 | 15 | 87% | 26% |
| Male, model | 238 | 76 | 31 | 90% | 37% |
| Female, rule-based | 212 | 50 | 14 | 71% | 20% |
| Male, rule-based | 238 | 76 | 32 | 94% | 39% |

Ablation (change in test AUC when a feature is removed; negative means the feature helps). The rows for feature sets
1–3 were measured on the earlier demo data, which had two exams in every term:

| Feature set | Removed | Overall | New risk | Decision |
|---|---|---|---|---|
| v1 | discipline points | 0.0000 | (not measured yet) | removed in v2 |
| v2 | subjects with F | +0.002 | +0.004 | removed in v3 |
| v2 | no previous term | −0.001 | −0.002 | removed in v3 |
| v3 | change in average | −0.002 | −0.004 | removed in v4 by decision (AUC 0.897 → 0.896, new risk 0.746 → 0.743) |
| v4 | term average | −0.131 | −0.159 | kept |
| v4 | absence rate | −0.004 | −0.008 | kept |

**Interventions** (the effect is planted, see above): 265 interventions, 212 in finished terms (168 Completed,
44 Cancelled: completed share 0.792) and 53 In Progress in Term 3 2026; 29 of those have reached their follow-up
date, and their responsible teachers have a ToDo (*Follow-ups Due* shows 29). The manifest says what to expect:
per-protocol 4 (3.95 reached the term averages), intention-to-treat 4 x 0.792 = 3.17 (3.11 reached them).
Intervention Outcomes on the demo site (risk by RM-00001; terms T from Term 1 2025 to Term 2 2026):

| | With intervention | Matched comparison | Difference (95% CI) | Raw difference |
|---|---|---|---|---|
| Per-protocol: change in average (points) | +3.0 (159) | +2.1 (270) | **+1.0 (−1.5 to +3.1)** | +4.5 |
| Per-protocol: at risk in T | 66.7% | 68.1% | −1.4 points (−9.3 to +6.9) | +44.0 points |
| Intention-to-treat: change in average (points) | +2.8 (202) | +2.0 (270) | **+0.9 (−1.1 to +3.1)** | +4.3 |
| Intention-to-treat: at risk in T | 67.8% | 68.9% | −1.0 points (−8.5 to +6.9) | +45.1 points |

Balance (per-protocol): term t average 28.7 for treated students against 50.7 for the comparison before matching
and 28.7 after; absence 16.7% against 7.0% before and 14.9% after. No treated student was left out for lack of a
comparison student in their stratum.

**Neither interval contains the planted effect** (4 and 3.2): the demo school is one of the 2 in 30 below. The
matching did its part (balance, and a raw difference of +44 points in at-risk shrinks to about −1), but in this
school the matched comparison students happened to improve almost as much (+2.1 against +3.0). By type (per-protocol):
Counseling −0.1, Extra Classes −0.7, Parent Meeting +2.2, Teacher Follow-up +0.3 points, each with an interval
about 7–9 points wide; Other (8) and Referral (3) are under the minimum of 20. Every type got the same planted +4,
so these differences are chance, which is what the report's warning about many comparisons is for.

**Checking the method on 30 schools.** The same generator and the same estimator (`intervention_outcomes.analyse`)
were run outside a site on 30 generated schools (seeds 1–29 and 42). There the risk deciles come from a fixed
model-like score of term t's average and absence instead of a trained model, and grades and divisions are
recomputed the way the app does. The planted effect that reached the term averages was measured in each school
by comparing every mark with the mark the student would have had without the intervention.

| Change in average from t to T (points) | Per-protocol | Intention-to-treat |
|---|---|---|
| Planted effect that reached the averages (mean of 30) | +3.94 | +3.13 |
| Matched estimate: mean of 30 (SD) | +3.82 (1.15) | +3.12 (1.08) |
| Matched estimate: lowest to highest | +0.99 (seed 42) to +6.60 (seed 26) | +0.90 (seed 42) to +6.14 (seed 26) |
| 95% interval contains the effect that reached the averages | 28 of 30 | 28 of 30 |
| Width of the 95% interval (mean) | 4.9 | 4.6 |
| Raw difference, no matching: mean (range) | +6.4 (+4.5 to +8.9) | +5.7 (+4.3 to +8.2) |
| At risk in T, matched: mean (range) | −10.3 (−19.8 to −1.8) points | −8.3 (−18.7 to −1.8) points |
| At risk in T, raw: mean (range) | +41.5 (+34.5 to +49.6) points | +43.4 (+34.0 to +48.8) points |

Balance, per-protocol, mean of 30: term t average 28.8 for treated students against 52.0 for all comparison
students before matching and 29.2 after; absence 16.3% against 7.4% before and 15.7% after.

What this shows:
- **Matching removes the bias here.** On average the matched estimates land on the planted effect (3.82 against
  3.94, 3.12 against 3.13). The raw differences are too large in every school, because treated students had a bad
  term t and bounce back anyway (regression to the mean), and the raw at-risk difference points the wrong way
  (about +40 points: the school chose students who were already at risk). In the generator the school chooses only
  on what the risk score sees; in a real school it also sees things the score does not, and matching cannot
  remove those.
- **Why one school can miss.** One school gives one estimate, and it moves from school to school by about 1.1
  points (SD) around the truth, depending on which students happen to be treated and which comparison students
  fall in each term and decile. With about 160 treated students and averages that move several points from term
  to term for reasons of their own, an interval about 5 points wide is as narrow as it gets. A 95% interval is
  built to miss the true value in about 1 school in 20; here it missed in 2 of 30, once low (seed 42) and once
  high (seed 26).
- **The demo is one of the misses.** Seed 42 is the demo school, and on the demo site, with the trained model, it
  gives nearly the same answer as here (+1.0 and +0.9). It is reported as it came out, without changing the seed
  or the size of the data: choosing a seed because it gives the planted answer would be choosing the result. Read
  the demo's interval as one draw; the 30 schools are the check of the method.

**SMS** (Test mode: nothing is sent; `demo_data.add_sms_demo`, run on this demo after it was made, with its own
random numbers so nothing above changed): 344 of 410 guardians agreed on the admission form (85%), and 3 of their
numbers were typed with a digit missing. The results of the 4 exams published in Term 2 2026 (Form 1, 3 and 4
Terminal, Form 4 Mock) and the receipts of the last 14 days' 49 payments gave 314 messages:

| | Test (recorded, not sent) | Skipped (no consent) | Failed (wrong number) |
|---|---|---|---|
| Results Published | 232 | 32 | 1 |
| Payment Received | 41 | 8 | 0 |

Every message fits in one SMS (111 characters on average, 121 at most), so 273 SMS would have cost TZS 6,825.
A results message reads: *Mwanga SS: Pendo John Kisanga - Terminal: wastani 53.3%, Division II. Zaidi:
http://demo.localhost:8000/matokeo* (the division shows because every exam of that term is published). The link
uses the site's address; set `host_name` to the address parents use.

### Limitations

- **Synthetic data.** The links between absence, results and next term were written into the generator, so the
  model partly rediscovers them. The results say that the method works, not that it will work as well in a real
  school; it must be measured again on real data before anyone relies on it.
- **Small new-risk sample.** Only 38 students who were not at risk became at risk in the test terms. The model's
  new-risk AUC is better (interval +0.063 to +0.190), but the precision difference runs from −3 to +24 points, so
  it is not shown to flag them more precisely than the rule-based score.
- **Calibration in the middle.** The probabilities are close at both ends but somewhat too high in between, most in
  deciles 7–8 (decile 8 says 53%, 36% happened; decile 7 says 37%, 31% happened); each decile has only 45
  students. The level thresholds (30% and 60%) fall in that region.
- **Fairness on small groups.** At the top-10% cut 15 girls and 31 boys are listed; the recall gap (11 points for
  the model, 19 for the rule-based score, whose precision gap is 22 points) raises the warning, although the
  generator gives gender no effect. It is most likely chance, but the check must be repeated on real data.
- **Top-10% precision** is high for both (89% and 87%) because the students ranked first are the obvious cases;
  the new-risk measures are the harder test.
- **Intervention outcomes are one draw.** In a school of this size the estimate moves by about 1.1 points from
  school to school around the truth, and 1 interval in 20 is expected to miss it; the demo school is such a miss
  (+1.0 per-protocol against a planted 4). In a real school, add selection on things the risk score does not see,
  which no matching removes: the report is a reason to look closer, not a verdict on a type of intervention.
- **External exams in the class-average check.** An external exam is compared only with earlier external exams of
  the same type in the same Form. A school usually sits one or two of a kind a year, so it takes several years
  before there are 4 to compare with; until then the class-average check is skipped for them (the other checks
  still run). The type is chosen from the **External Exam Type** list (District Exam, Regional Exam and Mock to
  start with; the Headmaster can add more, and spellings that differ only in case or spaces are refused), so the
  history of a kind is not split by typing.
- **Marks alerts** were tuned on synthetic data. The student-change check raised 13 alerts over three years of a
  300-student school, and at z 4.5 it misses swapped marks in a class whose marks vary a lot: in this run it missed
  all 4 swapped marks (z 3.0 to 3.6). A lower threshold would catch them at the cost of more alerts on genuine
  changes; the threshold is a setting (*Student Change: z Above*) left at 4.5.

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
