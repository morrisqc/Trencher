/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/. */

/* Trencher prototype — the panel.
 *
 * Five decisions, each one call into the client's own API, so the client keeps
 * ownership of the store and every flag survives.
 */

"use strict";

const LAST_KEY = "lastDestination";
const SKIP = /^(trash|junk|deleted items|bin)$/i;

let state = { message: null, folders: [], last: null };

const $ = (id) => document.getElementById(id);
const status = (text) => { $("status").textContent = text || ""; };

async function currentMessage() {
  const [tab] = await messenger.tabs.query({ active: true, currentWindow: true });
  const messages = await messenger.messageDisplay.getDisplayedMessages(tab.id);
  return messages && messages.length ? messages[0] : null;
}

async function collectFolders() {
  const accounts = await messenger.accounts.list();
  const out = [];
  async function walk(folder, path) {
    const label = path ? `${path} / ${folder.name}` : folder.name;
    out.push({ id: folder.id, name: folder.name, path: label, account: folder.accountId });
    for (const kid of await messenger.folders.getSubFolders(folder.id)) {
      await walk(kid, label);
    }
  }
  for (const account of accounts) {
    if (!account.rootFolder) continue;
    // the account's own root is a container, never a destination
    for (const child of await messenger.folders.getSubFolders(account.rootFolder.id)) {
      await walk(child, "");
    }
  }
  return out;
}

/* ── the five decisions ───────────────────────────────────────────────────── */

async function act(name) {
  const message = state.message;
  if (!message) { status("No message selected."); return; }

  if (name === "stay") {
    await messenger.messages.update(message.id, { read: true });
    status("Left where it is.");
    window.close();
    return;
  }

  if (name === "move") { showPanel("movePanel"); return; }
  if (name === "new") { showPanel("newPanel"); return; }

  if (name === "trash") {
    await messenger.messages.delete([message.id], false);
    status("Deleted.");
    window.close();
    return;
  }

  if (name === "spam") {
    await messenger.messages.update(message.id, { junk: true });
    status("Marked as spam; the client's own filter learns from it.");
    window.close();
  }
}

/* ── the destination list ─────────────────────────────────────────────────── */

function renderFolders(needle) {
  const list = $("folderList");
  list.textContent = "";
  const lower = (needle || "").trim().toLowerCase();
  const rows = state.folders
    .filter((f) => !SKIP.test(f.name))
    .filter((f) => !lower || f.path.toLowerCase().includes(lower))
    .sort((a, b) => {
      if (a.path === state.last) return -1;
      if (b.path === state.last) return 1;
      return a.path.localeCompare(b.path, undefined, { sensitivity: "base" });
    });

  const arrangement = typeof TRENCHER_MENU !== "undefined" ? TRENCHER_MENU : null;
  for (const [heading, items] of groupFolders(rows, arrangement)) {
    const header = document.createElement("li");
    header.className = "group";
    header.textContent = heading;
    list.append(header);

    for (const folder of items) {
      const li = document.createElement("li");
      const button = document.createElement("button");
      const name = document.createElement("span");
      name.textContent = folder.name;
      const path = document.createElement("span");
      path.className = "path";
      const parent = folder.path.slice(0, folder.path.length - folder.name.length)
        .replace(/\s*\/\s*$/, "");
      path.textContent = parent ? `  ·  ${parent}` : "";
      if (folder.path === state.last) path.textContent = "  ·  last used";
      button.append(name, path);
      button.addEventListener("click", () => fileInto(folder));
      li.append(button);
      list.append(li);
    }
  }
  if (!rows.length) status("Nothing matches that.");
}

async function fileInto(folder) {
  try {
    await messenger.messages.move([state.message.id], folder.id);
    await messenger.storage.local.set({ [LAST_KEY]: folder.path });
    status(`Filed in ${folder.path}.`);
    window.close();
  } catch (err) {
    status(`Could not move it: ${err.message}`);
  }
}

/* ── making a folder ──────────────────────────────────────────────────────── */

function renderParents() {
  const select = $("newParent");
  select.textContent = "";
  for (const folder of state.folders
         .filter((f) => !SKIP.test(f.name))
         .sort((a, b) => a.path.localeCompare(b.path, undefined, { sensitivity: "base" }))) {
    const option = document.createElement("option");
    option.value = folder.id;
    option.textContent = folder.path;
    select.append(option);
  }
}

async function createAndFile() {
  const name = $("newName").value.trim();
  if (!name) { status("Type a name first."); return; }
  if (name.includes("/")) { status("A slash would split the name. Use a plain name."); return; }
  try {
    const folder = await messenger.folders.create($("newParent").value, name);
    await messenger.messages.move([state.message.id], folder.id);
    await messenger.storage.local.set({ [LAST_KEY]: folder.path });
    status(`Made ${folder.path} and filed the letter there.`);
    window.close();
  } catch (err) {
    status(`Could not create it: ${err.message}`);
  }
}

/* ── wiring ───────────────────────────────────────────────────────────────── */

function showPanel(id) {
  for (const panel of ["movePanel", "newPanel"]) $(panel).hidden = panel !== id;
  $("decisions").hidden = id !== null;
  if (id === "movePanel") { renderFolders($("search").value); $("search").focus(); }
  if (id === "newPanel") { renderParents(); $("newName").focus(); }
}

async function start() {
  state.message = await currentMessage();
  if (!state.message) { status("Open a message first."); return; }
  $("subtitle").textContent =
    `${state.message.author} — ${state.message.subject}`.slice(0, 90);

  state.folders = await collectFolders();
  const stored = await messenger.storage.local.get(LAST_KEY);
  state.last = stored[LAST_KEY] || null;

  for (const tile of document.querySelectorAll(".tile")) {
    tile.addEventListener("click", () => act(tile.dataset.action));
  }
  for (const back of document.querySelectorAll("[data-close]")) {
    back.addEventListener("click", () => {
      for (const panel of ["movePanel", "newPanel"]) $(panel).hidden = true;
      $("decisions").hidden = false;
    });
  }
  $("search").addEventListener("input", (e) => renderFolders(e.target.value));
  $("createBtn").addEventListener("click", createAndFile);
  $("newName").addEventListener("keydown", (e) => { if (e.key === "Enter") createAndFile(); });
}

start().catch((err) => status(`Trencher: ${err.message}`));
