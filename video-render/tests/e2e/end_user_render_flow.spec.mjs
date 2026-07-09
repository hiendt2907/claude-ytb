import { test, expect } from "@playwright/test";
import { spawn, spawnSync } from "node:child_process";
import fs from "node:fs";
import http from "node:http";
import net from "node:net";
import os from "node:os";
import path from "node:path";

const REPO_ROOT = path.resolve(new URL("../..", import.meta.url).pathname);
const DEMO_ROOT = path.join(REPO_ROOT, "demo_data");

let tmpRoot;
let baseURL;
let server;

test.use({ actionTimeout: 10000, navigationTimeout: 30000 });

function run(command, args, options = {}) {
  const result = spawnSync(command, args, {
    cwd: REPO_ROOT,
    encoding: "utf8",
    stdio: "pipe",
    ...options,
  });
  if (result.status !== 0) {
    throw new Error(
      [
        `${command} ${args.join(" ")} failed`,
        result.stdout,
        result.stderr,
      ].join("\n")
    );
  }
  return result.stdout.trim();
}

function freePort() {
  return new Promise((resolve, reject) => {
    const socket = net.createServer();
    socket.on("error", reject);
    socket.listen(0, "127.0.0.1", () => {
      const address = socket.address();
      socket.close(() => resolve(address.port));
    });
  });
}

function waitForHTTP(url, timeoutMs = 30000) {
  const started = Date.now();
  return new Promise((resolve, reject) => {
    const tick = () => {
      const req = http.get(url, (res) => {
        res.resume();
        if (res.statusCode && res.statusCode < 500) {
          resolve();
          return;
        }
        retry();
      });
      req.on("error", retry);
      req.setTimeout(1000, () => {
        req.destroy();
        retry();
      });
    };
    const retry = () => {
      if (Date.now() - started > timeoutMs) {
        reject(new Error(`Timed out waiting for ${url}`));
        return;
      }
      setTimeout(tick, 250);
    };
    tick();
  });
}

function demoFixture(root) {
  const scenesDir = path.join(DEMO_ROOT, "scenes");
  const voicePath = path.join(DEMO_ROOT, "voice_test_generated.mp3");
  const outputDir = path.join(DEMO_ROOT, "output");
  fs.mkdirSync(outputDir, { recursive: true });
  if (!fs.existsSync(path.join(scenesDir, "scene_00", "1.2.MOV"))) {
    throw new Error(`Missing demo scenes under ${scenesDir}`);
  }
  if (!fs.existsSync(voicePath)) {
    throw new Error(`Missing demo voice file: ${voicePath}`);
  }

  return {
    scenesDir,
    outputDir,
    voicePath,
    finalPath: path.join(outputDir, "e2e_user_flow", "variant_1_final.mp4"),
    previewDir: path.join(outputDir, "_preview", "e2e_user_flow_xem_thu_preview"),
    autoSmartDir: path.join(outputDir, "e2e_auto_smart"),
  };
}

async function startServer() {
  const port = await freePort();
  baseURL = `http://127.0.0.1:${port}`;
  server = spawn(
    path.join(REPO_ROOT, ".venv/bin/python"),
    [
      "-m",
      "uvicorn",
      "ytb_pipeline.webui.app:app",
      "--host",
      "127.0.0.1",
      "--port",
      String(port),
    ],
    {
      cwd: REPO_ROOT,
      env: {
        ...process.env,
        PYTHONPATH: path.join(REPO_ROOT, "src"),
      },
      stdio: ["ignore", "pipe", "pipe"],
    }
  );
  await waitForHTTP(`${baseURL}/api/edit-profiles`);
}

function escapeRegex(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

async function navigateBrowserModalTo(page, targetPath) {
  const currentPath = await page.locator("#browserPath").textContent();
  const relativePath = path.relative(currentPath, targetPath);
  const segments = relativePath.split(path.sep).filter(Boolean);
  for (const segment of segments) {
    if (segment === "..") {
      await page
        .locator("#browserList li.dir")
        .filter({ hasText: /^\.\.$/ })
        .click();
      await expect(page.locator("#browserPath")).not.toHaveText(currentPath);
      continue;
    }
    await page
      .locator("#browserList li.dir")
      .filter({ hasText: new RegExp(`^${escapeRegex(segment)}$`) })
      .click();
    await expect(page.locator("#browserPath")).toContainText(segment);
  }
  await expect(page.locator("#browserPath")).toHaveText(targetPath);
}

async function chooseDirectory(page, buttonSelector, targetPath) {
  await page.locator(buttonSelector).click();
  await expect(page.locator("#browserModal")).toBeVisible();
  await expect(page.locator("#browserPath")).toHaveText(os.homedir());
  await navigateBrowserModalTo(page, targetPath);
  await page.locator("#browserConfirmBtn").click();
  await expect(page.locator("#browserModal")).toBeHidden();
}

async function chooseFile(page, buttonSelector, filePath) {
  await page.locator(buttonSelector).click();
  await expect(page.locator("#browserModal")).toBeVisible();
  await expect(page.locator("#browserPath")).toHaveText(os.homedir());
  await navigateBrowserModalTo(page, path.dirname(filePath));
  await page
    .locator("#browserList li.file")
    .filter({ hasText: new RegExp(escapeRegex(path.basename(filePath))) })
    .click();
  await page.locator("#browserConfirmBtn").click();
  await expect(page.locator("#browserModal")).toBeHidden();
}

test.beforeAll(async () => {
  tmpRoot = fs.mkdtempSync(path.join(os.tmpdir(), "video-render-e2e-"));
  await startServer();
});

test.afterAll(async () => {
  if (server) {
    server.kill("SIGTERM");
  }
  if (tmpRoot) {
    fs.rmSync(tmpRoot, { recursive: true, force: true });
  }
});

test("end user renders, reviews, cancels one cut range, then exports final with voice", async ({ page }) => {
  test.setTimeout(300000);
  const fixture = demoFixture(tmpRoot);
  fs.rmSync(path.dirname(fixture.finalPath), { recursive: true, force: true });
  fs.rmSync(fixture.previewDir, { recursive: true, force: true });

  await page.goto(baseURL);
  await page.evaluate(() => localStorage.clear());
  await page.reload();
  await expect(page.locator("h1")).toContainText("Dựng video bán hàng từ clip có sẵn");

  await chooseDirectory(page, "#pickScenesBtn", fixture.scenesDir);
  await expect(page.locator("#scenesDirDisplay")).toContainText(fixture.scenesDir);
  await chooseFile(page, "#pickVoiceBtn", fixture.voicePath);
  await expect(page.locator("#voiceTracksDisplay")).toContainText("1 file đã chọn");
  await chooseDirectory(page, "#pickOutputBtn", fixture.outputDir);
  await expect(page.locator("#outputDirDisplay")).toContainText(fixture.outputDir);
  await page.locator("#product_name").fill("e2e_user_flow");
  await page.locator('input[name="n_outputs"]').fill("1");
  await page.locator('select[name="fit_mode"]').selectOption("pad");
  await page.locator("#trimModeSelect").selectOption("manual_review");

  await page.locator("#scanBtn").click();
  await expect(page.locator("#scanResult")).toContainText("Đang phân tích");
  await expect(page.locator("#scanResult")).toContainText("scene_00", { timeout: 30000 });
  await expect(page.locator("#scanResult")).toContainText("scene_01");
  await expect(page.locator("#scanResult")).toContainText("scene_02");

  await page.locator("summary", { hasText: "Cài đặt nâng cao" }).click();
  await page.locator('input[name="mode"][value="manual"]').check();
  await page.locator('textarea[name="manual_plan_text"]').fill("1.2, 2.3, 3.1");
  await page.locator("#checkManualPlanBtn").click();
  await expect(page.locator("#manualPlanPreview")).toContainText("Danh sách hợp lệ");

  await page.locator("#previewBtn").click();
  await expect(page.locator("#previewModal")).toBeVisible();
  await expect(page.locator("#previewStatus")).toContainText("sẵn sàng", { timeout: 120000 });
  await expect(page.locator("#previewVideo")).toBeVisible();
  await page.locator("#closePreviewBtn").click();
  await expect(page.locator("#previewModal")).toBeHidden();

  await page.locator("#submitBtn").click();
  await expect(page.locator("#confirmModal")).toBeVisible();
  await expect(page.locator("#estimateItems")).toContainText("e2e_user_flow");
  await page.locator("#confirmRenderBtn").click();

  await expect(page.locator("#outputPage")).toBeVisible({ timeout: 180000 });
  await page.reload();
  await expect(page.locator("#outputPage")).toBeVisible({ timeout: 30000 });
  const card = page.locator(".output-card").first();
  await expect(card.locator("[data-badge]")).toContainText("Bản thô, chưa có voice");
  await expect(card.getByRole("button", { name: "Review & cắt video" })).toBeVisible();

  await card.getByRole("button", { name: "Review & cắt video" }).click();
  await expect(page.locator("#cutReviewModal")).toBeVisible();
  await expect(page.locator("#cutReviewStatus")).toContainText("cắt video thô");
  await page.locator("#cutVideo").evaluate((video) => new Promise((resolve) => {
    if (video.readyState >= 1) {
      resolve();
      return;
    }
    video.addEventListener("loadedmetadata", resolve, { once: true });
  }));

  const timeline = page.locator("#cutTimeline");
  const box = await timeline.boundingBox();
  expect(box).not.toBeNull();
  const y = box.y + box.height / 2;
  await page.mouse.move(box.x + box.width * 0.18, y);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width * 0.42, y);
  await expect(page.locator("#cutDimOverlay")).toHaveClass(/active/);
  await expect(page.locator("#cutHoverTime")).toContainText("00:");
  await page.mouse.up();
  await expect(page.locator("#cutRangesText")).not.toHaveValue("");
  await expect(page.locator("#cutRangeList")).toContainText("Vùng 1");

  await page.locator(".cut-range").first().click();
  await expect(page.locator("#cutRangesText")).toHaveValue("");
  await expect(page.locator("#cutReviewStatus")).toContainText("Đã huỷ vùng cắt");

  await page.mouse.move(box.x + box.width * 0.22, y);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width * 0.36, y);
  await page.mouse.up();
  await expect(page.locator("#cutRangesText")).not.toHaveValue("");

  await page.locator("#submitCutBtn").click();
  await expect(card.locator("[data-badge]")).toContainText("Final đã có voice", { timeout: 180000 });
  await page.reload();
  await expect(page.locator("#outputPage")).toBeVisible({ timeout: 30000 });
  await expect(page.locator(".output-card").first().locator("[data-badge]")).toContainText("Final đã có voice");

  expect(fs.existsSync(fixture.finalPath)).toBe(true);
  const probe = run("ffprobe", [
    "-v",
    "error",
    "-select_streams",
    "a:0",
    "-show_entries",
    "stream=codec_type",
    "-of",
    "default=nw=1:nk=1",
    fixture.finalPath,
  ]);
  expect(probe).toContain("audio");

  fs.rmSync(path.dirname(fixture.finalPath), { recursive: true, force: true });
  fs.rmSync(fixture.previewDir, { recursive: true, force: true });
});

test("end user renders multiple auto-smart finals without opening the cutter", async ({ page }) => {
  test.setTimeout(300000);
  const fixture = demoFixture(tmpRoot);
  fs.rmSync(fixture.autoSmartDir, { recursive: true, force: true });

  await page.goto(baseURL);
  await page.evaluate(() => localStorage.clear());
  await page.reload();
  await expect(page.locator("h1")).toContainText("Dựng video bán hàng từ clip có sẵn");

  await chooseDirectory(page, "#pickScenesBtn", fixture.scenesDir);
  await chooseFile(page, "#pickVoiceBtn", fixture.voicePath);
  await chooseDirectory(page, "#pickOutputBtn", fixture.outputDir);
  await page.locator("#product_name").fill("e2e_auto_smart");
  await page.locator('input[name="n_outputs"]').fill("2");
  await page.locator('select[name="fit_mode"]').selectOption("pad");
  await page.locator("#trimModeSelect").selectOption("auto_smart");

  await page.locator("#scanBtn").click();
  await expect(page.locator("#scanResult")).toContainText("scene_00", { timeout: 30000 });

  await page.locator("#submitBtn").click();
  await expect(page.locator("#confirmModal")).toBeVisible();
  await expect(page.locator("#estimateItems")).toContainText("e2e_auto_smart");
  await page.locator("#confirmRenderBtn").click();

  await expect(page.locator("#outputPage")).toBeVisible({ timeout: 240000 });
  await expect(page.locator(".output-card")).toHaveCount(2);
  await expect(page.locator(".output-card").first().locator("[data-badge]")).toContainText("Final đã có voice");
  await page.reload();
  await expect(page.locator("#outputPage")).toBeVisible({ timeout: 30000 });
  await expect(page.locator(".output-card")).toHaveCount(2);

  for (const fileName of ["variant_1_final.mp4", "variant_2_final.mp4"]) {
    const finalPath = path.join(fixture.autoSmartDir, fileName);
    expect(fs.existsSync(finalPath)).toBe(true);
    const probe = run("ffprobe", [
      "-v",
      "error",
      "-select_streams",
      "a:0",
      "-show_entries",
      "stream=codec_type",
      "-of",
      "default=nw=1:nk=1",
      finalPath,
    ]);
    expect(probe).toContain("audio");
  }

  fs.rmSync(fixture.autoSmartDir, { recursive: true, force: true });
});
