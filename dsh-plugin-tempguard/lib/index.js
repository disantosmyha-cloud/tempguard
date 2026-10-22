/** Tempguard tools for DeepSeek Harness. */
import { readFile } from "node:fs/promises";
import { join } from "node:path";
import { defineTool } from "@deepseek-ai/dsh-tools";

export const name = "tempguard";

export const inject = ["tools"];

const DEFAULT_PROJECT = "D:\\PythonStudy\\tempguard";
const DEFAULT_ALERTD = "http://127.0.0.1:8765/alert";

function asConfig(config) {
  return {
    projectDir: String(config?.projectDir || DEFAULT_PROJECT),
    alertdUrl: String(config?.alertdUrl || DEFAULT_ALERTD),
    alertdToken: String(config?.alertdToken || ""),
  };
}

async function jsonFetch(url, options = {}) {
  const response = await fetch(url, {
    ...options,
    signal: AbortSignal.timeout(5000),
  });
  const text = await response.text();
  let data;
  try {
    data = JSON.parse(text);
  } catch {
    data = { raw: text };
  }
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}: ${text.slice(0, 200)}`);
  }
  return data;
}

async function lastTemperature(projectDir) {
  const csv = await readFile(join(projectDir, "logs", "temps.csv"), "utf8");
  const lines = csv.trim().split(/\r?\n/);
  return lines.length > 1 ? lines[lines.length - 1] : "还没有温度记录";
}

export function apply(ctx, config) {
  const settings = asConfig(config);

  ctx.tools.register(
    defineTool({
      name: "tempguard_status",
      description:
        "Read the local tempguard watchdog health and the latest CPU/GPU temperature. Use when the user asks about temperature, fan, overheating, or whether the watchdog is running.",
      parameters: {},
      output: {
        schema: {
          type: "object",
          additionalProperties: false,
          properties: {
            text: { type: "string", required: true },
          },
        },
        render(_args, value) {
          return [{ type: "text", text: value.text }];
        },
      },
      async execute() {
        const health = await jsonFetch(
          new URL("/health", settings.alertdUrl).toString(),
        );
        const last = await lastTemperature(settings.projectDir);
        const channels = Array.isArray(health.channels)
          ? health.channels.join(", ") || "none"
          : "unknown";
        return {
          text: [
            `alertd: ${health.status || "unknown"}`,
            `queue: ${health.queue ?? "?"}`,
            `channels: ${channels}`,
            `latest temp: ${last}`,
          ].join("\n"),
        };
      },
    }),
  );

  ctx.tools.register(
    defineTool({
      name: "tempguard_alert",
      description:
        "Send a test or custom alert through the local tempguard alertd service to the configured WeChat/QQ/Feishu/DingTalk/email adapters.",
      parameters: {
        level: {
          type: "string",
          required: true,
          description: "INFO, WARN, or TRIP",
          enum: ["INFO", "WARN", "TRIP"],
        },
        message: {
          type: "string",
          required: true,
          description: "Alert text to send",
        },
      },
      output: {
        schema: {
          type: "object",
          additionalProperties: false,
          properties: {
            text: { type: "string", required: true },
            accepted: { type: "boolean", required: true },
          },
        },
        render(_args, value) {
          return [{ type: "text", text: value.text }];
        },
      },
      async execute(args) {
        const headers = { "Content-Type": "application/json" };
        if (settings.alertdToken) {
          headers["X-Alert-Token"] = settings.alertdToken;
        }
        const data = await jsonFetch(settings.alertdUrl, {
          method: "POST",
          headers,
          body: JSON.stringify({
            level: args.level,
            message: args.message,
            source: "dsh-plugin-tempguard",
          }),
        });
        return {
          accepted: data.status === "accepted",
          text: `alertd accepted=${data.status === "accepted"} status=${data.status}`,
        };
      },
    }),
  );
}
