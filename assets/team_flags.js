// Team flags section on a per-team challenge's admin page (file and instance challenges alike):
// every team's flag, solve and sharing status, their file or instance, and Regenerate.
(() => {
  const root = (window.init && init.urlRoot) || "";
  const match = location.pathname.slice(root.length).replace(/\/$/, "").match(/^\/admin\/challenges\/(\d+)$/);
  if (!match) return;
  const challengeId = Number(match[1]);
  const api = path => `${root}/admin/flagprint/flags/${challengeId}${path}`;

  let data = null;
  let filter = "";
  let armed = null; // "all" or an account id waiting for a confirming second click
  const section = document.createElement("section");
  section.className = "container-fluid mb-4";
  section.style.width = "80%";

  async function request(url, body) {
    const response = await fetch(url, {
      method: body === undefined ? "GET" : "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", Accept: "application/json", "CSRF-Token": init.csrfNonce },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    const json = await response.json().catch(() => ({}));
    if (!response.ok || json.success === false) throw new Error(json.error || `Request failed (${response.status})`);
    return json;
  }

  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = text;
    return node;
  }

  function button(label, className, onClick) {
    const b = el("button", `btn btn-sm ${className}`, label);
    b.type = "button";
    b.addEventListener("click", onClick);
    return b;
  }

  function when(iso) {
    return iso ? new Date(iso).toLocaleString() : "";
  }

  function say(text, isError) {
    const note = section.querySelector(".tf-note");
    note.className = `tf-note small mb-2 ${isError ? "text-danger" : "text-success"}`;
    note.textContent = text;
  }

  async function load() {
    try {
      data = await request(api(""));
    } catch (error) {
      return; // not a per-team challenge: no section
    }
    if (!section.isConnected) {
      const anchor = document.querySelector("#challenge-properties")?.closest(".container-fluid");
      if (!anchor) return;
      anchor.parentNode.insertBefore(section, anchor);
    }
    render();
  }

  async function regenerate(body, label) {
    armed = null;
    try {
      const result = await request(api("/regenerate"), body);
      await load();
      const r = result.removed || { solves: 0, attempts: 0 };
      say(`Reset ${label}${result.count > 1 ? ` (${result.count} ${data.teams_mode ? "teams" : "users"})` : ""}: new flag, ` +
        `${r.solves} solve${r.solves === 1 ? "" : "s"} and ${r.attempts} attempt${r.attempts === 1 ? "" : "s"} removed, scoreboard updated. ` +
        (data.challenge.mode === "instance" ? "Running instances were stopped so the next start carries the new flag."
          : data.challenge.mode === "variants" ? "They may get a different variant." : "Files are rebuilt on the next download.") +
        " Share alerts are kept.");
    } catch (error) {
      say(error.message, true);
    }
  }

  async function stopInstance(instanceId, name) {
    try {
      await request(`${root}/containers/api/kill`, { instance_id: instanceId });
      await load();
      say(`Stopped ${name}'s instance.`);
    } catch (error) {
      say(error.message, true);
    }
  }

  function exportCsv() {
    const header = ["team", "flag", "version", "solved", "wrong_attempts", "leaked", "copied"];
    const lines = [header.join(",")];
    data.rows.forEach(r => {
      lines.push([r.name, r.flag || "", r.version, r.solved || "", r.fails, r.leaked, r.copied]
        .map(v => `"${String(v).replace(/"/g, '""')}"`).join(","));
    });
    const link = document.createElement("a");
    link.href = URL.createObjectURL(new Blob([lines.join("\n")], { type: "text/csv" }));
    link.download = `${data.challenge.name.replace(/[^\w-]+/g, "_")}-team-flags.csv`;
    link.click();
    URL.revokeObjectURL(link.href);
  }

  function render() {
    const { challenge, rows, teams_mode: teamsMode } = data;
    const who = teamsMode ? "team" : "user";
    const isInstance = challenge.mode === "instance";
    const hasFile = Boolean(challenge.file);
    const solved = rows.filter(r => r.solved).length;
    const leaks = rows.reduce((n, r) => n + r.leaked, 0);
    const running = rows.filter(r => r.instance && r.instance.status === "running").length;

    section.replaceChildren();
    const card = el("div", "card");
    const body = el("div", "card-body");

    const head = el("div", "d-flex flex-wrap align-items-center mb-2");
    head.style.gap = "12px";
    head.append(el("h4", "mb-0 mr-2", `${teamsMode ? "Team" : "User"} flags`));
    const facts = [
      `${challenge.mode === "variants" ? "Variants" : isInstance ? "Instance" : `File: ${challenge.mode}`}`,
      challenge.template ? `Template ${challenge.template}` : null,
      `${solved}/${rows.length} solved`,
      isInstance ? `${running} running` : null,
      leaks ? `${leaks} shared-flag submission${leaks === 1 ? "" : "s"}` : null,
    ].filter(Boolean);
    facts.forEach(f => head.append(el("span", `badge ${f.includes("shared") ? "badge-danger" : "badge-secondary"}`, f)));
    body.append(head);

    const tools = el("div", "d-flex flex-wrap align-items-center mb-2");
    tools.style.gap = "8px";
    const search = el("input", "form-control form-control-sm");
    search.placeholder = `Filter ${who}s`;
    search.style.maxWidth = "240px";
    search.value = filter;
    search.addEventListener("input", () => { filter = search.value; fillRows(); });
    tools.append(
      search,
      button(armed === "all" ? `Click again: reset every ${who} on this challenge` : `Regenerate all`, armed === "all" ? "btn-danger" : "btn-outline-danger", () => {
        if (armed !== "all") { armed = "all"; render(); return; }
        regenerate({ all: true }, `every ${who}`);
      }),
      button("Export CSV", "btn-outline-secondary", exportCsv),
    );
    body.append(tools, el("p", "tf-note small mb-2"));
    body.append(el("p", "small text-muted mb-2",
      `Regenerate gives a new flag and resets that ${who} on this challenge: their solve, points and attempts are removed, ` +
      `as if the challenge were newly deployed for them. Share alerts and Hall of Shame entries stay.`));

    const table = el("table", "table table-sm table-striped mb-0");
    const headRow = el("tr");
    [teamsMode ? "Team" : "User", challenge.mode === "variants" ? "Variant" : "Flag", "Solved", "Wrong", "Leaked", "Copied",
      isInstance ? "Instance" : null, hasFile ? "File" : null, ""]
      .filter(h => h !== null).forEach(h => headRow.append(el("th", "", h)));
    const thead = el("thead");
    thead.append(headRow);
    const tbody = el("tbody");
    table.append(thead, tbody);
    const scroller = el("div");
    scroller.style.maxHeight = "520px";
    scroller.style.overflowY = "auto";
    scroller.append(table);
    body.append(scroller);
    card.append(body);
    section.append(card);

    function fillRows() {
      tbody.replaceChildren();
      const needle = filter.trim().toLowerCase();
      const shown = rows.filter(r => !needle || r.name.toLowerCase().includes(needle) || (r.flag || "").toLowerCase().includes(needle));
      shown.forEach(r => {
        const tr = el("tr");
        const name = el("td");
        const link = el("a", "", r.name);
        link.href = r.url;
        name.append(link);
        if (r.hidden) name.append(" ", el("span", "badge badge-secondary", "hidden"));
        if (r.banned) name.append(" ", el("span", "badge badge-danger", "banned"));

        const flag = el("td");
        flag.append(el("code", "", r.flag || "—"));
        if (r.version) flag.append(" ", el("span", "badge badge-info", `v${r.version + 1}`));

        const solvedCell = el("td", r.solved ? "text-success" : "text-muted", r.solved ? `✓ ${when(r.solved)}` : "—");
        const fails = el("td", "", String(r.fails));
        const leaked = el("td");
        leaked.append(r.leaked ? el("span", "badge badge-danger", String(r.leaked)) : document.createTextNode("0"));
        const copied = el("td");
        copied.append(r.copied ? el("span", "badge badge-danger", String(r.copied)) : document.createTextNode("0"));
        tr.append(name, flag, solvedCell, fails, leaked, copied);

        if (isInstance) {
          const cell = el("td");
          const inst = r.instance;
          if (!inst) cell.append(el("span", "text-muted", "—"));
          else if (inst.status === "running") {
            if (inst.access.startsWith("http")) {
              const a = el("a", "", inst.access);
              a.href = inst.access; a.target = "_blank"; a.rel = "noopener";
              cell.append(a);
            } else cell.append(el("code", "", inst.access));
            cell.append(" ", button("Stop", "btn-outline-danger py-0", () => stopInstance(inst.id, r.name)));
          } else cell.append(el("span", "badge badge-warning", inst.status));
          tr.append(cell);
        }
        if (hasFile) {
          const cell = el("td");
          const a = el("a", "", "Download");
          a.href = r.file;
          cell.append(a);
          tr.append(cell);
        }
        const actions = el("td", "text-right text-nowrap");
        const key = String(r.id);
        actions.append(button(armed === key ? "Click again: reset" : "Regenerate", armed === key ? "btn-danger" : "btn-outline-secondary", () => {
          if (armed !== key) { armed = key; fillRows(); return; }
          regenerate({ account_id: r.id }, r.name);
        }));
        tr.append(actions);
        tbody.append(tr);
      });
      if (!shown.length) {
        const tr = el("tr");
        const td = el("td", "text-muted", rows.length ? "No match." : `No ${who}s yet.`);
        td.colSpan = 9;
        tr.append(td);
        tbody.append(tr);
      }
    }
    fillRows();
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", load);
  else load();
})();
