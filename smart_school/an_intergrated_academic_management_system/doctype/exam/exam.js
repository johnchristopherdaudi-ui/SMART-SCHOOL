// Copyright (c) 2026, john daudi and contributors
// For license information, please see license.txt

frappe.ui.form.on("Exam", {
	refresh(frm) {
		if (frm.is_new() || !(frappe.user.has_role("Headmaster") || frappe.user.has_role("System Manager"))) {
			return;
		}

		const call = (method, message, args = {}) => {
			frappe.call({
				method: `smart_school.results.${method}`,
				args: { exam: frm.doc.name, ...args },
				freeze: true,
				callback: () => {
					frappe.show_alert({ message: __(message), indicator: "green" });
					frm.reload_doc();
				},
			});
		};

		if (frm.doc.results_published) {
			frm.add_custom_button(__("Unpublish Results"), () => {
				frappe.confirm(
					__("Hide these results from parents? This is noted on the exam and raises a marks alert."),
					() => call("unpublish_exam_results", "Results unpublished")
				);
			});
		} else {
			const publish = (send_sms) =>
				call("publish_exam_results", "Results published; parents are being notified", { send_sms: send_sms ? 1 : 0 });
			frm.add_custom_button(__("Publish Results"), () => check_marks_then_publish(frm, publish)).addClass(
				"btn-primary"
			);
		}

		frm.add_custom_button(__("Recompute Term Results"), () => call("recompute_term_results", "Term results recomputed"));
	},
});

// Marks alerts are a warning before publishing, never a block
function check_marks_then_publish(frm, publish) {
	const confirm_publish = () => confirm_with_sms(frm, publish);

	frappe.call({
		method: "smart_school.marks_alerts.check_exam",
		args: { exam: frm.doc.name },
		freeze: true,
		freeze_message: __("Checking marks..."),
		callback: (r) => {
			const alerts = r.message || [];
			alerts.length ? show_marks_alerts(frm, alerts, publish) : confirm_publish();
		},
		error: () => frappe.confirm(__("The marks check could not run. Publish these results anyway?"), confirm_publish),
	});
}

function show_marks_alerts(frm, alerts, publish) {
	const esc = frappe.utils.escape_html;
	const rows = alerts
		.map(
			(a) => `<tr>
				<td>${esc(__(a.severity))}</td>
				<td><a href="/app/marks-alert/${encodeURIComponent(a.name)}" target="_blank">${esc(__(a.alert_type))}</a></td>
				<td>${esc(a.message || "")}</td>
			</tr>`
		)
		.join("");
	const list_url = `/app/marks-alert?exam=${encodeURIComponent(frm.doc.name)}&status=Open`;

	const dialog = new frappe.ui.Dialog({
		title: __("{0} open marks alert(s)", [alerts.length]),
		size: "extra-large",
		fields: [
			{
				fieldtype: "HTML",
				options: `<p>${__("These marks may need a second look. You can still publish; the open alerts will be noted on the exam.")}
					<a href="${list_url}" target="_blank">${__("Review alerts")}</a></p>
					<table class="table table-bordered small">
						<thead><tr><th>${__("Severity")}</th><th>${__("Alert")}</th><th>${__("Details")}</th></tr></thead>
						<tbody>${rows}</tbody>
					</table>`,
			},
		],
		primary_action_label: __("Publish anyway"),
		primary_action() {
			dialog.hide();
			confirm_with_sms(frm, publish);
		},
		secondary_action_label: __("Cancel"),
		secondary_action() {
			dialog.hide();
		},
	});
	dialog.show();
}

// The last step before publishing: how many SMS the results take and what they cost
function confirm_with_sms(frm, publish) {
	const email_only = () => frappe.confirm(__("Publish these results to parents and notify them by email?"), () => publish(false));
	frappe.call({
		method: "smart_school.sms.preview_exam_results",
		args: { exam: frm.doc.name },
		freeze: true,
		callback: (r) => {
			const p = r.message;
			if (p.mode === "Off" || !p.template_enabled) {
				email_only();
				return;
			}
			const money = (v) => format_number(v, null, 0);
			const lines = [];
			if (p.mode === "Test") {
				lines.push(`<b>${__("Test mode")}</b>: ${__("messages are written to the SMS Outbox, not sent.")}`);
			}
			lines.push(
				__("{0} messages to guardians: {1} SMS, about TZS {2} (TZS {3} per SMS).", [p.messages, p.sms, money(p.cost), money(p.price)]),
				__("Not agreed to SMS: {0} · wrong or missing number: {1} · already sent before: {2}.", [p.skipped, p.failed, p.already]),
				__("Left today: {0} of {1} SMS; this month: {2} of {3}.", [p.remaining_today, p.daily_limit, p.remaining_month, p.monthly_limit])
			);
			if (p.sms > p.remaining_today && p.fits_month) {
				lines.push(__("More than is left today: the rest is sent on the following day(s)."));
			}
			if (!p.fits_month) {
				lines.push(`<span style="color: var(--red-600)">${__("Not enough SMS left this month: publish without SMS, or raise the monthly limit.")}</span>`);
			}
			lines.push(__("Messages written between 21:00 and 07:00 wait for the morning."));
			const dialog = new frappe.ui.Dialog({
				title: __("Publish results"),
				fields: [
					{ fieldtype: "HTML", options: lines.map((l) => `<p>${l}</p>`).join("") },
					{
						fieldname: "send_sms",
						fieldtype: "Check",
						label: __("Also send SMS to parents"),
						default: p.fits_month && p.messages ? 1 : 0,
						read_only: p.fits_month ? 0 : 1,
					},
				],
				primary_action_label: __("Publish"),
				primary_action(values) {
					dialog.hide();
					publish(values.send_sms && p.fits_month);
				},
			});
			dialog.show();
		},
		error: email_only,
	});
}
