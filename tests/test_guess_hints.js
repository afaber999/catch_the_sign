"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const element = { addEventListener() {} };
const context = vm.createContext({
  document: { getElementById: () => element },
  fetch: () => new Promise(() => {}),
});
const source = fs.readFileSync(
  path.join(__dirname, "..", "callsign_trainer", "web", "app.js"), "utf8"
);
vm.runInContext(source, context);
const scoreGuess = vm.runInContext("scoreGuess", context);
const statuses = (guess, answer) => Array.from(scoreGuess(guess, answer), (item) => item.status);

test("marks exact, misplaced and absent letters and digits", () => {
  assert.deepEqual(statuses("A2C", "A1B"), ["exact", "absent", "absent"]);
  assert.deepEqual(statuses("1AB", "A1B"), ["present", "present", "exact"]);
});

test("exact matches take priority over repeated characters elsewhere", () => {
  assert.deepEqual(statuses("AAA", "BAA"), ["absent", "exact", "exact"]);
  assert.deepEqual(statuses("BAAA", "AABC"), ["present", "exact", "present", "absent"]);
});

test("extra occurrences and missing or extra positions are handled", () => {
  assert.deepEqual(statuses("AAAA", "AABC"), ["exact", "exact", "absent", "absent"]);
  assert.deepEqual(statuses("A", "A1B"), ["exact"]);
  assert.deepEqual(statuses("A1BC", "A1B"), ["exact", "exact", "exact", "absent"]);
});
