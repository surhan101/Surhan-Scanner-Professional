frappe.pages["agent_dashboard"].on_page_load = function (wrapper) {
  const page = frappe.ui.make_app_page({
    parent: wrapper,
    title: __("Surhan Scanner Agent Dashboard"),
    single_column: true,
  });

  const $page = $(page.body);

  $page.html(`
    <div class="surhan-agent-dashboard">
      <div class="row mb-3">
        <div class="col-md-3">
          <input type="text" class="form-control" id="sag-search" placeholder="${__("Search by agent, machine, user, IP...")}">
        </div>
        <div class="col-md-2">
          <select class="form-control" id="sag-status">
            <option value="All">${__("All Statuses")}</option>
            <option value="Online">${__("Online")}</option>
            <option value="Offline">${__("Offline")}</option>
            <option value="Warning">${__("Warning")}</option>
            <option value="Blocked">${__("Blocked")}</option>
          </select>
        </div>
        <div class="col-md-2">
          <input type="text" class="form-control" id="sag-version" placeholder="${__("Agent Version")}">
        </div>
        <div class="col-md-2">
          <select class="form-control" id="sag-update">
            <option value="">${__("Update Filter")}</option>
            <option value="1">${__("Update Available")}</option>
            <option value="0">${__("No Update")}</option>
          </select>
        </div>
        <div class="col-md-3 text-right">
          <button class="btn btn-primary mr-2" id="sag-refresh">${__("Refresh")}</button>
          <button class="btn btn-warning" id="sag-mark-offline">${__("Mark Stale Offline")}</button>
        </div>
      </div>

      <div id="sag-summary" class="row mb-3"></div>

      <div class="card">
        <div class="card-body">
          <div class="table-responsive">
            <table class="table table-bordered table-hover" id="sag-table">
              <thead>
                <tr>
                  <th>${__("Agent ID")}</th>
                  <th>${__("Machine")}</th>
                  <th>${__("User")}</th>
                  <th>${__("Status")}</th>
                  <th>${__("Last Seen")}</th>
                  <th>${__("Agent Version")}</th>
                  <th>${__("Scanner")}</th>
                  <th>${__("Scans")}</th>
                  <th>${__("Update")}</th>
                  <th>${__("Actions")}</th>
                </tr>
              </thead>
              <tbody></tbody>
            </table>
          </div>

          <div class="text-center mt-3">
            <button class="btn btn-outline-secondary" id="sag-load-more">${__("Load More")}</button>
          </div>
        </div>
      </div>
    </div>
  `);

  const state = {
    limit_start: 0,
    limit_page_length: 20,
    has_more: false,
    loading: false,
    filters: {
      search: "",
      status: "All",
      agent_version: "",
      update_available: "",
    },
  };

  function badgeClass(status) {
    if (status === "Online") return "badge badge-success";
    if (status === "Offline") return "badge badge-secondary";
    if (status === "Warning") return "badge badge-warning";
    if (status === "Blocked") return "badge badge-danger";
    return "badge badge-light";
  }

  function esc(value) {
    return frappe.utils.escape_html(value == null ? "" : String(value));
  }

  function renderSummary(summary) {
    const items = [
      { label: __("Total"), value: summary.total || 0, cls: "bg-primary text-white" },
      { label: __("Online"), value: summary.online || 0, cls: "bg-success text-white" },
      { label: __("Offline"), value: summary.offline || 0, cls: "bg-secondary text-white" },
      { label: __("Warning"), value: summary.warning || 0, cls: "bg-warning text-dark" },
      { label: __("Blocked"), value: summary.blocked || 0, cls: "bg-danger text-white" },
      { label: __("Update Available"), value: summary.update_available || 0, cls: "bg-info text-white" },
    ];

    $("#sag-summary").html(
      items.map((item) => `
        <div class="col-md-2 mb-2">
          <div class="card ${item.cls}">
            <div class="card-body p-3">
              <div style="font-size: 12px;">${esc(item.label)}</div>
              <div style="font-size: 24px; font-weight: 700;">${esc(item.value)}</div>
            </div>
          </div>
        </div>
      `).join("")
    );
  }

  function renderRows(rows, append = false) {
    const tbody = $("#sag-table tbody");

    const html = rows.map((row) => {
      const updateText = row.update_available ? __("Yes") : __("No");
      const updateClass = row.update_available ? "badge badge-info" : "badge badge-light";

      return `
        <tr>
          <td><code>${esc(row.agent_id)}</code></td>
          <td>${esc(row.machine_name)}</td>
          <td>${esc(row.windows_user)}</td>
          <td><span class="${badgeClass(row.status)}">${esc(row.status)}</span></td>
          <td>${esc(row.last_seen || "")}</td>
          <td>${esc(row.agent_version || "")}</td>
          <td>${esc(row.scanner_name || "")}</td>
          <td>${esc(row.total_scans || 0)}</td>
          <td><span class="${updateClass}">${updateText}</span></td>
          <td>
            <div class="btn-group btn-group-sm">
              <button class="btn btn-outline-success sag-set-status" data-agent="${esc(row.agent_id)}" data-status="Online">${__("Online")}</button>
              <button class="btn btn-outline-warning sag-set-status" data-agent="${esc(row.agent_id)}" data-status="Warning">${__("Warning")}</button>
              <button class="btn btn-outline-secondary sag-set-status" data-agent="${esc(row.agent_id)}" data-status="Offline">${__("Offline")}</button>
              <button class="btn btn-outline-danger sag-set-status" data-agent="${esc(row.agent_id)}" data-status="Blocked">${__("Blocked")}</button>
            </div>
          </td>
        </tr>
      `;
    }).join("");

    if (append) {
      tbody.append(html);
    } else {
      tbody.html(html);
    }
  }

  function loadData(reset = false) {
    if (state.loading) return;
    state.loading = true;

    if (reset) {
      state.limit_start = 0;
      $("#sag-table tbody").html("");
    }

    frappe.call({
      method: "surhan_scanner.agent_api.get_agent_dashboard_data",
      args: {
        search: state.filters.search,
        status: state.filters.status,
        agent_version: state.filters.agent_version,
        update_available: state.filters.update_available,
        limit_start: state.limit_start,
        limit_page_length: state.limit_page_length,
      },
      callback(r) {
        const data = r.message || r;

        if (!data || !data.success) {
          frappe.msgprint(data && data.message ? data.message : __("Could not load dashboard data"));
          return;
        }

        renderSummary(data.summary || {});
        renderRows(data.agents || [], !reset);

        state.has_more = data.pagination && data.pagination.has_more;
        if (state.has_more) {
          $("#sag-load-more").show();
        } else {
          $("#sag-load-more").hide();
        }

        state.loading = false;
      },
      error() {
        state.loading = false;
        frappe.msgprint(__("Failed to load dashboard data"));
      },
    });
  }

  function bindEvents() {
    $("#sag-refresh").on("click", function () {
      state.filters.search = $("#sag-search").val().trim();
      state.filters.status = $("#sag-status").val();
      state.filters.agent_version = $("#sag-version").val().trim();
      state.filters.update_available = $("#sag-update").val();
      loadData(true);
    });

    $("#sag-load-more").on("click", function () {
      if (!state.has_more) return;
      state.limit_start += state.limit_page_length;
      loadData(false);
    });

    $("#sag-mark-offline").on("click", function () {
      frappe.call({
        method: "surhan_scanner.agent_api.mark_stale_agents_offline",
        callback(r) {
          const data = r.message || r;
          if (data && data.success) {
            frappe.show_alert({ message: __("Offline status updated"), indicator: "green" });
            loadData(true);
          } else {
            frappe.msgprint(data && data.message ? data.message : __("Could not update offline status"));
          }
        },
      });
    });

    $page.on("click", ".sag-set-status", function () {
      const agentId = $(this).data("agent");
      const status = $(this).data("status");

      frappe.call({
        method: "surhan_scanner.agent_api.set_agent_device_status",
        args: {
          agent_id: agentId,
          status: status,
        },
        callback(r) {
          const data = r.message || r;
          if (data && data.success) {
            frappe.show_alert({ message: __("Status updated"), indicator: "green" });
            loadData(true);
          } else {
            frappe.msgprint(data && data.message ? data.message : __("Could not update status"));
          }
        },
      });
    });
  }

  bindEvents();
  loadData(true);
};

frappe.pages["agent_dashboard"].refresh = function (wrapper) {
  const page = wrapper.page;
  if (page) {
    $(page.body).find("#sag-refresh").trigger("click");
  }
};
