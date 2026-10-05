import { expect, test, type Page } from "@playwright/test";

const PASSWORD = "BankOpsDemo!2026";

async function login(page: Page, username: string) {
  await page.goto("/login");
  await page.getByLabel("Username").fill(username);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("heading", { name: "Operations overview" })).toBeVisible({ timeout: 20_000 });
}

test.describe("Statement outage scenario — end to end", () => {
  test("analyst starts, manager approves, investigation resolves", async ({ browser }) => {
    test.setTimeout(120_000);

    // Use two separate contexts to avoid session conflicts.
    const analystCtx = await browser.newContext();
    const managerCtx = await browser.newContext();
    const analyst = await analystCtx.newPage();
    const manager = await managerCtx.newPage();

    // 1. Analyst logs in and starts the scenario.
    await login(analyst, "ops.analyst");
    await analyst.goto("/demo");
    await expect(analyst.getByRole("heading", { name: "Guided demo" })).toBeVisible();

    const startButton = analyst.locator("section", { hasText: /statement/i }).getByRole("button", { name: "Start scenario" });
    await startButton.click();

    // 2. Wait for the investigation to reach awaiting_approval.
    await expect(analyst.getByText("AI Investigation Workspace")).toBeVisible({ timeout: 15_000 });
    await expect(analyst.getByText("Awaiting approval", { exact: false })).toBeVisible({ timeout: 60_000 });

    // 3. Manager logs in and approves the action.
    await login(manager, "ops.manager");
    await manager.goto("/approvals");
    await expect(manager.getByRole("heading", { name: "Approval Center" })).toBeVisible();

    // Wait for the pending approval to appear (the investigation may still be creating it).
    const approvalArticle = manager.locator("article").filter({ hasText: /SIMULATED ACTION/i }).first();
    await expect(approvalArticle).toBeVisible({ timeout: 30_000 });

    // Click "Approve…" to open the confirmation modal.
    await approvalArticle.getByRole("button", { name: /Approve/i }).click();

    // Check the confirmation checkbox inside the modal and confirm.
    const modal = manager.locator("[role='dialog']");
    await expect(modal).toBeVisible({ timeout: 5_000 });
    await modal.getByRole("checkbox").check();
    await modal.getByRole("button", { name: /Confirm approval/i }).click();

    // 4. Wait for the approval to be processed (the modal closes and the status changes).
    await expect(modal).not.toBeVisible({ timeout: 15_000 });
    await manager.waitForTimeout(2000); // Allow the list to refresh.

    // 5. Analyst views the investigation and waits for completion.
    await analyst.goto("/investigations");
    await analyst.locator("a").filter({ hasText: /INC-/i }).first().click();
    await expect(analyst.getByText(/completed|resolved/i).first()).toBeVisible({ timeout: 60_000 });

    // 6. Verify the audit chain as the manager.
    await manager.goto("/governance");
    await manager.getByRole("tab", { name: "Audit log" }).click();
    await manager.getByRole("button", { name: "Verify hash chain" }).click();
    await expect(manager.getByText(/Chain valid/i)).toBeVisible({ timeout: 10_000 });

    await analystCtx.close();
    await managerCtx.close();
  });

  test("read-only viewer cannot start investigations", async ({ page }) => {
    await login(page, "readonly.viewer");
    await page.goto("/demo");
    const startButton = page.locator("section", { hasText: /statement/i }).getByRole("button", { name: "Start scenario" });
    await expect(startButton).toBeDisabled();
  });

  test("analyst cannot approve (separation of duties)", async ({ page }) => {
    await login(page, "ops.analyst");
    await page.goto("/approvals");
    const approveButtons = page.locator("article").getByRole("button", { name: /Approve/i });
    if (await approveButtons.count() > 0) {
      await expect(approveButtons.first()).toBeDisabled();
    }
  });
});
