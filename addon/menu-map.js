/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/. */

/* The arrangement of the destination list: each folder path mapped to one of
   the headings.

   THIS IS AN EXAMPLE. The paths below are illustrative only. To use the add-on
   against your own folders, generate this file from your own arrangement with
   tools/make_menu_map.py, or edit the map by hand.

   Rules the grouping code applies:
     - a folder named here sits under the heading given;
     - a folder not named here takes the heading of its nearest named ancestor;
     - a folder with no named ancestor falls into "Everything else".
   Nothing is ever hidden: a folder the arrangement does not mention still
   appears, so the list remains usable while you build it up.

   Paths are written as the parent chain joined by " / ". */

const TRENCHER_MENU = {
  headings: ["Urgent", "Professional", "Administrative", "Personal", "Agentic"],
  map: {
    "!!urgent": "Urgent",
    "!priority": "Urgent",

    "matters - active": "Professional",
    "matters - active / Example v Example": "Professional",
    "matters - active / Example v Example / Pleadings": "Professional",
    "clients / Example Pty Ltd": "Professional",

    "financial": "Administrative",
    "financial / BAS": "Administrative",
    "insurance": "Administrative",
    "library": "Administrative",

    "family": "Personal",
    "household": "Personal",

    "Agentic": "Agentic",
    "Agentic / triage bays": "Agentic"
  }
};
