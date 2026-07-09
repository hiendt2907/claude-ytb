import { test, expect } from "@playwright/test";
import { spawn } from "node:child_process";
import fs from "node:fs";
import http from "node:http";
import path from "node:path";

const REPO_ROOT = path.resolve(new URL("../..", import.meta.url).pathname);
const APP_EXECUTABLE = path.join(
  REPO_ROOT,
  "dist",
  "Video Render.app",
  "Contents",
  "MacOS",
  "Video Render"
);

let appProcess;

test.use({ actionTimeout: 10000, navigationTimeout: 30000 });

function getJSON(url) {
  return new Promise((resolve, reject) => {
    const req = http.get(url, (res) => {
      let body = "";
      res.setEncoding("utf8");
      res.on("data", (chunk) => {
        body += chunk;
      });
      res.on("end", () => {
        try {
          resolve({ status: res.statusCode || 0, body: JSON.parse(body) });
        } catch (error) {
          reject(error);
        }
      });
    });
    req.on("error", reject);
    req.setTimeout(800, () => {
      req.destroy(new Error(`Timed out requesting ${url}`));
    });
  });
}

async function discoverPackagedAppURL(timeoutMs = 45000) {
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    for (let port = 8000; port < 8020; port += 1) {
      try {
        const res = await getJSON(`http://127.0.0.1:${port}/api/edit-profiles`);
        if (res.status < 500 && Array.isArray(res.body.profiles)) {
          return `http://127.0.0.1:${port}`;
        }
      } catch {
        // Try the next port until the packaged launcher finishes booting.
      }
    }
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  throw new Error("Packaged macOS app did not expose the video-render API");
}

test.afterEach(() => {
  if (appProcess && !appProcess.killed) {
    appProcess.kill("SIGTERM");
  }
});

test("packaged macOS app launches and serves the end-user UI", async ({ page }) => {
  test.skip(process.platform !== "darwin", "macOS app smoke test only runs on macOS");
  test.skip(!fs.existsSync(APP_EXECUTABLE), "dist/Video Render.app has not been built");

  appProcess = spawn(APP_EXECUTABLE, [], {
    cwd: REPO_ROOT,
    stdio: ["ignore", "ignore", "ignore"],
  });

  const baseURL = await discoverPackagedAppURL();
  await page.goto(baseURL);
  await expect(page.locator("h1")).toContainText("Dựng video bán hàng từ clip có sẵn");
  await expect(page.locator("#pickScenesBtn")).toBeVisible();
});
