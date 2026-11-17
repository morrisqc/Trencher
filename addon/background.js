/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/. */

/* Trencher prototype — background script.
 *
 * Two jobs: keep the panel's small state (the last folder filed into), and —
 * while we are still testing on a sandbox profile — run one self-test at install
 * time so that the API calls can be verified without clicking anything.
 */

"use strict";

const LAST_KEY = "lastDestination";

async function allFolders() {
  const accounts = await messenger.accounts.list();
  const out = [];
  async function walk(folder) {
    out.push(folder);
    const kids = await messenger.folders.getSubFolders(folder.id);
    for (const kid of kids) await walk(kid);
  }
  for (const account of accounts) {
    if (account.rootFolder) await walk(account.rootFolder);
  }
  return out;
}

async function inboxOf(folders) {
  return folders.find((f) => /^inbox$/i.test(f.name)) || null;
}

/* ── the sandbox self-test ─────────────────────────────────────────────────── */

async function selfTest() {
  const report = { ran: new Date().toISOString(), steps: [] };
  const step = (name, ok, detail) => report.steps.push({ name, ok, detail });

  try {
    const folders = await allFolders();
    step("list folders", true, folders.map((f) => f.name).slice(0, 12));

    const inbox = await inboxOf(folders);
    step("find Inbox", !!inbox, inbox && inbox.name);
    if (!inbox) throw new Error("no Inbox in the sandbox account");

    const messages = await messenger.messages.list(inbox.id);
    step("list messages", messages.length > 0, messages.map((m) => m.subject));

    const localRoot = folders.find((f) => /local folders/i.test(f.name));
    step("find account root", !!localRoot, localRoot && localRoot.name);

    let created = null;
    try {
      created = await messenger.folders.create(localRoot.id, "Trencher Test");
      step("create folder", true, created.name);
    } catch (err) {
      step("create folder", false, String(err));
    }

    if (created && messages.length) {
      await messenger.messages.move([messages[0].id], created.id);
      step("move message", true, messages[0].subject);
    }

    if (messages.length > 1) {
      await messenger.messages.update(messages[1].id, { junk: true });
      step("mark junk", true, messages[1].subject);
    }

    const after = await messenger.messages.list(created.id);
    step("verify move", after.length === 1, after.map((m) => m.subject));

    const flagged = await messenger.messages.query({ junk: true });
    step("verify junk flag", flagged.messages.length > 0,
         flagged.messages.map((m) => m.subject));
  } catch (err) {
    step("fatal", false, String(err));
  }

  await messenger.storage.local.set({ selfTest: report });
  console.log("Trencher self-test:", JSON.stringify(report, null, 1));
  return report;
}

/* load evidence + a self-test that does not wait for an install event */
(async () => {
  try {
    await messenger.storage.local.set({ loadedAt: Date.now() });
    const done = await messenger.storage.local.get("selfTestDone");
    if (!done.selfTestDone) {
      await messenger.storage.local.set({ selfTestDone: true });
      await selfTest();
    }
  } catch (err) {
    console.error("Trencher start-up failed:", err);
  }
})();

messenger.runtime.onInstalled.addListener(async () => {
  const done = await messenger.storage.local.get("selfTestDone");
  if (!done.selfTestDone && messenger.messages) {
    await messenger.storage.local.set({ selfTestDone: true });
    await selfTest();
  }
});
