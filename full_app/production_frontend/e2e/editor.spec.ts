import { test, expect } from "@playwright/test";
import { execFileSync } from "node:child_process";
import { mkdirSync } from "node:fs";
import { dirname } from "node:path";
test("synthetic gameplay review works at laptop and mobile widths", async ({
  page,
}, info) => {
  const sample = info.outputPath("synthetic.mp4");
  mkdirSync(dirname(sample), { recursive: true });
  execFileSync(
    "ffmpeg",
    [
      "-y",
      "-f",
      "lavfi",
      "-i",
      "testsrc2=size=320x180:rate=10",
      "-f",
      "lavfi",
      "-i",
      "sine=frequency=440:sample_rate=44100",
      "-t",
      "60",
      "-c:v",
      "libx264",
      "-preset",
      "ultrafast",
      "-pix_fmt",
      "yuv420p",
      "-c:a",
      "aac",
      "-movflags",
      "+faststart",
      sample,
    ],
    { stdio: "pipe" },
  );
  const errors: string[] = [];
  const apiRequests: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  page.on("request", (r) => {
    if (new URL(r.url()).pathname.startsWith("/api/"))
      apiRequests.push(r.url());
  });
  await page.goto("/?mock=1");
  await page.getByLabel("Upload gameplay").setInputFiles(sample);
  await page.getByRole("button", { name: /Find my moments/ }).click();
  await expect(page.getByLabel("Caption 1")).toBeVisible();
  expect(await page.locator("body").innerText()).not.toMatch(/[\uFFFD?]/);
  await expect(page.getByLabel("Move clip 1 down")).toHaveText("\u2193");
  await expect
    .poll(() =>
      page
        .locator(".player video")
        .evaluate((v: HTMLVideoElement) => v.readyState),
    )
    .toBeGreaterThan(1);
  await page.getByLabel("Trim end 1").focus();
  await page.keyboard.press("Home");
  await page
    .getByRole("button", { name: /Preview range/ })
    .first()
    .click();
  await expect
    .poll(() =>
      page
        .locator(".player video")
        .evaluate((v: HTMLVideoElement) => v.currentTime),
    )
    .toBeGreaterThanOrEqual(8);
  await expect
    .poll(() =>
      page.locator(".player video").evaluate((v: HTMLVideoElement) => v.paused),
    )
    .toBe(true);
  expect(
    await page
      .locator(".player video")
      .evaluate((v: HTMLVideoElement) => v.currentTime),
  ).toBeCloseTo(8.1, 1);
  await page.getByLabel("Move clip 1 down").click();
  await expect(page.getByLabel("Caption 2")).toHaveValue(
    "One shot. Round saved.",
  );
  await page.screenshot({
    path: info.outputPath("laptop.png"),
    fullPage: true,
  });
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: info.outputPath("mobile.png"),
    fullPage: true,
  });
  await page.getByLabel("Export preset").selectOption("vertical");
  await page.getByRole("button", { name: /Render reel/ }).click();
  await expect(page.getByText("Demo export complete")).toBeVisible();
  expect(apiRequests).toEqual([]);
  expect(errors).toEqual([]);
});
