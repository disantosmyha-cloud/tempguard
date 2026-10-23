import assert from "node:assert/strict";
import test from "node:test";

import { asConfig } from "../lib/index.js";

test("defaults are loopback and project-local", () => {
  const config = asConfig({});
  assert.equal(config.projectDir, "D:\\PythonStudy\\tempguard");
  assert.equal(config.alertdUrl, "http://127.0.0.1:8765/alert");
  assert.equal(config.alertdToken, "");
});

test("explicit config wins", () => {
  const config = asConfig({
    projectDir: "D:\\tmp\\tg",
    alertdUrl: "http://127.0.0.1:9999/alert",
    alertdToken: "x",
  });
  assert.equal(config.projectDir, "D:\\tmp\\tg");
  assert.equal(config.alertdUrl, "http://127.0.0.1:9999/alert");
  assert.equal(config.alertdToken, "x");
});
