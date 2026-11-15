"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

function setup() {
  const elements = {};
  const handlers = {};
  const document = {
    getElementById(id) {
      if (!elements[id]) {
        elements[id] = {
          disabled: false,
          addEventListener() {},
          requestSubmit() { this.submissions = (this.submissions || 0) + 1; },
          click() { this.clicks = (this.clicks || 0) + 1; },
          closest() { return this; },
        };
      }
      return elements[id];
    },
    addEventListener(name, handler) { handlers[name] = handler; },
  };
  const context = vm.createContext({ document, fetch: () => new Promise(() => {}), plays: 0 });
  for (const id of ["answer", "level-select", "random-mode"]) document.getElementById(id);
  const source = fs.readFileSync(
    path.join(__dirname, "..", "callsign_trainer", "web", "app.js"), "utf8"
  );
  vm.runInContext(source, context);
  vm.runInContext('state.phase = "exercise"; state.current = {}; playCurrent = () => { plays++; };', context);
  const body = { closest: () => null };
  function key(keyName, target = body, options = {}) {
    const event = {
      key: keyName, target, prevented: false,
      preventDefault() { this.prevented = true; },
      ...options,
    };
    handlers.keydown(event);
    return event;
  }
  return { elements, context, key, body };
}

test("up arrow replays from the answer field and prevents cursor movement", () => {
  const { elements, context, key } = setup();
  const event = key("ArrowUp", elements.answer);
  assert.equal(context.plays, 1);
  assert.equal(event.prevented, true);
  elements.play.disabled = true;
  key("ArrowUp", elements.answer);
  assert.equal(context.plays, 1);
});

test("enter submits outside controls without duplicating native form submission", () => {
  const { elements, key } = setup();
  assert.equal(key("Enter").prevented, true);
  assert.equal(elements["answer-form"].submissions, 1);
  assert.equal(key("Enter", elements.answer).prevented, false);
  assert.equal(elements["answer-form"].submissions, 1);
});

test("settings, modifiers, composition and repeated keys are left alone", () => {
  const { elements, context, key } = setup();
  for (const options of [
    { ctrlKey: true }, { shiftKey: true }, { altKey: true }, { metaKey: true },
    { isComposing: true }, { repeat: true }, { defaultPrevented: true },
  ]) {
    assert.equal(key("ArrowUp", elements.answer, options).prevented, false);
  }
  assert.equal(key("ArrowUp", elements["level-select"]).prevented, false);
  assert.equal(key("Enter", elements["random-mode"]).prevented, false);
  assert.equal(context.plays, 0);
  assert.equal(elements["answer-form"].submissions, undefined);
});

test("enter advances results without overriding focused buttons", () => {
  const { elements, context, key } = setup();
  vm.runInContext('state.phase = "success"', context);
  assert.equal(key("Enter").prevented, true);
  assert.equal(elements.next.clicks, 1);
  assert.equal(key("Enter", elements.next).prevented, false);
  vm.runInContext('state.phase = "complete"', context);
  assert.equal(key("Enter").prevented, true);
  assert.equal(elements.again.clicks, 1);
});
