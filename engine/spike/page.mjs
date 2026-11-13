// Drive one FusionPBX page on staging as its admin, the way a person would: open it, fill fields by name, press Save.
//   node engine/spike/page.mjs <path> '<json: {"field name": "value", ...}>' [save button id, default btn_save]
//   node engine/spike/page.mjs <path> --show      list the page's form fields (name, type, current value) without saving
// FPBX_DOMAIN=<uuid> switches to that domain first. The admin password is read from staging's root-only file over SSH and never printed. Staging only.
import { execFileSync } from "node:child_process";
import { createRequire } from "node:module";
const require = createRequire(new URL("../../web/package.json", import.meta.url));
const { chromium } = require("playwright-core");

const BASE = "https://10.10.0.60";
const [path, arg, saveId = "btn_save"] = process.argv.slice(2);
const secret = execFileSync("ssh", ["-i", `${process.env.HOME}/.ssh/vox_staging`, "root@10.10.0.60",
  "sed -n 's/^[[:space:]]*password:[[:space:]]*//p' /root/vox-staging-admin.txt"], { encoding: "utf8" }).trim();

const executablePath = `${process.env.HOME}/.cache/ms-playwright/chromium-1248/chrome-linux64/chrome`;
const browser = await chromium.launch({ executablePath });
const page = await (await browser.newContext({ ignoreHTTPSErrors: true })).newPage();
try {
  await page.goto(`${BASE}/login.php`);
  await page.fill("input[name=username]", "admin");
  await page.fill("input[name=password]", secret);
  await Promise.all([page.waitForLoadState("networkidle"), page.click("#btn_login")]);
  if (page.url().includes("login.php")) throw new Error("login failed");
  // FPBX_DOMAIN=<domain uuid>: work in that domain, as an admin would by choosing it from the domain list.
  if (process.env.FPBX_DOMAIN) await page.goto(`${BASE}/core/domains/domains.php?domain_uuid=${process.env.FPBX_DOMAIN}&domain_change=true`);
  await page.goto(`${BASE}${path}`);
  if (arg === "--show") {
    const fields = await page.$$eval("form [name]", els => els.map(e => [e.name, e.type || e.tagName.toLowerCase(), e.type === "password" ? "(secret)" : (e.value ?? "").slice(0, 60)]));
    for (const f of fields) console.log(f.join("\t"));
  } else {
    for (const [name, value] of Object.entries(JSON.parse(arg))) {
      // A key starting with "css=" is a Playwright selector (for forms whose field names carry random indexes, like time conditions).
      const el = (name.startsWith("css=") ? page.locator(name) : page.locator(`[name="${name}"]`)).first();
      const tag = await el.evaluate(e => e.tagName.toLowerCase() + ":" + (e.type || ""));
      if (tag.startsWith("select")) await el.selectOption(String(value), { force: true });
      else if (tag.endsWith(":checkbox")) await el.setChecked(Boolean(value), { force: true });
      else await el.fill(String(value), { force: true });
    }
    await Promise.all([page.waitForLoadState("networkidle"), page.click(`#${saveId}`)]);
    const msg = await page.locator("#message_text, .message_text, #message_container").first().textContent().catch(() => "");
    console.log(`saved; now at ${page.url().replace(BASE, "")}${msg ? " — " + msg.trim() : ""}`);
  }
} finally {
  await browser.close();
}
