// API secret on the User form (Settings > API Access): eye icon in the field to show / hide it.
// Frappe itself shows it only once, right after Generate Keys.
frappe.ui.form.on("User", {
	refresh(frm) {
		litwatch_show_api_secret(frm);
	},
	after_save(frm) {
		litwatch_show_api_secret(frm);
	},
});

function litwatch_show_api_secret(frm) {
	if (!frm.fields_dict.api_secret || frm.is_new() || !frm.doc.api_key) return;
	if (frappe.session.user !== frm.doc.name && !frappe.user.has_role("System Manager")) return;
	litwatch_secret_eye(frm, "api_secret", {
		method: "litwatch.api.api_keys.get_api_secret",
		args: { user: frm.doc.name },
		key: "api_secret",
	});
}

// Eye icon inside a Password field: click to show the saved value in the field itself, click again
// to hide it. The value is fetched from the server only when the eye is clicked; nothing is saved.
function litwatch_secret_eye(frm, fieldname, spec) {
	const field = frm.fields_dict[fieldname];
	if (!field) return;
	field.$wrapper.find(".ls-eye").remove();
	const $input = field.$wrapper.find("input").first();
	$input.attr("type", "password");
	if (frm.is_new()) return;
	const EYE = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>';
	const EYE_OFF = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94"/><path d="M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19"/><path d="M14.12 14.12a3 3 0 1 1-4.24-4.24"/><line x1="1" y1="1" x2="23" y2="23"/></svg>';
	const $wrap = field.$wrapper.find(".control-input-wrapper").first().css("position", "relative");
	const $static = field.$wrapper.find(".control-value").first();
	$input.css("padding-right", "34px");
	let secret = null;
	let shown = false;
	let static_html = null;
	const $btn = $(`<button type="button" class="ls-eye" title="${__("Show")}"
		style="position: absolute; right: 8px; top: 50%; transform: translateY(-50%); z-index: 3;
		background: transparent; border: none; padding: 2px; line-height: 0; color: var(--text-muted); cursor: pointer">${EYE}</button>`);
	$btn.on("click", async (e) => {
		e.preventDefault();
		const editable = $input.is(":visible");
		if (!shown) {
			if (secret === null) {
				const r = await frappe.call({ method: spec.method, args: spec.args });
				secret = (r.message && r.message[spec.key]) || "";
			}
			if (!secret) {
				frappe.show_alert({ message: __("No secret saved"), indicator: "orange" });
				return;
			}
			if (editable) {
				$input.attr("type", "text").val(secret);
			} else {
				static_html = $static.html();
				$static.text(secret);
			}
		} else if (editable) {
			$input.attr("type", "password").val(frm.doc[fieldname] || "");
		} else if (static_html !== null) {
			$static.html(static_html);
		}
		shown = !shown;
		$btn.html(shown ? EYE_OFF : EYE).attr("title", shown ? __("Hide") : __("Show"));
	});
	$wrap.append($btn);
}
