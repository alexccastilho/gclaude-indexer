/* GClaude Indexer - document collection indexer
   Copyright (C) 2026  Alex Camacho Castilho
   This program is free software: you can redistribute it and/or modify it
   under the terms of the GNU General Public License as published by the
   Free Software Foundation, either version 3 of the License, or (at your
   option) any later version. See the LICENSE file for details.

   The command palette of the workspace layout. Ctrl+K (or Cmd+K,
   or the "Search or run" button) opens it; typing filters; arrows choose;
   Enter opens; Esc closes and gives the focus back. */
(function () {
  "use strict";
  var dialog = document.getElementById("ws-palette");
  var scrim = document.getElementById("ws-palette-scrim");
  var input = document.getElementById("ws-palette-input");
  var list = document.getElementById("ws-palette-list");
  var empty = document.getElementById("ws-palette-empty");
  var opener = document.getElementById("ws-palette-open");
  var dataNode = document.getElementById("ws-palette-data");
  if (!dialog || !input || !list || !dataNode) return;

  var entries = [];
  try { entries = JSON.parse(dataNode.textContent) || []; } catch (error) { entries = []; }
  var shown = [];
  var selected = 0;
  var returnFocus = null;
  var MAX = 60;

  function plain(text) {
    return String(text).normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
  }
  entries.forEach(function (entry) { entry.key = plain(entry.group + " " + entry.label); });

  function matches(entry, words) {
    for (var i = 0; i < words.length; i++) {
      if (entry.key.indexOf(words[i]) < 0) return false;
    }
    return true;
  }

  function render() {
    var words = plain(input.value).split(/\s+/).filter(Boolean);
    shown = entries.filter(function (entry) { return matches(entry, words); }).slice(0, MAX);
    if (selected >= shown.length) selected = shown.length ? shown.length - 1 : 0;
    list.textContent = "";
    var lastGroup = null;
    shown.forEach(function (entry, index) {
      if (entry.group !== lastGroup) {
        var head = document.createElement("li");
        head.className = "ws-palette-group";
        head.setAttribute("role", "presentation");
        head.textContent = entry.group;
        list.appendChild(head);
        lastGroup = entry.group;
      }
      var option = document.createElement("li");
      option.id = "ws-option-" + index;
      option.className = "ws-palette-option";
      option.setAttribute("role", "option");
      option.setAttribute("aria-selected", index === selected ? "true" : "false");
      option.textContent = entry.label;
      if (entry.current) option.classList.add("is-current");
      option.addEventListener("mousedown", function (event) { event.preventDefault(); });
      option.addEventListener("click", function () { selected = index; choose(); });
      option.addEventListener("mousemove", function () {
        if (selected !== index) { selected = index; highlight(); }
      });
      list.appendChild(option);
    });
    empty.hidden = shown.length > 0;
    highlight();
  }

  function highlight() {
    var options = list.querySelectorAll(".ws-palette-option");
    options.forEach(function (option, index) {
      option.setAttribute("aria-selected", index === selected ? "true" : "false");
    });
    var current = options[selected];
    if (current) {
      input.setAttribute("aria-activedescendant", current.id);
      current.scrollIntoView({ block: "nearest" });
    } else {
      input.removeAttribute("aria-activedescendant");
    }
  }

  function open() {
    if (!dialog.hidden) return;
    returnFocus = document.activeElement;
    dialog.hidden = false;
    scrim.hidden = false;
    document.documentElement.classList.add("ws-palette-open");
    input.value = "";
    selected = 0;
    render();
    input.focus();
  }

  function close() {
    if (dialog.hidden) return;
    dialog.hidden = true;
    scrim.hidden = true;
    document.documentElement.classList.remove("ws-palette-open");
    if (returnFocus && typeof returnFocus.focus === "function") returnFocus.focus();
  }

  function setPreference(entry) {
    var body = new FormData();
    body.append(entry.pref, entry.value);
    var action = "/preferences/" + entry.pref;
    if (entry.pref === "theme") {
      fetch(action, { method: "POST", credentials: "same-origin", body: body, headers: { "X-Preference-Fetch": "1" } })
        .then(function (response) {
          if (!response.ok) throw new Error(String(response.status));
          document.documentElement.setAttribute("data-theme", entry.value);
          entries.forEach(function (other) {
            if (other.pref === "theme") other.current = other.value === entry.value;
          });
          var select = document.querySelector('select[data-preference="theme"]');
          if (select) select.value = entry.value;
          close();
        })
        .catch(function () { submitForm(action, entry); });
      return;
    }
    submitForm(action, entry);
  }

  function submitForm(action, entry) {
    var form = document.createElement("form");
    form.method = "post";
    form.action = action;
    form.setAttribute("data-no-wait", "");
    var field = document.createElement("input");
    field.type = "hidden";
    field.name = entry.pref;
    field.value = entry.value;
    form.appendChild(field);
    document.body.appendChild(form);
    form.submit();
  }

  function choose() {
    var entry = shown[selected];
    if (!entry) return;
    if (entry.url) { window.location.href = entry.url; return; }
    if (entry.pref) setPreference(entry);
  }

  input.addEventListener("input", function () { selected = 0; render(); });
  input.addEventListener("keydown", function (event) {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      if (shown.length) { selected = (selected + 1) % shown.length; highlight(); }
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      if (shown.length) { selected = (selected - 1 + shown.length) % shown.length; highlight(); }
    } else if (event.key === "Home") {
      event.preventDefault(); selected = 0; highlight();
    } else if (event.key === "End") {
      event.preventDefault(); selected = Math.max(0, shown.length - 1); highlight();
    } else if (event.key === "Enter") {
      event.preventDefault(); choose();
    } else if (event.key === "Escape") {
      event.preventDefault(); close();
    } else if (event.key === "Tab") {
      // The dialog is modal and has one control: keep the focus in it.
      event.preventDefault();
    }
  });
  scrim.addEventListener("click", close);
  if (opener) opener.addEventListener("click", open);

  document.addEventListener("keydown", function (event) {
    var key = (event.key || "").toLowerCase();
    if ((event.ctrlKey || event.metaKey) && !event.altKey && key === "k") {
      event.preventDefault();
      if (dialog.hidden) open(); else close();
    }
  });
})();
