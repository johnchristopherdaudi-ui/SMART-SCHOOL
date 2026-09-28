// Copyright (c) 2026, john daudi and contributors
// For license information, please see license.txt

frappe.query_reports["Early Warning"] = {
	filters: [
		{ fieldname: "class", label: __("Class"), fieldtype: "Link", options: "Class" },
		{
			fieldname: "section",
			label: __("Group"),
			fieldtype: "Select",
			options: "\nWanaoanza kushuka\nWalio tayari hatarini",
		},
		{ fieldname: "level", label: __("Level"), fieldtype: "Select", options: "\nHigh\nMedium\nLow" },
	],
	formatter(value, row, column, data, default_formatter) {
		if (column.fieldname === "add_intervention" && data && data.student && data.term) {
			const esc = frappe.utils.escape_html;
			return `<button class="btn btn-xs btn-default ew-add-intervention"
				data-student="${esc(data.student)}" data-student-name="${esc(data.student_name || "")}"
				data-term="${esc(data.term)}">${__("Weka hatua")}</button>`;
		}
		value = default_formatter(value, row, column, data);
		if (column.fieldname === "level" && data && data.level) {
			const color = { High: "red", Medium: "orange", Low: "green" }[data.level];
			value = `<span style="color: var(--${color}-600)">${value}</span>`;
		}
		return value;
	},
	onload(report) {
		$(document)
			.off("click.ew", ".ew-add-intervention")
			.on("click.ew", ".ew-add-intervention", (e) => {
				const btn = $(e.currentTarget);
				add_intervention(report, btn.attr("data-student"), btn.attr("data-student-name"), btn.attr("data-term"));
			});
	},
};

function add_intervention(report, student, student_name, term) {
	const dialog = new frappe.ui.Dialog({
		title: __("Weka hatua: {0}", [student_name || student]),
		fields: [
			{
				fieldname: "intervention_type",
				label: __("Type"),
				fieldtype: "Select",
				reqd: 1,
				options: "Counseling\nParent Meeting\nExtra Classes\nTeacher Follow-up\nReferral\nOther",
			},
			{
				fieldname: "responsible",
				label: __("Responsible"),
				fieldtype: "Link",
				options: "User",
				reqd: 1,
				default: frappe.session.user,
				get_query: () => ({ query: "smart_school.interventions.staff_user_query" }),
			},
			{ fieldname: "start_date", label: __("Start Date"), fieldtype: "Date", default: frappe.datetime.get_today() },
			{
				fieldname: "follow_up_date",
				label: __("Follow-up Date"),
				fieldtype: "Date",
				reqd: 1,
				default: frappe.datetime.add_days(frappe.datetime.get_today(), 14),
			},
			{ fieldname: "description", label: __("Description"), fieldtype: "Small Text" },
		],
		primary_action_label: __("Save"),
		primary_action(values) {
			frappe
				.call("smart_school.interventions.create_from_early_warning", { student, term, ...values })
				.then(() => {
					dialog.hide();
					frappe.show_alert({ message: __("Intervention saved"), indicator: "green" });
					report.refresh();
				});
		},
	});
	dialog.show();
}
