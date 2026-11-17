/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/. */

/* Grouping the destination list under the reader's own headings.

   Pure on purpose: given the folders the client reports and the arrangement
   carried in menu-map.js, it returns an ordered list of [heading, folders].

   A folder the arrangement does not name takes the heading of its nearest named
   ancestor, so a matter created under "matters - active" is Professional the
   moment it exists, without rebuilding anything. Only a folder with no named
   ancestor anywhere above it falls into the last group, so nothing is lost. */

"use strict";

function headingFor(path, map) {
  if (!map) return null;
  if (Object.prototype.hasOwnProperty.call(map, path)) return map[path];
  let parent = path;
  while (parent.includes(" / ")) {
    parent = parent.slice(0, parent.lastIndexOf(" / "));
    if (Object.prototype.hasOwnProperty.call(map, parent)) return map[parent];
  }
  return null;
}

function groupFolders(rows, menu) {
  const order = (menu && menu.headings) ? [...menu.headings] : [];
  order.push("Everything else");

  const buckets = new Map(order.map((name) => [name, []]));
  for (const row of rows) {
    const named = headingFor(row.path, menu && menu.map);
    const heading = buckets.has(named) ? named : "Everything else";
    buckets.get(heading).push(row);
  }
  return order
    .map((name) => [name, buckets.get(name)])
    .filter(([, items]) => items.length > 0);
}

if (typeof module !== "undefined") module.exports = { groupFolders, headingFor };
