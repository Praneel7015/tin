"use strict";

// People (Paper PEOPLE-A1, C1 and C1b): everyone this project keeps a record of, as a grid
// with segments, and one person in a side panel with their fields, timeline and Forget.
// Tin's workflows write the records; this view reads them and forgets a person on request.
window.TinPeople = (() => {
  const PAGE = 50;
  const MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"];
  const RELATIONSHIP = { connected: "Connected", pending: "Pending", none: "Not connected" };
  // LinkedIn's names for its reactions.
  const REACTIONS = {
    LIKE: "Like", PRAISE: "Celebrate", EMPATHY: "Love", INTEREST: "Insightful",
    APPRECIATION: "Support", ENTERTAINMENT: "Funny",
  };
  const SEGMENTS = [
    { key: "all", label: "All people" },
    { key: "fit", label: "ICP fit" },
    { key: "new", label: "Not connected yet" },
  ];
  const SORTS = {
    name: (a, b) => a.name.localeCompare(b.name),
    fit: (a, b) => fitOf(a) - fitOf(b),
    touch: (a, b) => touchOf(a) - touchOf(b),
  };
  const ARROW = '<svg aria-hidden="true" viewBox="0 0 8 10"><path d="M4 1v8M1.2 6.2 4 9l2.8-2.8" /></svg>';
  const OUT = '<svg aria-hidden="true" viewBox="0 0 10 10"><path d="M3 2h5v5M8 2 2.5 7.5" /></svg>';
  const CLOSE = '<svg aria-hidden="true" viewBox="0 0 14 14"><path d="M3 3l8 8M11 3l-8 8" /></svg>';

  let view = null;
  let hover = null;

  const escape = (value) => String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const field = (person, key) => person.fields?.[key] || null;
  const fitOf = (person) => {
    const value = field(person, "icp_fit")?.value;
    return typeof value === "number" ? value : -1;
  };
  const touchOf = (person) => (person.last_touch ? Date.parse(person.last_touch.at) : 0);

  function day(value) {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return "";
    const label = `${MONTHS[date.getMonth()]} ${date.getDate()}`;
    return date.getFullYear() === new Date().getFullYear() ? label : `${label}, ${date.getFullYear()}`;
  }

  // "ICP 1: founders who need growth done" reads as "ICP 1" beside a score.
  function icpShort(text) {
    if (!text) return "";
    if (text === "none") return "no ICP";
    const numbered = text.match(/^(ICP\s*\d+)\s*[:–—-]/i);
    if (numbered) return numbered[1];
    return text.length > 22 ? `${text.slice(0, 21)}…` : text;
  }

  function icpText(value) {
    if (!value) return { text: "—", muted: true };
    if (value === "none") return { text: "None", muted: true };
    return { text: value, muted: false };
  }

  function staleNote(value) {
    return `Scored before ${value.definition || "the ICP file"} changed. The next run rescores it.`;
  }

  function mount(main, options) {
    const fresh = !view || view.projectId !== options.projectId;
    if (fresh) {
      close();
      view = {
        ...options, people: null, error: null, fitShown: 0.6, segment: "all", query: "",
        sort: { key: "fit", descending: true }, page: 0,
        openId: new URLSearchParams(window.location.search).get("person"),
        person: null, personError: null, confirming: false, forgetting: false, forgetError: null,
      };
    } else {
      Object.assign(view, options);
    }
    view.main = main;
    view.active = true;
    renderShell();
    load();
    if (view.openId && !document.getElementById("person-panel")) openPerson(view.openId, { focus: false });
    else renderPanel();
  }

  async function load() {
    const current = view;
    try {
      const listed = await current.api(`/api/projects/${encodeURIComponent(current.projectId)}/people`);
      if (view !== current || !current.active) return;
      current.people = listed.people;
      current.fitShown = listed.fit_shown;
      current.error = null;
    } catch (error) {
      if (view !== current || !current.active) return;
      current.error = error.message;
    }
    renderShell();
  }

  function segmentPeople(key) {
    const people = view.people || [];
    if (key === "fit") return people.filter((person) => fitOf(person) >= view.fitShown);
    if (key === "new") return people.filter((person) => field(person, "linkedin_relationship")?.value === "none");
    return people;
  }

  function shown() {
    const query = view.query.trim().toLowerCase();
    const people = segmentPeople(view.segment).filter((person) => !query ||
      [person.name, person.headline, field(person, "icp")?.value].some((text) => (text || "").toLowerCase().includes(query)));
    const compare = SORTS[view.sort.key];
    return [...people].sort((a, b) => {
      const order = view.sort.descending ? compare(b, a) : compare(a, b);
      return order || a.name.localeCompare(b.name);
    });
  }

  function renderShell() {
    const main = view.main;
    if (!main.querySelector(".people-view")) {
      main.innerHTML = `<section class="product-view workspace-view people-view">
        <header class="workspace-header system-header">
          <h1>People</h1>
          <span class="header-spacer"></span>
          <div class="search-field is-registry">
            <svg aria-hidden="true" viewBox="0 0 13 13"><circle cx="5.5" cy="5.5" r="4" /><path d="M8.5 8.5L12 12" /></svg>
            <input id="people-search" type="search" aria-label="Search people" placeholder="Search people…" />
            <button class="search-clear" type="button" data-clear-people-search aria-label="Clear search" hidden>✕</button>
          </div>
        </header>
        <div class="people-body"></div>
      </section>`;
      const search = main.querySelector("#people-search");
      search.value = view.query;
      search.addEventListener("input", () => {
        view.query = search.value;
        view.page = 0;
        syncSearch();
        renderBody();
      });
      main.querySelector("[data-clear-people-search]").addEventListener("click", () => {
        view.query = "";
        search.value = "";
        view.page = 0;
        syncSearch();
        renderBody();
        search.focus();
      });
    }
    syncSearch();
    renderBody();
  }

  function syncSearch() {
    const box = view.main.querySelector(".people-view .search-field");
    if (!box) return;
    box.hidden = !view.people?.length;
    box.classList.toggle("is-active", Boolean(view.query));
    box.querySelector("[data-clear-people-search]").hidden = !view.query;
  }

  function renderBody() {
    const body = view.main.querySelector(".people-body");
    if (!body) return;
    hideHover();
    if (view.error && !view.people) {
      body.innerHTML = `<div class="decisions-empty"><strong>Tin couldn't load people.</strong><span>${escape(view.error)}</span></div>`;
      return;
    }
    if (!view.people) {
      body.innerHTML = '<div class="view-loading">Loading people…</div>';
      return;
    }
    if (!view.people.length) {
      body.innerHTML = `<div class="decisions-empty"><strong>No people yet.</strong><span>When someone reacts to your LinkedIn posts, Tin adds them here with how well they fit your ICP.</span><button class="button-secondary" type="button" data-people-open-system>Open System</button></div>`;
      body.querySelector("[data-people-open-system]").addEventListener("click", () => view.openSystem?.());
      return;
    }
    const people = shown();
    const pages = Math.max(1, Math.ceil(people.length / PAGE));
    view.page = Math.min(view.page, pages - 1);
    const start = view.page * PAGE;
    const visible = people.slice(start, start + PAGE);
    body.innerHTML = `
      <div class="workflow-sections system-sections people-sections" role="tablist" aria-label="People segments">
        ${SEGMENTS.map((segment) => `<button class="workflow-section ${view.segment === segment.key ? "is-active" : ""}" type="button" role="tab" aria-selected="${view.segment === segment.key}" data-people-segment="${segment.key}">${segment.label} <span>${segmentPeople(segment.key).length}</span></button>`).join("")}
      </div>
      <div class="people-grid">
        <table class="tin-table people-table">
          <thead><tr>
            ${header("name", "Name")}
            <th class="is-headline" scope="col">Headline</th>
            <th class="is-icp" scope="col">ICP</th>
            ${header("fit", "ICP fit")}
            <th class="is-linkedin" scope="col">LinkedIn</th>
            ${header("touch", "Last touch")}
          </tr></thead>
          <tbody>${visible.length ? visible.map(row).join("") : `<tr class="is-none"><td colspan="6">${view.query.trim() ? `No one matches “${escape(view.query.trim())}”.` : "No one here yet."}</td></tr>`}</tbody>
        </table>
      </div>
      <footer class="people-pager">
        <code>${people.length ? `${start + 1}–${start + visible.length} of ${people.length}` : "0 of 0"}</code>
        <span></span>
        ${pages > 1 ? `<div>
          <button type="button" data-people-page="-1" aria-label="Previous page" ${view.page === 0 ? "disabled" : ""}><svg aria-hidden="true" viewBox="0 0 12 12"><path d="M7.5 2.5 4 6l3.5 3.5" /></svg></button>
          <button type="button" data-people-page="1" aria-label="Next page" ${view.page >= pages - 1 ? "disabled" : ""}><svg aria-hidden="true" viewBox="0 0 12 12"><path d="M4.5 2.5 8 6l-3.5 3.5" /></svg></button>
        </div>` : ""}
      </footer>`;
    bindBody(body);
  }

  function header(key, label) {
    const active = view.sort.key === key;
    const sort = active ? (view.sort.descending ? "descending" : "ascending") : "none";
    return `<th class="is-${key} is-sortable" scope="col" aria-sort="${sort}">
      <button type="button" data-people-sort="${key}" class="${active ? "is-active" : ""} ${active && !view.sort.descending ? "is-ascending" : ""}">${label}${active ? ARROW : ""}</button>
    </th>`;
  }

  function row(person) {
    const icp = field(person, "icp");
    const fit = field(person, "icp_fit");
    const relationship = field(person, "linkedin_relationship")?.value;
    const icpLabel = icpText(icp?.value);
    const fitValue = typeof fit?.value === "number" ? fit.value : null;
    const fitClass = fitValue === null || fit.stale ? "is-muted" : fitValue >= view.fitShown ? "" : "is-secondary";
    const touch = person.last_touch;
    return `<tr tabindex="0" data-person="${escape(person.id)}" class="${person.id === view.openId ? "is-selected" : ""}" aria-label="${escape(person.name || "Unnamed")}">
      <td class="is-name"><span>${escape(person.name || "Unnamed")}</span></td>
      <td class="is-headline"><span>${escape(person.headline)}</span></td>
      <td class="is-icp ${icpLabel.muted ? "is-muted" : ""}"><span>${escape(icpLabel.text)}</span></td>
      <td class="is-fit ${fitClass}" ${fit ? `data-fit="${escape(person.id)}"` : ""}>${fit?.stale && fitValue !== null ? "<small>old</small>" : ""}<span>${fitValue === null ? "—" : fitValue.toFixed(2)}</span></td>
      <td class="is-linkedin"><span>${escape(RELATIONSHIP[relationship] || "—")}</span></td>
      <td class="is-touch"><span>${touch ? `${escape(day(touch.at))} · ${escape(touch.kind)}` : "—"}</span></td>
    </tr>`;
  }

  function bindBody(body) {
    body.querySelectorAll("[data-people-segment]").forEach((button) => button.addEventListener("click", () => {
      view.segment = button.dataset.peopleSegment;
      view.page = 0;
      renderBody();
    }));
    body.querySelectorAll("[data-people-sort]").forEach((button) => button.addEventListener("click", () => {
      const key = button.dataset.peopleSort;
      view.sort = view.sort.key === key ? { key, descending: !view.sort.descending } : { key, descending: key !== "name" };
      view.page = 0;
      renderBody();
    }));
    body.querySelectorAll("[data-people-page]").forEach((button) => button.addEventListener("click", () => {
      view.page += Number(button.dataset.peoplePage);
      renderBody();
      body.querySelector(".people-grid")?.scrollIntoView({ block: "nearest" });
    }));
    body.querySelectorAll("tbody tr[data-person]").forEach((tr) => {
      tr.addEventListener("click", () => openPerson(tr.dataset.person));
      tr.addEventListener("keydown", (event) => {
        if (event.key !== "Enter" && event.key !== " ") return;
        event.preventDefault();
        openPerson(tr.dataset.person);
      });
    });
    body.querySelectorAll("td[data-fit]").forEach((cell) => {
      cell.addEventListener("pointerenter", () => showHover(cell));
      cell.addEventListener("pointerleave", hideHover);
    });
  }

  // The reason behind a score, its lineage, and whether it's out of date (PEOPLE-A1 hover).
  function showHover(cell) {
    const person = view.people?.find((item) => item.id === cell.dataset.fit);
    const fit = person && field(person, "icp_fit");
    if (!fit) return;
    const icp = field(person, "icp");
    hover ||= Object.assign(document.createElement("div"), { className: "people-hover", role: "tooltip" });
    if (!hover.isConnected) document.body.append(hover);
    const line = [typeof fit.value === "number" ? fit.value.toFixed(2) : "", icpShort(icp?.value), day(fit.at)].filter(Boolean).join(" · ");
    hover.innerHTML = `${fit.reason ? `<p>${escape(fit.reason)}</p>` : ""}<code>${escape(line)}</code>${fit.stale ? `<small>${escape(staleNote(fit))}</small>` : ""}`;
    // Under the score, its right edge on the cell's.
    const rect = cell.getBoundingClientRect();
    hover.style.left = `${Math.max(16, rect.right - 300)}px`;
    hover.style.top = `${rect.bottom - 4}px`;
    hover.classList.add("is-visible");
  }

  function hideHover() {
    hover?.classList.remove("is-visible");
  }

  function setPersonParam(id) {
    const url = new URL(window.location.href);
    if (id) url.searchParams.set("person", id);
    else url.searchParams.delete("person");
    window.history.replaceState(null, "", `${url.pathname}${url.search}`);
  }

  async function openPerson(id, { focus = true } = {}) {
    const current = view;
    const switching = current.openId !== id;
    current.openId = id;
    current.confirming = false;
    current.forgetError = null;
    if (switching || !current.person || current.person.id !== id) {
      current.person = current.people?.find((item) => item.id === id) || null;
      current.personError = null;
    }
    setPersonParam(id);
    renderPanel();
    syncSelection();
    if (focus) document.getElementById("person-panel")?.focus({ preventScroll: true });
    try {
      const person = await current.api(`/api/projects/${encodeURIComponent(current.projectId)}/people/${encodeURIComponent(id)}`);
      if (view !== current || !current.active || current.openId !== id) return;
      current.person = person;
    } catch (error) {
      if (view !== current || !current.active || current.openId !== id) return;
      current.personError = error.message;
    }
    renderPanel();
  }

  function closePerson({ restoreFocus = true } = {}) {
    if (!view?.openId) return;
    const id = view.openId;
    view.openId = null;
    view.person = null;
    view.confirming = false;
    setPersonParam(null);
    renderPanel();
    syncSelection();
    if (restoreFocus) view.main.querySelector(`tr[data-person="${CSS.escape(id)}"]`)?.focus({ preventScroll: true });
  }

  function syncSelection() {
    view.main.querySelectorAll("tbody tr[data-person]").forEach((tr) => tr.classList.toggle("is-selected", tr.dataset.person === view.openId));
  }

  function fieldRow(label, value, lineage, extra = "") {
    return `<div class="person-field">
      <div class="person-field-line"><span>${label}</span>${value}<code>${escape(lineage)}</code></div>
      ${extra}
    </div>`;
  }

  function lineage(value) {
    return [value.by, day(value.at)].filter(Boolean).join(" · ");
  }

  function fieldsHtml(person) {
    const rows = [];
    const icp = field(person, "icp");
    const fit = field(person, "icp_fit");
    const relationship = field(person, "linkedin_relationship");
    if (icp) {
      const label = icpText(icp.value);
      rows.push(fieldRow("ICP", `<strong class="${label.muted ? "is-muted" : ""}">${escape(label.text)}</strong>`, lineage(icp)));
    }
    if (fit) {
      const number = typeof fit.value === "number" ? fit.value.toFixed(2) : "—";
      const value = `<strong class="is-mono ${fit.stale || fit.value === null ? "is-muted" : ""}">${fit.stale && fit.value !== null ? "<small>old</small> " : ""}${number}</strong>`;
      const notes = [fit.reason ? `<p>${escape(fit.reason)}</p>` : "", fit.stale ? `<p>${escape(staleNote(fit))}</p>` : ""].join("");
      rows.push(fieldRow("ICP fit", value, lineage(fit), notes ? `<div class="person-field-notes">${notes}</div>` : ""));
    }
    if (relationship) {
      rows.push(fieldRow("LinkedIn", `<strong>${escape(RELATIONSHIP[relationship.value] || "—")}</strong>`, lineage(relationship)));
    }
    if (!rows.length) return "";
    return `<section class="person-section"><h3>Fields <span>${rows.length}</span></h3>${rows.join("")}</section>`;
  }

  function eventText(event) {
    const whose = event.yours === true ? "your post" : event.yours === false ? "a teammate’s post" : "a post";
    if (event.kind === "reacted") {
      const reaction = REACTIONS[event.reaction];
      return `Reacted to ${whose}${reaction ? ` with ${reaction}` : ""}`;
    }
    if (event.kind === "commented") return `Commented on ${whose}`;
    if (event.kind === "invited") return "Invited to connect";
    if (event.kind === "accepted") return "Accepted the invitation";
    if (event.kind === "withdrawn") return "Invitation withdrawn";
    return event.kind;
  }

  function timelineHtml(person) {
    if (!person.events) return view.personError ? "" : '<section class="person-section"><h3>Timeline</h3><p class="person-quiet">Loading…</p></section>';
    if (!person.events.length) return "";
    const rows = person.events.map((event) => {
      const content = `<code>${escape(day(event.at))}</code><span>${escape(eventText(event))}</span>`;
      return event.post_url
        ? `<a class="person-event" href="${escape(event.post_url)}" target="_blank" rel="noopener noreferrer">${content}${OUT}</a>`
        : `<div class="person-event">${content}</div>`;
    }).join("");
    return `<section class="person-section"><h3>Timeline <span>${person.events.length}</span></h3>${rows}</section>`;
  }

  function footerHtml(person) {
    if (view.confirming) {
      const name = person.name || "this person";
      const files = person.added?.by === "engagers" ? " The list in Files drops them at the next run." : "";
      return `<footer class="person-forget">
        <div>
          <strong>Forget ${escape(name)}?</strong>
          <p>Tin deletes this person’s fields and timeline in ${escape(view.projectName || "this project")} and won’t add them again, even when they react to a later post.${files}</p>
          ${view.forgetError ? `<p class="person-forget-error" role="alert">${escape(view.forgetError)}</p>` : ""}
        </div>
        <div class="person-forget-actions">
          <button type="button" data-person-cancel ${view.forgetting ? "disabled" : ""}>Cancel</button>
          <button class="person-forget-confirm" type="button" data-person-confirm ${view.forgetting ? "disabled" : ""}>${view.forgetting ? "Forgetting…" : "Forget"}</button>
        </div>
      </footer>`;
    }
    const added = person.added ? `added ${day(person.added.at)} by ${person.added.by}` : "";
    return `<footer><code>${escape(added)}</code><button class="person-forget-start" type="button" data-person-forget>Forget this person</button></footer>`;
  }

  function renderPanel() {
    let panel = document.getElementById("person-panel");
    if (!view?.openId) {
      panel?.remove();
      document.body.classList.remove("has-person-panel");
      return;
    }
    const person = view.person;
    if (!panel) {
      panel = document.createElement("aside");
      panel.id = "person-panel";
      panel.className = "person-panel";
      panel.tabIndex = -1;
      panel.setAttribute("aria-labelledby", "person-panel-name");
      panel.addEventListener("keydown", (event) => {
        if (event.key === "Escape") closePerson();
      });
      document.body.append(panel);
    }
    document.body.classList.add("has-person-panel");
    if (!person) {
      panel.innerHTML = `<header><div class="person-panel-title"><h2 id="person-panel-name">${view.personError ? "Not found" : "Loading…"}</h2><button class="diagram-panel-close" type="button" data-close-person aria-label="Close this person">${CLOSE}</button></div>
        ${view.personError ? `<p>${escape(view.personError)}</p>` : ""}</header>`;
    } else {
      const body = [fieldsHtml(person), timelineHtml(person)].join("");
      panel.innerHTML = `<header>
          <div class="person-panel-title"><h2 id="person-panel-name">${escape(person.name || "Unnamed")}</h2><button class="diagram-panel-close" type="button" data-close-person aria-label="Close this person">${CLOSE}</button></div>
          ${person.headline ? `<p>${escape(person.headline)}</p>` : ""}
          ${person.profile_url ? `<a class="person-panel-linkedin" href="${escape(person.profile_url)}" target="_blank" rel="noopener noreferrer">Open on LinkedIn${OUT}</a>` : ""}
        </header>
        <div class="person-panel-body">${body}${view.personError ? `<p class="person-quiet">${escape(view.personError)}</p>` : ""}</div>
        ${footerHtml(person)}`;
    }
    panel.querySelector("[data-close-person]").addEventListener("click", () => closePerson());
    panel.querySelector("[data-person-forget]")?.addEventListener("click", () => {
      view.confirming = true;
      view.forgetError = null;
      renderPanel();
      panel.querySelector("[data-person-cancel]")?.focus();
    });
    panel.querySelector("[data-person-cancel]")?.addEventListener("click", () => {
      view.confirming = false;
      view.forgetError = null;
      renderPanel();
      panel.querySelector("[data-person-forget]")?.focus();
    });
    panel.querySelector("[data-person-confirm]")?.addEventListener("click", () => forget(person));
  }

  async function forget(person) {
    const current = view;
    current.forgetting = true;
    current.forgetError = null;
    renderPanel();
    try {
      await current.api(`/api/projects/${encodeURIComponent(current.projectId)}/people/${encodeURIComponent(person.id)}`, { method: "DELETE" });
    } catch (error) {
      if (view !== current) return;
      current.forgetting = false;
      current.forgetError = error.message;
      if (current.active) renderPanel();
      return;
    }
    if (view !== current) return;
    current.forgetting = false;
    current.people = (current.people || []).filter((item) => item.id !== person.id);
    current.toast?.(`Forgot ${person.name || "this person"}.`);
    if (!current.active) return;
    closePerson({ restoreFocus: false });
    renderBody();
  }

  // Leaving the view: the open person, the panel and the hover card go with it.
  function close() {
    hideHover();
    if (view) Object.assign(view, { active: false, openId: null, person: null, personError: null, confirming: false });
    document.getElementById("person-panel")?.remove();
    document.body.classList.remove("has-person-panel");
  }

  window.addEventListener("scroll", hideHover, { passive: true });

  return { mount, close };
})();
