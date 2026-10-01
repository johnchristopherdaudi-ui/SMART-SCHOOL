// Copyright (c) 2026, john daudi and contributors
// For license information, please see license.txt

frappe.ui.form.on("Leave Request", {
	refresh(frm) {
		if (frm.doc.status === "Pending" && frm.perm[0] && frm.perm[0].write) {
			frm.add_custom_button(__("Approve"), () => decide(frm, "Approved")).addClass("btn-primary");
			frm.add_custom_button(__("Reject"), () => decide(frm, "Rejected"));
		}
		const manager = frappe.user.has_role("Headmaster") || frappe.user.has_role("System Manager");
		if (frm.doc.status === "Approved" && manager) {
			frm.add_custom_button(__("Withdraw"), () => decide(frm, "Withdraw"));
		}
	},
});

// A short note for the parent (in Swahili: they read it on the portal)
function decide(frm, decision) {
	const labels = { Approved: __("Approve"), Rejected: __("Reject"), Withdraw: __("Withdraw") };
	const dialog = new frappe.ui.Dialog({
		title: `${labels[decision]}: ${frm.doc.student_name}`,
		fields: [
			{
				fieldname: "note",
				fieldtype: "Small Text",
				label: __("Note to the parent (Swahili)"),
				description:
					decision === "Approved"
						? __("School days of the leave already recorded Absent become Excused; Present and Late stay.")
						: decision === "Withdraw"
						? __("Only the days this leave excused go back to Absent.")
						: "",
			},
		],
		primary_action_label: labels[decision],
		primary_action(values) {
			const method = decision === "Withdraw" ? "withdraw" : "decide";
			const args = decision === "Withdraw" ? { name: frm.doc.name, note: values.note } : { name: frm.doc.name, decision, note: values.note };
			frappe.call({ method: `smart_school.leave.${method}`, args, freeze: true }).then(() => {
				dialog.hide();
				frm.reload_doc();
			});
		},
	});
	dialog.show();
}
