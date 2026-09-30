// Copyright (c) 2026, john daudi and contributors
// For license information, please see license.txt

// A whole class at once: everyone starts Present (or as recorded, or Excused on an approved leave); change the few
// who differ and save once. Made for a phone: one row per student, big buttons.
const STATUS_INFO = {
	Present: { key: "P", color: "green", tip: "Present" },
	Absent: { key: "A", color: "red", tip: "Absent: counts as a day missed" },
	Late: { key: "L", color: "orange", tip: "Late: counts as half a day missed" },
	Excused: { key: "E", color: "blue", tip: "Excused (e.g. an approved leave): not counted as missed" },
};

frappe.pages["class-attendance"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({ parent: wrapper, title: __("Class Attendance"), single_column: true });
	new ClassAttendance(page);
};

class ClassAttendance {
	constructor(page) {
		this.page = page;
		this.sheet = null;
		this.$body = $(`<div class="class-attendance"></div>`).appendTo(page.main);
		this.add_style();
		this.class_field = page.add_field({
			fieldname: "class_name",
			label: __("Class"),
			fieldtype: "Select",
			change: () => this.load(),
		});
		this.date_field = page.add_field({
			fieldname: "date",
			label: __("Date"),
			fieldtype: "Date",
			default: frappe.datetime.get_today(),
			change: () => this.load(),
		});
		page.set_primary_action(__("Save"), () => this.save(), "check");
		page.add_inner_button(__("All Present"), () => this.all_present());
		frappe.call("smart_school.class_attendance.get_classes").then((r) => {
			const classes = r.message || [];
			this.class_field.df.options = classes.join("\n");
			this.class_field.refresh();
			if (classes.length) this.class_field.set_value(classes[0]);
		});
	}

	load() {
		const class_name = this.class_field.get_value();
		const date = this.date_field.get_value();
		if (!class_name || !date) return;
		frappe
			.call({ method: "smart_school.class_attendance.get_sheet", args: { class_name, date }, freeze: true })
			.then((r) => {
				this.sheet = r.message;
				this.render();
			})
			.catch(() => {
				this.sheet = null;
				this.$body.empty();
			});
	}

	render() {
		const esc = frappe.utils.escape_html;
		const s = this.sheet;
		const warning = s.not_school_day
			? `<div class="ca-warning">${__("{0} is not a school day ({1}). Records saved for it are not counted.", [
					frappe.datetime.str_to_user(s.date),
					esc(s.not_school_day),
			  ])}</div>`
			: "";
		const rows = s.students
			.map(
				(st, i) => `<div class="ca-row" data-index="${i}">
					<div class="ca-name">${esc(st.student_name || st.student)}
						${st.source === "leave" ? `<span class="ca-tag">${__("Approved leave")}</span>` : ""}
						${st.source === "recorded" ? `<span class="ca-tag muted">${__("Recorded")}</span>` : ""}
					</div>
					<div class="ca-buttons">${Object.entries(STATUS_INFO)
						.map(
							([status, info]) =>
								`<button class="btn ca-btn ${st.status === status ? `active ${info.color}` : ""}"
									data-status="${status}" title="${esc(__(info.tip))}" aria-label="${esc(__(info.tip))}">${info.key}</button>`
						)
						.join("")}</div>
				</div>`
			)
			.join("");
		this.$body.html(`${warning}<div class="ca-summary"></div>
			<div class="ca-legend">${Object.values(STATUS_INFO)
				.map((info) => `<span title="${esc(__(info.tip))}"><b>${info.key}</b> ${esc(__(info.tip.split(":")[0]))}</span>`)
				.join(" · ")}</div>
			${rows || `<p class="text-muted">${__("No active students in this class.")}</p>`}`);
		this.$body.find(".ca-btn").on("click", (e) => {
			const $btn = $(e.currentTarget);
			const index = $btn.closest(".ca-row").data("index");
			this.sheet.students[index].status = $btn.data("status");
			this.render();
		});
		this.show_summary();
	}

	show_summary() {
		const counts = {};
		this.sheet.students.forEach((st) => (counts[st.status] = (counts[st.status] || 0) + 1));
		this.$body
			.find(".ca-summary")
			.text(Object.entries(STATUS_INFO).map(([status, info]) => `${info.key} ${counts[status] || 0}`).join(" · "));
	}

	all_present() {
		if (!this.sheet) return;
		this.sheet.students.forEach((st) => {
			if (st.source !== "leave") st.status = "Present";
		});
		this.render();
	}

	save() {
		if (!this.sheet) return;
		const send = () =>
			frappe
				.call({
					method: "smart_school.class_attendance.save_sheet",
					args: {
						class_name: this.sheet.class,
						date: this.sheet.date,
						entries: this.sheet.students.map((st) => ({ student: st.student, status: st.status })),
					},
					freeze: true,
				})
				.then((r) => {
					const m = r.message;
					frappe.show_alert({
						message: __("Saved: {0} new, {1} changed", [m.created, m.updated]),
						indicator: "green",
					});
					this.load();
				});
		if (this.sheet.not_school_day) {
			frappe.confirm(
				__("{0} is not a school day ({1}). Save anyway? These records will not count.", [
					frappe.datetime.str_to_user(this.sheet.date),
					frappe.utils.escape_html(this.sheet.not_school_day),
				]),
				send
			);
		} else {
			send();
		}
	}

	add_style() {
		$(`<style>
			.class-attendance { max-width: 720px; margin: 0 auto; }
			.ca-warning { background: var(--yellow-100); color: var(--yellow-800); padding: 10px 12px; border-radius: 8px; margin-bottom: 10px; }
			.ca-summary { font-weight: 600; margin: 6px 0; }
			.ca-legend { font-size: 12px; color: var(--text-muted); margin-bottom: 10px; }
			.ca-row { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 8px;
				padding: 10px 4px; border-bottom: 1px solid var(--border-color); }
			.ca-name { font-size: 15px; flex: 1 1 180px; }
			.ca-tag { display: inline-block; font-size: 11px; background: var(--blue-100); color: var(--blue-700); border-radius: 10px; padding: 1px 8px; margin-left: 6px; }
			.ca-tag.muted { background: var(--gray-100); color: var(--gray-700); }
			.ca-buttons { display: flex; gap: 6px; }
			.ca-btn { min-width: 44px; min-height: 40px; font-weight: 700; }
			.ca-btn.active.green { background: var(--green-500); color: #fff; }
			.ca-btn.active.red { background: var(--red-500); color: #fff; }
			.ca-btn.active.orange { background: var(--orange-500); color: #fff; }
			.ca-btn.active.blue { background: var(--blue-500); color: #fff; }
		</style>`).appendTo(this.$body.parent());
	}
}
