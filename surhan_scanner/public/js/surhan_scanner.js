frappe.provide("surhan_scanner");

surhan_scanner.manager = {
    config_cache: {},
    current_frm: null,
    current_settings: null,
    current_rule: null,
    agent_dialog: null,
    agent_devices: [],
    agent_health: null,
    active_scan: false,

    client_can_use_scanner: function () {
        const roles = window.frappe && frappe.user_roles ? frappe.user_roles : [];
        const allowed_roles = [
            "System Manager",
            "Surhan Scanner Admin",
            "Surhan Scanner Manager",
            "Surhan Scanner User"
        ];

        return allowed_roles.some((role) => roles.includes(role));
    },

    disabled_config: function () {
        return {
            enabled: 0,
            settings: {},
            rules: []
        };
    },

    load_config: function (frm, callback) {
        if (!frm || !frm.doctype) {
            return;
        }

        if (!this.client_can_use_scanner()) {
            const data = this.disabled_config();
            this.config_cache[frm.doctype] = data;

            if (callback) {
                callback(data);
            }
            return;
        }

        if (this.config_cache[frm.doctype]) {
            if (callback) {
                callback(this.config_cache[frm.doctype]);
            }
            return;
        }

        frappe.call({
            method: "surhan_scanner.api.get_scanner_config",
            freeze: false,
            args: {
                doctype: frm.doctype
            },
            callback: (r) => {
                const data = r.message || this.disabled_config();
                this.config_cache[frm.doctype] = data;

                if (callback) {
                    callback(data);
                }
            },
            error: () => {
                const data = this.disabled_config();
                this.config_cache[frm.doctype] = data;

                if (callback) {
                    callback(data);
                }
            }
        });
    },

    apply_to_form: function (frm) {
        if (!frm || frm.is_new()) {
            return;
        }

        if (!this.client_can_use_scanner()) {
            frm.__surhan_scanner_checked = true;
            return;
        }

        if (frm.__surhan_scanner_checked || frm.__surhan_scanner_loaded) {
            return;
        }

        frm.__surhan_scanner_checked = true;

        this.load_config(frm, (config) => {
            if (!config || !config.enabled || !config.rules || !config.rules.length) {
                return;
            }

            config.rules.forEach((rule) => {
                this.add_button(frm, config.settings || {}, rule || {});
            });

            frm.__surhan_scanner_loaded = true;
        });
    },

    add_button: function (frm, settings, rule) {
        const label = rule.button_label || settings.button_label || "اسكانر";
        const group = rule.button_group || settings.button_group || "مرفقات";

        if (rule.placement_type === "All Attach Fields") {
            this.add_buttons_to_all_attach_fields(frm, settings, rule, label);
            return;
        }

        if (rule.placement_type === "After Field" && rule.target_field) {
            this.add_button_after_field(frm, rule.target_field, label, () => {
                const field_rule = Object.assign({}, rule);

                if (!field_rule.attach_field) {
                    field_rule.attach_field = rule.target_field;
                }

                if (!field_rule.upload_mode || field_rule.upload_mode === "Attachment Only") {
                    field_rule.upload_mode = "Both";
                }

                this.open(frm, settings, field_rule);
            });
            return;
        }

        frm.add_custom_button(
            label,
            () => {
                this.open(frm, settings, rule);
            },
            group
        );
    },

    add_buttons_to_all_attach_fields: function (frm, settings, rule, label) {
        if (!frm || !frm.meta || !frm.meta.fields) {
            return;
        }

        let added = 0;

        frm.meta.fields.forEach((df) => {
            if (!df.fieldname) {
                return;
            }

            if (["Attach", "Attach Image"].includes(df.fieldtype)) {
                this.add_button_after_field(frm, df.fieldname, label, () => {
                    const field_rule = Object.assign({}, rule, {
                        attach_field: df.fieldname,
                        upload_mode: "Both"
                    });

                    this.open(frm, settings, field_rule);
                });

                added++;
                return;
            }

            if (df.fieldtype === "Table") {
                this.add_button_after_field(frm, df.fieldname, label, () => {
                    const field_rule = Object.assign({}, rule, {
                        attach_field: df.fieldname,
                        upload_mode: "Both"
                    });

                    this.open(frm, settings, field_rule);
                });

                added++;
            }
        });

        if (!added) {
            frm.add_custom_button(
                label,
                () => {
                    this.open(frm, settings, rule);
                },
                rule.button_group || "مرفقات"
            );
        }
    },

    add_button_after_field: function (frm, fieldname, label, handler) {
        const field = frm.fields_dict ? frm.fields_dict[fieldname] : null;

        if (!field || !field.$wrapper) {
            console.warn("Surhan Scanner target field not found:", fieldname);
            return;
        }

        const button_id = "surhan-scanner-btn-" + this.safe_id(fieldname);

        if (field.$wrapper.find("#" + button_id).length) {
            return;
        }

        const html =
            '<div class="surhan-scanner-inline-button" style="margin-top:8px;margin-bottom:6px;">' +
            '<button type="button" class="btn btn-sm btn-primary" id="' + button_id + '">' +
            this.escape_html(label) +
            "</button></div>";

        const target_area = field.$wrapper
            .find(".attached-file, .missing-image, .control-input, .form-group")
            .first();

        if (target_area.length) {
            target_area.append(html);
        } else {
            field.$wrapper.append(html);
        }

        field.$wrapper.find("#" + button_id).on("click", handler);
    },

    get_effective_engine: function (settings, rule) {
        settings = settings || {};
        rule = rule || {};

        const rule_engine = rule.scanner_engine || "Default";
        if (rule_engine && rule_engine !== "Default") {
            return rule_engine;
        }

        return settings.scanner_engine || "Surhan Agent";
    },

    open: function (frm, settings, rule) {
        if (!frm) {
            frappe.msgprint("لا يوجد مستند مفتوح");
            return;
        }

        if (frm.is_new()) {
            frappe.msgprint("يرجى حفظ المستند أولاً قبل استخدام الاسكانر");
            return;
        }

        settings = settings || {};
        rule = rule || {};

        const engine = this.get_effective_engine(settings, rule);
        if (engine === "Surhan Agent") {
            this.open_agent_dialog(frm, settings, rule);
            return;
        }

        frappe.msgprint(
            "هذا الإصدار مضبوط للعمل عبر Surhan Agent. يرجى جعل Scanner Engine = Surhan Agent."
        );
    },

    open_agent_dialog: function (frm, settings, rule) {
        this.current_frm = frm;
        this.current_settings = settings || {};
        this.current_rule = rule || {};
        this.agent_health = null;

        this.make_agent_dialog();
        this.set_agent_dialog_defaults();
        this.agent_dialog.show();

        setTimeout(() => {
            this.check_agent_and_load_devices();
        }, 300);
    },

    make_agent_dialog: function () {
        if (this.agent_dialog) {
            return;
        }

        this.agent_dialog = new frappe.ui.Dialog({
            title: "Surhan Scanner Professional",
            size: "extra-large",
            fields: [
                {
                    fieldtype: "HTML",
                    fieldname: "scanner_html"
                }
            ],
            primary_action_label: "بدء المسح والرفع",
            primary_action: () => {
                this.start_agent_scan_from_dialog();
            }
        });

        const html = `
            <style>
                .surhan-pro-wrapper {
                    direction: rtl;
                    font-family: inherit;
                }

                .surhan-pro-header {
                    display: flex;
                    justify-content: space-between;
                    align-items: center;
                    gap: 12px;
                    padding: 14px 16px;
                    border: 1px solid #e5e7eb;
                    border-radius: 10px;
                    background: #f8fafc;
                    margin-bottom: 14px;
                }

                .surhan-pro-title {
                    font-size: 18px;
                    font-weight: 700;
                    margin-bottom: 4px;
                    color: #0f172a;
                }

                .surhan-pro-subtitle {
                    color: #64748b;
                    font-size: 13px;
                    line-height: 1.7;
                }

                .surhan-pro-badge {
                    padding: 6px 10px;
                    border-radius: 999px;
                    background: #e0f2fe;
                    color: #075985;
                    font-size: 12px;
                    font-weight: 600;
                    white-space: nowrap;
                }

                .surhan-pro-grid {
                    display: grid;
                    grid-template-columns: repeat(3, minmax(0, 1fr));
                    gap: 12px;
                }

                .surhan-pro-card {
                    border: 1px solid #e5e7eb;
                    border-radius: 8px;
                    background: #ffffff;
                    padding: 14px;
                    min-height: 100px;
                }

                .surhan-pro-card h4 {
                    margin: 0 0 12px 0;
                    font-size: 14px;
                    font-weight: 700;
                    color: #0f172a;
                }

                .surhan-pro-field {
                    margin-bottom: 10px;
                }

                .surhan-pro-field label {
                    display: block;
                    font-weight: 600;
                    font-size: 12px;
                    color: #475569;
                    margin-bottom: 5px;
                }

                .surhan-pro-field select,
                .surhan-pro-field input {
                    width: 100%;
                    min-height: 34px;
                    border: 1px solid #d1d5db;
                    border-radius: 6px;
                    padding: 6px 8px;
                    background: #ffffff;
                }

                .surhan-pro-field select:disabled,
                .surhan-pro-field input:disabled {
                    background: #f1f5f9;
                    color: #94a3b8;
                    cursor: not-allowed;
                }

                .surhan-pro-check {
                    display: flex;
                    align-items: center;
                    gap: 7px;
                    margin-bottom: 8px;
                    color: #334155;
                    font-size: 13px;
                }

                .surhan-pro-check input {
                    margin: 0;
                }

                .surhan-pro-actions {
                    display: flex;
                    flex-wrap: wrap;
                    gap: 8px;
                    margin-top: 12px;
                }

                .surhan-pro-status {
                    margin-top: 14px;
                    padding: 12px 14px;
                    border-radius: 8px;
                    border: 1px solid #e5e7eb;
                    background: #f8fafc;
                    color: #334155;
                    min-height: 45px;
                    line-height: 1.7;
                }

                .surhan-pro-status.success {
                    background: #ecfdf5;
                    border-color: #bbf7d0;
                    color: #166534;
                }

                .surhan-pro-status.warning {
                    background: #fffbeb;
                    border-color: #fde68a;
                    color: #92400e;
                }

                .surhan-pro-status.error {
                    background: #fef2f2;
                    border-color: #fecaca;
                    color: #991b1b;
                }

                .surhan-pro-progress {
                    margin-top: 12px;
                    height: 10px;
                    border-radius: 999px;
                    overflow: hidden;
                    background: #e5e7eb;
                }

                .surhan-pro-progress-bar {
                    height: 100%;
                    width: 0%;
                    background: #2563eb;
                    transition: width 0.25s ease;
                }

                .surhan-pro-preview {
                    margin-top: 12px;
                    padding: 10px;
                    border: 1px dashed #cbd5e1;
                    border-radius: 8px;
                    background: #f8fafc;
                    color: #64748b;
                    min-height: 60px;
                    line-height: 1.7;
                }

                .surhan-pro-warning-box,
                .surhan-pro-success-box {
                    padding: 10px 12px;
                    border-radius: 8px;
                    line-height: 1.7;
                }

                .surhan-pro-warning-box {
                    background: #fff7ed;
                    border: 1px solid #fed7aa;
                    color: #9a3412;
                }

                .surhan-pro-success-box {
                    background: #ecfdf5;
                    border: 1px solid #bbf7d0;
                    color: #166534;
                }


                .surhan-scanner-agent-dialog .modal-dialog {
                    width: calc(100vw - 70px);
                    max-width: 1500px;
                }

                .surhan-scanner-agent-dialog .modal-content {
                    min-height: calc(100vh - 70px);
                }

                .surhan-scanner-agent-dialog .modal-body {
                    max-height: calc(100vh - 145px);
                    overflow: auto;
                }

                .surhan-pro-workspace {
                    display: grid;
                    grid-template-columns: minmax(760px, 1fr) minmax(320px, 420px);
                    gap: 14px;
                    align-items: start;
                    direction: ltr;
                }

                .surhan-pro-preview-column,
                .surhan-pro-device-column {
                    direction: rtl;
                }

                .surhan-pro-page-viewer {
                    min-height: 560px;
                    border: 1px dashed #d1d5db;
                    border-radius: 10px;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    padding: 12px;
                    background: #ffffff;
                    overflow: auto;
                    text-align: center;
                }

                .surhan-pro-page-viewer img,
                .surhan-pro-page-viewer iframe {
                    width: 100%;
                    max-width: 100%;
                    max-height: 560px;
                    border: 0;
                }

                .surhan-pro-page-nav {
                    display: flex;
                    gap: 8px;
                    align-items: center;
                    justify-content: center;
                    margin-top: 10px;
                }

                .surhan-pro-report {
                    margin-top: 10px;
                }

                .surhan-pro-hidden-setting {
                    display: none !important;
                }

                @media (max-width: 992px) {
                    .surhan-pro-workspace {
                        grid-template-columns: 1fr;
                    }
                }

                @media (max-width: 992px) {
                    .surhan-pro-grid {
                        grid-template-columns: 1fr;
                    }

                    .surhan-pro-header {
                        flex-direction: column;
                        align-items: flex-start;
                    }
                }
            </style>

            <div class="surhan-pro-wrapper">
                <div class="surhan-pro-header">
                    <div>
                        <div class="surhan-pro-title">ماسح المستندات الاحترافي</div>
                        <div class="surhan-pro-subtitle">
                            يتم المسح عبر Surhan Agent المحلي مع جلسة آمنة مستقلة لكل عملية.
                        </div>
                    </div>
                    <div class="surhan-pro-badge" id="surhan_agent_badge">
                        Agent: جاري الفحص...
                    </div>
                </div>

                <div class="surhan-pro-workspace">
                    <div class="surhan-pro-preview-column">
                        <div class="surhan-pro-card">
                            <h4>الأوراق الممسوحة</h4>

                            <div class="surhan-pro-page-viewer" id="surhan_agent_page_viewer">
                                لا توجد أوراق ممسوحة حاليًا.
                            </div>

                            <div class="surhan-pro-page-nav">
                                <button type="button" class="btn btn-sm btn-default" id="surhan_agent_page_prev">
                                    السابق
                                </button>
                                <span id="surhan_agent_page_counter">0 / 0</span>
                                <button type="button" class="btn btn-sm btn-default" id="surhan_agent_page_next">
                                    التالي
                                </button>
                            </div>

                            <div class="surhan-pro-report">
                                <h4>تقرير المسح</h4>
                                <div class="surhan-pro-preview" id="surhan_agent_preview">
                                    لا توجد عملية مسح حالية.
                                </div>
                            </div>

                            <div class="surhan-pro-status warning" id="surhan_agent_status">
                                جاري تجهيز بيئة المسح...
                            </div>

                            <div class="surhan-pro-progress">
                                <div class="surhan-pro-progress-bar" id="surhan_agent_progress"></div>
                            </div>
                        </div>
                    </div>

                    <div class="surhan-pro-device-column">
                        <div class="surhan-pro-card">
                            <h4>الجهاز</h4>

                            <div class="surhan-pro-field">
                                <label>جهاز الاسكانر</label>
                                <select id="surhan_agent_device">
                                    <option value="">جاري تحميل الأجهزة...</option>
                                </select>
                            </div>

                            <div class="surhan-pro-actions">
                                <button type="button" class="btn btn-sm btn-default" id="surhan_agent_refresh_devices">
                                    تحديث الأجهزة
                                </button>
                                <button type="button" class="btn btn-sm btn-default" id="surhan_agent_health_check">
                                    فحص Agent
                                </button>
                            </div>

                            <div class="surhan-pro-field">
                                <label>الألوان</label>
                                <select id="surhan_agent_pixel_type">
                                    <option value="Color">Color</option>
                                    <option value="Gray">Gray</option>
                                    <option value="Black & White">Black & White</option>
                                </select>
                            </div>

                            <label class="surhan-pro-check">
                                <input type="checkbox" id="surhan_agent_duplex">
                                <span>مسح الوجهين Duplex</span>
                            </label>
                        </div>
                    </div>
                </div>

                <div class="surhan-pro-hidden-setting" aria-hidden="true">
                    <select id="surhan_agent_paper_source">
                        <option value="Feeder">Feeder</option>
                        <option value="Flatbed">Flatbed</option>
                        <option value="Auto">Auto</option>
                    </select>

                    <select id="surhan_agent_resolution">
                        <option value="200">200 DPI</option>
                        <option value="300">300 DPI</option>
                        <option value="600">600 DPI</option>
                    </select>

                    <select id="surhan_agent_file_type">
                        <option value="jpg">JPG</option>
                        <option value="pdf">PDF</option>
                    </select>

                    <select id="surhan_agent_batch_mode">
                        <option value="Single Page">Single Page</option>
                        <option value="Multi Page">Multi Page</option>
                        <option value="Continuous Batch">Continuous Batch</option>
                    </select>

                    <input type="number" id="surhan_agent_max_pages" min="1" max="1000" value="1">

                    <input type="checkbox" id="surhan_agent_use_feeder" checked>
                    <input type="checkbox" id="surhan_agent_multi_page">
                    <input type="checkbox" id="surhan_agent_silent_scan" checked>
                    <input type="checkbox" id="surhan_agent_show_preview" checked>
                </div>

                <div class="surhan-pro-card" id="surhan_barcode_card" style="margin-top:12px;display:none;">
                    <h4>الباركود</h4>
                    <div class="surhan-pro-field">
                        <label id="surhan_barcode_label">قيمة الباركود</label>
                        <input
                            type="text"
                            id="surhan_barcode_value"
                            autocomplete="off"
                            inputmode="text"
                            placeholder="ضع المؤشر هنا ثم امسح الباركود بجهاز USB"
                        >
                    </div>
                    <div class="surhan-pro-subtitle" id="surhan_barcode_hint">
                        قارئ الباركود USB يعمل مثل لوحة مفاتيح: عند وضع المؤشر داخل الحقل ستظهر القيمة مباشرة.
                    </div>
                </div>


            </div>
        `;

        this.agent_dialog.fields_dict.scanner_html.$wrapper.html(html);

        const wrapper = this.agent_dialog.fields_dict.scanner_html.$wrapper;
        this.agent_dialog.$wrapper.addClass("surhan-scanner-agent-dialog");

        wrapper.find("#surhan_agent_refresh_devices").on("click", () => {
            this.refresh_agent_devices();
        });

        wrapper.find("#surhan_agent_health_check").on("click", () => {
            this.check_agent_and_load_devices();
        });

        wrapper.find("#surhan_agent_page_prev").on("click", () => {
            this.move_agent_preview_page(-1);
        });

        wrapper.find("#surhan_agent_page_next").on("click", () => {
            this.move_agent_preview_page(1);
        });

        wrapper.find("#surhan_agent_batch_mode").on("change", () => {
            this.sync_batch_options();
        });
    },

    set_agent_dialog_defaults: function () {
        const settings = this.current_settings || {};
        const rule = this.current_rule || {};

        const file_type = this.get_file_type(settings, rule).toLowerCase();
        const pixel_type = this.get_pixel_type(settings, rule);
        const resolution = this.get_resolution(settings, rule);

        $("#surhan_agent_file_type").val(file_type || "jpg");
        $("#surhan_agent_pixel_type").val(pixel_type || "Color");
        $("#surhan_agent_resolution").val(String(resolution || 200));

        $("#surhan_agent_paper_source").val(rule.paper_source || settings.default_paper_source || "Feeder");
        $("#surhan_agent_batch_mode").val(rule.scan_batch_mode || settings.default_scan_batch_mode || "Single Page");
        $("#surhan_agent_max_pages").val(this.as_int(rule.max_pages || settings.default_max_pages, 1, 1, 1000));

        $("#surhan_agent_use_feeder").prop("checked", this.as_bool(rule.use_feeder, true));
        $("#surhan_agent_duplex").prop("checked", this.as_bool(rule.duplex, false));
        $("#surhan_agent_multi_page").prop("checked", this.as_bool(rule.multi_page, false));

        const silent_default =
            rule.silent_scan !== undefined && rule.silent_scan !== null
                ? rule.silent_scan
                : settings.enable_silent_scan;

        $("#surhan_agent_silent_scan").prop("checked", this.as_bool(silent_default, true));
        $("#surhan_agent_show_preview").prop("checked", this.as_bool(rule.show_preview, true));

        this.setup_barcode_ui();
        this.sync_batch_options();
        this.apply_locked_scan_settings();
    },

    setup_barcode_ui: function () {
        const frm = this.current_frm;
        const rule = this.current_rule || {};
        const enabled = this.as_bool(rule.enable_barcode, false);
        const barcode_field = rule.barcode_field || "";
        const card = $("#surhan_barcode_card");
        const input = $("#surhan_barcode_value");

        if (!enabled || !barcode_field) {
            card.hide();
            input.val("");
            return;
        }

        const label = this.get_form_field_label(frm, barcode_field) || barcode_field;
        const placeholder = rule.barcode_placeholder || "ضع المؤشر هنا ثم امسح الباركود بجهاز USB";
        const existing_value = frm && frm.doc ? (frm.doc[barcode_field] || "") : "";

        $("#surhan_barcode_label").text("قيمة الباركود - " + label);
        $("#surhan_barcode_hint").text(
            "المصدر: " + (rule.barcode_source || "USB Keyboard Scanner") +
            ". ضع المؤشر داخل الحقل ثم امسح الباركود؛ سيحفظ في الحقل المحدد داخل المستند."
        );

        input.attr("placeholder", placeholder);
        input.val(existing_value);
        card.show();

        input.off("keydown.surhan_barcode").on("keydown.surhan_barcode", (event) => {
            if (event.key === "Enter") {
                event.preventDefault();
                this.set_barcode_value_on_form(input.val());
                this.set_agent_status("تمت قراءة الباركود: " + input.val(), "success");
            }
        });

        input.off("change.surhan_barcode").on("change.surhan_barcode", () => {
            this.set_barcode_value_on_form(input.val());
        });

        setTimeout(() => {
            input.trigger("focus").select();
        }, 500);
    },

    set_barcode_value_on_form: function (value) {
        const frm = this.current_frm;
        const rule = this.current_rule || {};
        const barcode_field = rule.barcode_field || "";

        if (!frm || !barcode_field) {
            return;
        }

        if (frm.set_value) {
            frm.set_value(barcode_field, value || "");
        } else if (frm.doc) {
            frm.doc[barcode_field] = value || "";
        }
    },

    get_form_field_label: function (frm, fieldname) {
        if (!frm || !frm.meta || !frm.meta.fields) {
            return fieldname;
        }

        const df = frm.meta.fields.find((field) => field.fieldname === fieldname);
        return df ? (df.label || df.fieldname) : fieldname;
    },

    sync_batch_options: function () {
        const batch_mode = $("#surhan_agent_batch_mode").val() || "Single Page";
        const is_multi = batch_mode !== "Single Page";
        const max_pages = $("#surhan_agent_max_pages");

        $("#surhan_agent_multi_page").prop("checked", is_multi);

        if (is_multi && parseInt(max_pages.val() || 1) < 2) {
            max_pages.val(200);
        }

        if (!is_multi) {
            max_pages.val(1);
        }
    },

    apply_locked_scan_settings: function () {
        const settings = this.current_settings || {};
        const rule = this.current_rule || {};
        const lock_for_non_admin = this.as_bool(rule.lock_scan_settings, this.as_bool(settings.lock_scan_settings, false));
        const locked = lock_for_non_admin && !this.is_scanner_admin();

        const selectors = [
            "#surhan_agent_file_type",
            "#surhan_agent_batch_mode",
            "#surhan_agent_max_pages",
            "#surhan_agent_paper_source",
            "#surhan_agent_pixel_type",
            "#surhan_agent_resolution",
            "#surhan_agent_use_feeder",
            "#surhan_agent_duplex",
            "#surhan_agent_multi_page",
            "#surhan_agent_silent_scan",
            "#surhan_agent_show_preview"
        ];

        selectors.forEach((selector) => {
            $(selector).prop("disabled", locked);
            $(selector).prop("readonly", locked);
        });

        $("#surhan_agent_device").prop("disabled", false).prop("readonly", false);

        if (locked) {
            $("#surhan_agent_preview").prepend(
                '<div class="alert alert-info" style="margin-bottom:8px;">إعدادات المسح مقفلة ولا يمكن تعديلها إلا من قبل الأدمن.</div>'
            );
        }
    },

    check_agent_and_load_devices: function () {
        const settings = this.current_settings || {};
        const agent_url = settings.agent_url || "http://127.0.0.1:8787";

        this.set_agent_status("جاري فحص Surhan Agent...", "warning");
        this.set_agent_progress(10);

        this.check_local_agent_health(agent_url)
            .then((health) => {
                this.agent_health = health || {};

                $("#surhan_agent_badge").text("Agent: " + (this.agent_health.version || "Running"));

                this.apply_agent_capabilities();
                this.set_agent_status("تم الاتصال بـ Surhan Agent بنجاح.", "success");
                this.set_agent_progress(25);
                this.refresh_agent_devices();
            })
            .catch(() => {
                this.agent_health = null;
                $("#surhan_agent_badge").text("Agent: غير متاح");
                this.set_agent_progress(0);

                if (this.as_bool(settings.show_agent_install_dialog, true)) {
                    this.show_agent_install_dialog(agent_url, settings);
                } else {
                    this.set_agent_status("تعذر الاتصال بـ Surhan Scanner Agent على هذا الجهاز.", "error");
                }
            });
    },

    apply_agent_capabilities: function () {
        const health = this.agent_health || {};
        const version = health.version || "0.0.0";
        const is_enterprise_agent = this.compare_versions(version, "1.0.0") >= 0;

        const fileType = $("#surhan_agent_file_type");
        const batchMode = $("#surhan_agent_batch_mode");
        const multiPage = $("#surhan_agent_multi_page");
        const duplex = $("#surhan_agent_duplex");
        const maxPages = $("#surhan_agent_max_pages");

        fileType.find('option[value="pdf"]').prop("disabled", !is_enterprise_agent);
        batchMode.find('option[value="Multi Page"]').prop("disabled", !is_enterprise_agent);
        batchMode.find('option[value="Continuous Batch"]').prop("disabled", !is_enterprise_agent);
        multiPage.prop("disabled", !is_enterprise_agent);
        duplex.prop("disabled", !is_enterprise_agent);
        maxPages.prop("disabled", !is_enterprise_agent);

        if (!is_enterprise_agent) {
            fileType.val("jpg");
            batchMode.val("Single Page");
            multiPage.prop("checked", false);
            duplex.prop("checked", false);
            maxPages.val(1);

            $("#surhan_agent_preview").html(
                '<div class="surhan-pro-warning-box">' +
                "<b>ملاحظة مهمة:</b><br>" +
                "Agent الحالي v" +
                this.escape_html(version) +
                " يدعم الوضع المستقر فقط:<br>" +
                "JPG صفحة واحدة + Feeder + بدون Duplex.<br>" +
                "سيتم تفعيل PDF و Multi Page و Duplex بعد تثبيت Agent Enterprise v1.0.0." +
                "</div>"
            );
            return;
        }

        $("#surhan_agent_preview").html(
            '<div class="surhan-pro-success-box">' +
            "Agent Enterprise v" +
            this.escape_html(version) +
            " جاهز لدعم PDF و Multi Page و Duplex." +
            "</div>"
        );
    },

    refresh_agent_devices: function () {
        const settings = this.current_settings || {};
        const rule = this.current_rule || {};
        const agent_url = settings.agent_url || "http://127.0.0.1:8787";

        this.set_agent_status("جاري قراءة أجهزة الاسكانر...", "warning");
        this.set_agent_progress(35);

        fetch(agent_url + "/devices", {
            method: "GET",
            headers: {
                "Accept": "application/json"
            },
            signal: this.make_timeout_signal(8000)
        })
            .then((response) => this.parse_json_response(response))
            .then((data) => {
                if (!data || !data.success) {
                    throw new Error("No devices response");
                }

                this.agent_devices = data.devices || [];
                this.populate_agent_devices(rule.agent_scanner_name || "");

                this.set_agent_status("تم تحميل أجهزة الاسكانر. يمكنك بدء المسح الآن.", "success");
                this.set_agent_progress(45);
            })
            .catch((error) => {
                console.error("Surhan Agent devices error:", error);
                this.set_agent_status(
                    "تعذر قراءة أجهزة الاسكانر. تأكد من تعريف الجهاز على Windows ومن تشغيل Surhan Agent.",
                    "error"
                );
                this.set_agent_progress(0);
            });
    },

    populate_agent_devices: function (preferred_name) {
        const select = $("#surhan_agent_device");
        select.empty();

        if (!this.agent_devices.length) {
            select.append('<option value="">لا توجد أجهزة متاحة</option>');
            return;
        }

        this.agent_devices.forEach((device) => {
            const name = device.name || device.device_id || "Scanner";
            select.append(
                '<option value="' + this.escape_attr(name) + '">' + this.escape_html(name) + "</option>"
            );
        });

        if (preferred_name) {
            select.val(preferred_name);
        }

        if (!select.val() && this.agent_devices.length) {
            select.val(this.agent_devices[0].name || this.agent_devices[0].device_id);
        }
    },

    start_agent_scan_from_dialog: function () {
        if (this.active_scan) {
            frappe.msgprint("توجد عملية مسح قيد التنفيذ بالفعل. يرجى الانتظار.");
            return;
        }

        const frm = this.current_frm;
        const settings = this.current_settings || {};
        const rule = this.current_rule || {};

        if (!frm) {
            frappe.msgprint("لا يوجد مستند نشط.");
            return;
        }

        if (frm.is_new()) {
            frappe.msgprint("يرجى حفظ المستند قبل استخدام الاسكانر.");
            return;
        }

        const options = this.collect_agent_options();

        if (this.as_bool(rule.barcode_required, false) && !options.barcode_value) {
            frappe.msgprint("قيمة الباركود مطلوبة قبل بدء المسح. ضع المؤشر داخل حقل الباركود ثم امسح الرمز بجهاز USB.");
            return;
        }

        if (!options.scanner_name) {
            frappe.msgprint("يرجى اختيار جهاز الاسكانر أولاً.");
            return;
        }

        this.active_scan = true;
        this.set_agent_status("جاري إنشاء جلسة مسح آمنة...", "warning");
        this.set_agent_progress(55);

        frappe.call({
            method: "surhan_scanner.agent_api.create_scan_session",
            args: {
                doctype: frm.doctype,
                docname: frm.docname,
                attach_field: rule.attach_field || "",
                upload_mode: rule.upload_mode || "Both",
                rule: rule.name || "",
                is_private: rule.is_private,
                folder: rule.folder || settings.folder || "Home/Attachments",

                file_type: options.file_type,
                resolution: options.resolution,
                pixel_type: options.pixel_type,
                multi_page: options.multi_page,
                use_feeder: options.use_feeder,
                duplex: options.duplex,

                scanner_name: options.scanner_name,
                profile: rule.agent_profile || "",

                paper_source: options.paper_source,
                silent_scan: options.silent_scan,
                show_preview: options.show_preview,
                scan_batch_mode: options.scan_batch_mode,
                max_pages: options.max_pages,
                upload_strategy: options.upload_strategy,

                barcode_field: options.barcode_field,
                barcode_value: options.barcode_value,
                barcode_source: options.barcode_source
            },
            callback: (r) => {
                const session = r.message;

                if (!session || !session.success) {
                    this.active_scan = false;
                    this.set_agent_status("تعذر إنشاء جلسة المسح.", "error");
                    this.set_agent_progress(0);
                    return;
                }

                this.call_local_agent_scan(
                    session.agent_url || settings.agent_url || "http://127.0.0.1:8787",
                    session,
                    settings,
                    rule,
                    options
                );
            },
            error: () => {
                this.active_scan = false;
                this.set_agent_status("حدث خطأ أثناء إنشاء جلسة المسح.", "error");
                this.set_agent_progress(0);
            }
        });
    },

    collect_agent_options: function () {
        const settings = this.current_settings || {};
        const rule = this.current_rule || {};

        const rule_value = (fieldname, fallback_value) => {
            const value = rule[fieldname];
            if (value !== undefined && value !== null && value !== "") {
                return value;
            }
            return fallback_value;
        };

        const selected_file_type = String(
            rule_value("file_type", this.get_file_type(settings, rule) || "jpg")
        ).toLowerCase();

        const selected_resolution = this.as_int(
            rule_value("resolution", this.get_resolution(settings, rule) || 200),
            200,
            75,
            1200
        );

        const selected_paper_source = String(
            rule_value("paper_source", settings.default_paper_source || "Feeder")
        );

        const selected_batch_mode = String(
            rule_value("scan_batch_mode", settings.default_scan_batch_mode || "Single Page")
        );

        const selected_max_pages = this.as_int(
            rule_value("max_pages", settings.default_max_pages || 1),
            1,
            1,
            1000
        );

        const selected_use_feeder = this.as_bool(
            rule_value("use_feeder", true),
            true
        ) ? 1 : 0;

        const selected_multi_page = (
            this.as_bool(rule_value("multi_page", false), false) ||
            selected_batch_mode !== "Single Page"
        ) ? 1 : 0;

        const silent_default =
            rule.silent_scan !== undefined && rule.silent_scan !== null
                ? rule.silent_scan
                : settings.enable_silent_scan;

        const selected_silent_scan = this.as_bool(silent_default, true) ? 1 : 0;
        const selected_show_preview = this.as_bool(rule_value("show_preview", true), true) ? 1 : 0;

        const barcode_field = rule.barcode_field || "";
        const barcode_value = barcode_field ? ($("#surhan_barcode_value").val() || "") : "";

        if (barcode_field && barcode_value) {
            this.set_barcode_value_on_form(barcode_value);
        }

        const options = {
            // مسموح تغييره من الديالوق فقط
            scanner_name: $("#surhan_agent_device").val() || rule.agent_scanner_name || "",
            pixel_type: $("#surhan_agent_pixel_type").val() || rule_value("pixel_type", this.get_pixel_type(settings, rule) || "Color"),
            duplex: $("#surhan_agent_duplex").is(":checked") ? 1 : 0,

            // من الـ Rule فقط
            file_type: selected_file_type,
            resolution: selected_resolution,
            paper_source: selected_paper_source,
            use_feeder: selected_use_feeder,
            multi_page: selected_multi_page,
            silent_scan: selected_silent_scan,
            show_preview: selected_show_preview,
            scan_batch_mode: selected_batch_mode,
            max_pages: selected_max_pages,
            upload_strategy: rule.upload_strategy || "Direct Upload",

            barcode_field: barcode_field,
            barcode_value: barcode_value,
            barcode_source: rule.barcode_source || ""
        };

        console.log("Surhan Effective Scan Options:", options);
        return options;
    },

    call_local_agent_scan: function (agent_url, session, settings, rule, options) {
        const timeout_seconds =
            session.agent_scan_timeout_seconds ||
            settings.agent_scan_timeout_seconds ||
            120;

        this.set_agent_status("جاري المسح من الجهاز ورفع الملف...", "warning");
        this.set_agent_progress(70);

        fetch(agent_url + "/scan-and-upload", {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify({
                scan_session_id: session.scan_session_id,
                scan_token: session.scan_token,
                upload_url: session.upload_url,
                farabi_url: session.farabi_url,

                doctype: session.doctype,
                docname: session.docname,
                attach_field: session.attach_field,
                upload_mode: session.upload_mode,

                file_type: options.file_type,
                resolution: options.resolution,
                pixel_type: options.pixel_type,
                multi_page: options.multi_page,
                use_feeder: options.use_feeder,
                duplex: options.duplex,

                scanner_name: options.scanner_name,
                profile: session.profile || "",

                paper_source: options.paper_source,
                silent_scan: options.silent_scan,
                show_preview: options.show_preview,
                scan_batch_mode: options.scan_batch_mode,
                max_pages: options.max_pages,
                upload_strategy: options.upload_strategy,

                barcode_field: options.barcode_field,
                barcode_value: options.barcode_value,
                barcode_source: options.barcode_source,

                enable_upload_retry: session.enable_upload_retry,
                upload_retry_count: session.upload_retry_count,
                upload_retry_delay_seconds: session.upload_retry_delay_seconds
            }),
            signal: this.make_timeout_signal(timeout_seconds * 1000)
        })
            .then((response) => this.parse_json_response(response))
            .then((data) => {
                console.log("Surhan Agent Response:", data);

                if (!data || !data.success) {
                    const msg = data && data.message
                        ? data.message
                        : "فشل المسح عبر Surhan Agent";

                    this.set_agent_status(msg, "error");
                    this.set_agent_progress(0);
                    this.active_scan = false;
                    return;
                }

                this.set_agent_status("تم المسح والرفع بنجاح.", "success");
                this.set_agent_progress(100);
                this.show_agent_upload_result(data);

                frappe.show_alert({
                    message: "تم المسح والرفع بنجاح",
                    indicator: "green"
                });

                this.active_scan = false;

                // Phase 41: keep the scanner dialog open after success.
                // The user closes it manually.
            })
            .catch((error) => {
                console.error("Surhan Agent Error:", error);

                this.active_scan = false;
                this.set_agent_progress(0);

                if (settings.show_agent_install_dialog) {
                    this.show_agent_install_dialog(agent_url, settings);
                    return;
                }

                this.set_agent_status(
                    "تعذر الاتصال بـ Surhan Scanner Agent على هذا الجهاز.",
                    "error"
                );
            });
    },

    extract_agent_preview_pages: function (data) {
        if (!data) {
            return [];
        }

        const candidates = [
            data.pages,
            data.preview_pages,
            data.scanned_pages,
            data.images,
            data.files
        ];

        for (const candidate of candidates) {
            if (Array.isArray(candidate) && candidate.length) {
                return candidate;
            }
        }

        return [];
    },

    set_agent_preview_pages: function (pages, total_pages) {
        this.agent_preview_pages = Array.isArray(pages) ? pages : [];
        this.agent_preview_total_pages = total_pages || this.agent_preview_pages.length || 0;
        this.agent_preview_page_index = 0;
        this.render_agent_preview_page();
    },

    move_agent_preview_page: function (delta) {
        const total = this.agent_preview_total_pages || 0;
        if (!total) {
            return;
        }

        const max_index = total - 1;
        const current = this.agent_preview_page_index || 0;
        this.agent_preview_page_index = Math.max(0, Math.min(max_index, current + delta));
        this.render_agent_preview_page();
    },

    render_agent_preview_page: function () {
        const viewer = $("#surhan_agent_page_viewer");
        const counter = $("#surhan_agent_page_counter");
        const prev_btn = $("#surhan_agent_page_prev");
        const next_btn = $("#surhan_agent_page_next");

        if (!viewer.length) {
            return;
        }

        const pages = this.agent_preview_pages || [];
        const total = this.agent_preview_total_pages || pages.length || 0;
        let index = this.agent_preview_page_index || 0;

        if (!total) {
            viewer.html("لا توجد أوراق ممسوحة حاليًا.");
            counter.text("0 / 0");
            prev_btn.prop("disabled", true);
            next_btn.prop("disabled", true);
            return;
        }

        if (index >= total) {
            index = total - 1;
            this.agent_preview_page_index = index;
        }

        const page = pages[index] || {};
        let page_url =
            page.url ||
            page.file_url ||
            page.preview_url ||
            page.image_url ||
            page.thumbnail_url ||
            "";

        if (page_url) {
            const is_pdf = String(page_url).toLowerCase().includes(".pdf");
            if (is_pdf) {
                const page_number = page.page_number || (index + 1);
                page_url = String(page_url).split("#")[0] + "#page=" + String(page_number) + "&view=FitH";
            }

            const escaped_url = this.escape_html(page_url);
            if (is_pdf) {
                viewer.html('<iframe src="' + escaped_url + '" style="width:100%;height:560px;border:0;"></iframe>');
            } else {
                viewer.html('<img src="' + escaped_url + '" alt="Scanned Page">');
            }
        } else {
            viewer.html("تم مسح الصفحة " + String(index + 1) + " من " + String(total));
        }

        counter.text(String(index + 1) + " / " + String(total));
        prev_btn.prop("disabled", index <= 0);
        next_btn.prop("disabled", index >= total - 1);
    },

    show_agent_upload_result: function (data) {
        const file_name =
            data.file_name ||
            (data.file && data.file.file_name) ||
            "scan file";

        const file_size = data.file_size || (data.file && data.file.file_size) || "";

        const file_url =
            data.file_url ||
            (data.file && data.file.file_url) ||
            (data.upload && data.upload.file_url) ||
            "";

        const total_pages =
            data.page_count ||
            data.pages_count ||
            data.total_pages ||
            data.scanned_page_count ||
            0;

        let pages = this.extract_agent_preview_pages(data);

        // Agent يرجع غالبًا PDF واحد + عدد الصفحات.
        // هنا نحول الـ PDF إلى صفحات قابلة للتنقل داخل نفس مربع العرض.
        if ((!pages || !pages.length) && file_url) {
            const count = this.as_int(total_pages, 1, 1, 2000);
            pages = [];

            for (let i = 1; i <= count; i++) {
                pages.push({
                    file_url: file_url,
                    page_number: i,
                    is_pdf_page: String(file_url).toLowerCase().includes(".pdf")
                });
            }
        }

        this.set_agent_preview_pages(pages, total_pages || pages.length || 0);

        let html =
            "<b>تم رفع الملف بنجاح</b><br>" +
            "اسم الملف: " + this.escape_html(file_name);

        if (file_size) {
            html += "<br>الحجم: " + this.format_file_size(file_size);
        }

        // Phase 41C: إخفاء رقم الجلسة من تقرير المسح حسب الطلب.
        $("#surhan_agent_preview").html(html);
    },

    check_local_agent_health: function (agent_url) {
        return fetch(agent_url + "/health", {
            method: "GET",
            headers: {
                "Accept": "application/json"
            },
            signal: this.make_timeout_signal(5000)
        }).then((response) => {
            if (!response.ok) {
                throw new Error("Agent health check failed");
            }

            return response.json();
        });
    },

    show_agent_install_dialog: function (agent_url, settings) {
        settings = settings || {};

        const download_url = this.get_absolute_url(
            settings.agent_download_url ||
            "/assets/surhan_scanner/agent/releases/SurhanScannerAgentSetup-1.0.0.exe"
        );

        const version_url = this.get_absolute_url(
            settings.agent_version_check_url ||
            "/assets/surhan_scanner/agent/version.json"
        );

        const latest_version = settings.agent_latest_version || "1.0.0";

        const html =
            '<div style="line-height:1.9;">' +
            '<div class="alert alert-warning">' +
            "<b>برنامج Surhan Scanner Agent غير مثبت أو غير شغال على هذا الجهاز.</b><br>" +
            "يجب تثبيته مرة واحدة حتى يعمل الاسكانر من داخل Farabi." +
            "</div>" +
            "<ol>" +
            "<li>اضغط تحميل البرنامج.</li>" +
            "<li>شغل ملف التثبيت على الجهاز.</li>" +
            "<li>بعد انتهاء التثبيت اضغط إعادة الفحص.</li>" +
            "</ol>" +
            "<p><b>Agent URL:</b><br><span class=\"text-muted\">" + this.escape_html(agent_url) + "</span></p>" +
            "<p><b>Latest Version:</b> " + this.escape_html(latest_version) + "</p>" +
            '<a class="btn btn-primary" href="' + this.escape_attr(download_url) + '" target="_blank" download>' +
            "تحميل Surhan Scanner Agent" +
            "</a>" +
            '<a class="btn btn-default" href="' + this.escape_attr(version_url) + '" target="_blank" style="margin-right:8px;">' +
            "معلومات النسخة" +
            "</a>" +
            "</div>";

        const dialog = new frappe.ui.Dialog({
            title: "تثبيت Surhan Scanner Agent",
            size: "large",
            fields: [
                {
                    fieldtype: "HTML",
                    fieldname: "install_html",
                    options: html
                }
            ],
            primary_action_label: "إعادة الفحص",
            primary_action: () => {
                this.check_local_agent_health(agent_url)
                    .then(() => {
                        dialog.hide();

                        frappe.show_alert({
                            message: "تم العثور على Surhan Scanner Agent",
                            indicator: "green"
                        });

                        this.check_agent_and_load_devices();
                    })
                    .catch(() => {
                        frappe.msgprint(
                            "ما زال Surhan Scanner Agent غير متاح على " + agent_url
                        );
                    });
            }
        });

        dialog.show();
    },

    get_file_type: function (settings, rule) {
        if (rule.file_type && rule.file_type !== "Default") {
            return rule.file_type;
        }

        return settings.default_file_type || "JPG";
    },

    get_resolution: function (settings, rule) {
        return rule.resolution || settings.default_resolution || 200;
    },

    get_pixel_type: function (settings, rule) {
        if (rule.pixel_type && rule.pixel_type !== "Default") {
            return rule.pixel_type;
        }

        return settings.default_pixel_type || "Color";
    },

    is_scanner_admin: function () {
        const roles = frappe.user_roles || [];
        return roles.includes("System Manager") || roles.includes("Surhan Scanner Admin");
    },

    set_agent_status: function (message, type) {
        const el = $("#surhan_agent_status");

        if (!el.length) {
            return;
        }

        el.removeClass("success warning error");
        el.addClass(type || "");
        el.text(message || "");
    },

    set_agent_progress: function (percent) {
        const value = Math.max(0, Math.min(100, parseInt(percent || 0, 10)));
        $("#surhan_agent_progress").css("width", value + "%");
    },

    make_timeout_signal: function (timeout_ms) {
        if (window.AbortSignal && AbortSignal.timeout) {
            return AbortSignal.timeout(timeout_ms);
        }

        const controller = new AbortController();

        setTimeout(() => {
            controller.abort();
        }, timeout_ms);

        return controller.signal;
    },

    parse_json_response: function (response) {
        return response.text().then((text) => {
            let data = {};

            if (text) {
                try {
                    data = JSON.parse(text);
                } catch (error) {
                    throw new Error("Invalid JSON response: " + text.slice(0, 200));
                }
            }

            if (!response.ok) {
                throw new Error(data.message || response.statusText || "HTTP error");
            }

            return data;
        });
    },

    get_absolute_url: function (url) {
        if (!url) {
            return "";
        }

        url = String(url).trim();

        if (url.startsWith("http://") || url.startsWith("https://")) {
            return url;
        }

        return window.location.origin + url;
    },

    as_bool: function (value, default_value) {
        if (value === undefined || value === null || value === "") {
            return !!default_value;
        }

        if (value === 1 || value === "1" || value === true || value === "true") {
            return true;
        }

        if (value === 0 || value === "0" || value === false || value === "false") {
            return false;
        }

        return !!value;
    },

    as_int: function (value, default_value, min, max) {
        let number = parseInt(value, 10);

        if (isNaN(number)) {
            number = default_value;
        }

        if (min !== undefined) {
            number = Math.max(min, number);
        }

        if (max !== undefined) {
            number = Math.min(max, number);
        }

        return number;
    },

    compare_versions: function (a, b) {
        const clean = function (value) {
            return String(value || "0.0.0")
                .trim()
                .replace(/^v/i, "")
                .split(".")
                .map((x) => {
                    const n = parseInt(x || 0, 10);
                    return isNaN(n) ? 0 : n;
                });
        };

        const pa = clean(a);
        const pb = clean(b);
        const length = Math.max(pa.length, pb.length);

        for (let i = 0; i < length; i++) {
            const na = pa[i] || 0;
            const nb = pb[i] || 0;

            if (na > nb) {
                return 1;
            }

            if (na < nb) {
                return -1;
            }
        }

        return 0;
    },

    format_file_size: function (bytes) {
        bytes = parseInt(bytes || 0, 10);

        if (bytes < 1024) {
            return bytes + " B";
        }

        if (bytes < 1024 * 1024) {
            return (bytes / 1024).toFixed(1) + " KB";
        }

        return (bytes / 1024 / 1024).toFixed(1) + " MB";
    },

    safe_id: function (value) {
        return String(value || "").replace(/[^A-Za-z0-9_-]/g, "_");
    },

    escape_html: function (value) {
        return String(value || "")
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#039;");
    },

    escape_attr: function (value) {
        return this.escape_html(value).replace(/`/g, "&#096;");
    }
};

(function () {

    function try_apply() {
        if (!window.cur_frm || !window.surhan_scanner?.manager) return;

        window.surhan_scanner.manager.apply_to_form(window.cur_frm);
    }

    function schedule_try_apply() {
        setTimeout(try_apply, 500);
    }

    // form refresh
    $(document).on("form-refresh", function () {
        schedule_try_apply();
    });

    // router change
    if (frappe.router && frappe.router.on) {
        frappe.router.on("change", function () {
            setTimeout(try_apply, 700);
            setTimeout(try_apply, 1500);
            setTimeout(try_apply, 2500);
        });
    }

    // document ready
    $(document).ready(function () {
        setTimeout(try_apply, 1000);
        setTimeout(try_apply, 2500);
    });

})();


(function () {
}, 800);
    }
})();