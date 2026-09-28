// Copyright (c) 2026, john daudi and contributors
// For license information, please see license.txt

frappe.ui.form.on("SMS Template", {
	refresh(frm) {
		show_length(frm);
	},
	template_type(frm) {
		show_length(frm);
	},
	message(frm) {
		clearTimeout(frm._sms_timer);
		frm._sms_timer = setTimeout(() => show_length(frm), 300);
	},
});

function show_length(frm) {
	if (!frm.doc.template_type) {
		return;
	}
	frappe.call({
		method: "smart_school.sms.preview_template",
		args: { message_type: frm.doc.template_type, message: frm.doc.message || "" },
		callback: (r) => {
			const p = r.message;
			const esc = frappe.utils.escape_html;
			const color = (segments) => (segments > 1 ? "var(--red-600)" : "var(--green-600)");
			const unknown = p.unknown.length
				? `<p style="color: var(--red-600)">${__("Unknown placeholders")}: ${esc(p.unknown.map((u) => `{${u}}`).join(", "))}</p>`
				: "";
			frm.get_field("preview_html").$wrapper.html(`
				<p>${__("As typed")}: <b>${p.characters}</b> ${__("characters")} ·
					<b style="color: ${color(p.segments)}">${p.segments} SMS</b> · ${esc(p.encoding)}</p>
				<p>${__("With long names")}: <b>${p.example_characters}</b> ${__("characters")} ·
					<b style="color: ${color(p.example_segments)}">${p.example_segments} SMS</b> · ${esc(p.example_encoding)}</p>
				<p class="text-muted small">${esc(p.example)}</p>${unknown}`);
			const rows = Object.entries(p.placeholders)
				.map(([k, v]) => `<tr><td><code>{${esc(k)}}</code></td><td>${esc(v)}</td></tr>`)
				.join("");
			frm.get_field("placeholders_html").$wrapper.html(
				`<table class="table table-bordered small"><tbody>${rows}</tbody></table>`
			);
		},
	});
}
