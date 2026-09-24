import { expect, test } from "@playwright/test";

const enabled = Boolean(process.env.E2E_BASE_URL);
test.describe("production core browser smoke tests", () => {
  test.beforeEach(async ({}, testInfo) => {
    test.skip(!enabled, "Set E2E_BASE_URL to run browser tests against a running frontend; no live browser target was configured.");
    testInfo.annotations.push({ type: "security", description: "Test data is synthetic and API failures are reported without response bodies." });
  });

  test("authentication and role navigation", async ({ page }) => {
    await page.route("**/api/v1/auth/login", route => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ user: { role: "admin", full_name: "E2E Test Admin", must_change_password: false } }) }));
    await page.route("**/api/v1/auth/me", route => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ user: { id: "admin-1", role: "admin", full_name: "E2E Test Admin" } }) }));
    await page.route("**/api/v1/operations/notifications/unread-count", route => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ count: 0 }) }));
    await page.route("**/api/v1/admin/dashboard", route => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ metrics: {} }) }));
    await page.route("**/api/v1/admin/applications**", route => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ items: [] }) }));
    await page.goto("/login");
    await page.getByLabel("Username or email").fill("e2e-admin@example.test");
    await page.getByLabel("Password").fill("E2E-not-a-real-password");
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(page).toHaveURL(/dashboard/);
    await expect(page.getByRole("link", { name: "Requisitions" })).toBeVisible();
  });

  test("applications search and bulk shortlist", async ({ page }) => {
    let bulkCalled = false;
    await page.route("**/api/v1/admin/applications**", route => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ items: [{ id: "00000000-0000-0000-0000-000000000001", application_code: "APP-E2E", name_at_application: "E2E Candidate", email_at_application: "candidate@example.test", experience_years: 3, status: "MANUAL_REVIEW", final_score: 82, created_at: "2026-09-22T00:00:00Z", job_positions: { title: "Test Role", department: "Engineering" } }], has_more: false }) }));
    await page.route("**/api/v1/operations/applications/bulk", route => { bulkCalled = true; return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ message: "Bulk shortlist complete" }) }); });
    await page.goto("/dashboard/applications");
    await page.getByLabel(/Select E2E Candidate/).check();
    await page.getByRole("button", { name: "Shortlist" }).click();
    await expect.poll(() => bulkCalled).toBe(true);
  });

  test("interviewer assignment approval", async ({ page }) => {
    let assignmentCalled = false;
    await page.route("**/api/v1/auth/me", route => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ user: { id: "hr-1", role: "hr", full_name: "E2E HR" } }) }));
    await page.route("**/api/v1/admin/interviews", route => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ items: [{ id: "00000000-0000-0000-0000-000000000002", interview_code: "INT-E2E", status: "PENDING_CONFIRMATION", assignment_status: "PENDING_APPROVAL", interview_type: "Technical", round_number: 1, applications: { name_at_application: "E2E Candidate", job_positions: { title: "Test Role", department: "Engineering" } } }] }) }));
    await page.route("**/api/v1/admin/interviewers", route => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ items: [{ id: "00000000-0000-0000-0000-000000000003", full_name: "E2E Interviewer", role: "interviewer", department: "Engineering" }] }) }));
    await page.route("**/api/v1/admin/interviews/*/assignment", route => { assignmentCalled = true; return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ message: "Interviewer assignment approved" }) }); });
    await page.goto("/dashboard/interviews");
    await page.getByRole("button", { name: "Assign / change" }).click();
    await page.getByLabel("Eligible interviewer").selectOption("00000000-0000-0000-0000-000000000003");
    await page.getByRole("button", { name: "Approve assignment" }).click();
    await expect.poll(() => assignmentCalled).toBe(true);
  });

  test("assigned interviewer creates Google Meet schedule", async ({ page }) => {
    let scheduleCalled = false;
    await page.route("**/api/v1/auth/me", route => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ user: { id: "person-1", role: "interviewer", full_name: "E2E Interviewer" } }) }));
    await page.route("**/api/v1/admin/interviews/interview-1/workspace", route => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ item: { id: "interview-1", interview_code: "INT-E2E", status: "PENDING_CONFIRMATION", interviewer_id: "person-1", assignment_status: "APPROVED", interviewer_response: "ACCEPTED", applications: { name_at_application: "E2E Candidate", email_at_application: "candidate@example.test", final_score: 88, ai_review: { candidate_summary: "Evidence-based test summary" }, job_positions: { title: "Python Engineer", department: "Engineering" } } } }) }));
    await page.route("**/api/v1/admin/interviews/interview-1/schedule", route => { scheduleCalled = true; return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ message: "Google Meet interview scheduled and invitations sent" }) }); });
    await page.goto("/dashboard/interviews/interview-1");
    await page.getByLabel("Date and time").fill("2099-09-23T10:00");
    await page.getByRole("button", { name: "Save schedule and send invitations" }).click();
    await expect.poll(() => scheduleCalled).toBe(true);
  });

  test("candidate securely requests a new interview time", async ({ page }) => {
    let rescheduleCalled = false;
    const token = "x".repeat(40);
    await page.route("**/api/v1/interviews/respond**", route => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ item: { interview_code: "INT-E2E", status: "PENDING_CONFIRMATION", scheduled_start: "2099-01-01T10:00:00Z", candidate_name: "E2E Candidate", position: "Python Engineer" } }) }));
    await page.route("**/api/v1/interviews/reschedule", route => { rescheduleCalled = true; return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ message: "Your reschedule request has been sent" }) }); });
    await page.goto(`/interview?token=${token}&action=RESCHEDULE`);
    await page.getByLabel("Preferred new date and time").fill("2099-01-02T10:00");
    await page.getByRole("button", { name: "Send reschedule request" }).click();
    await expect.poll(() => rescheduleCalled).toBe(true);
  });

  test("candidate offer response", async ({ page }) => {
    let responseCalled = false;
    await page.route("**/api/v1/candidate/portal", route => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ applications: [{ id: "app-1", application_code: "APP-E2E", status: "OFFERED", job_positions: { title: "Test Role", department: "Engineering", location: "Remote" }, interviews: [], offers: [{ id: "offer-1", offer_code: "OFF-E2E", status: "OFFERED", joining_date: "2026-10-01", expiry_date: "2099-10-01" }] }], documents: [], employee: null, onboarding: [] }) }));
    await page.route("**/api/v1/candidate/offers/offer-1/response", route => { responseCalled = true; return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ message: "Offer response recorded" }) }); });
    await page.goto("/portal");
    page.on("dialog", dialog => dialog.accept());
    await page.getByRole("button", { name: "Accept offer" }).click();
    await expect.poll(() => responseCalled).toBe(true);
  });

  test("profile photo upload", async ({ page }) => {
    let uploadCalled = false;
    await page.route("**/api/v1/auth/me", route => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ user: { full_name: "E2E User", username: "e2e", email: "e2e@example.test", role: "admin" } }) }));
    await page.route("**/api/v1/auth/me/avatar", route => { uploadCalled = true; return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ message: "Profile photo updated", data: { avatar_url: "https://signed.example.test/avatar" } }) }); });
    await page.goto("/account");
    await page.locator('input[name="file"]').setInputFiles({ name: "avatar.png", mimeType: "image/png", buffer: Buffer.from("fake-e2e-image") });
    await page.getByRole("button", { name: "Upload photo" }).click();
    await expect.poll(() => uploadCalled).toBe(true);
  });

  test("candidate document upload", async ({ page }) => {
    let uploadCalled = false;
    await page.route("**/api/v1/candidate/portal", route => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ applications: [], documents: [], employee: null, onboarding: [] }) }));
    await page.route("**/api/v1/candidate/documents", route => { uploadCalled = true; return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ message: "Document uploaded for review" }) }); });
    await page.goto("/portal");
    await page.locator('input[name="document_type"]').fill("CV");
    await page.locator('input[name="file"]').setInputFiles({ name: "resume.pdf", mimeType: "application/pdf", buffer: Buffer.from("%PDF-e2e") });
    await page.getByRole("button", { name: "Upload document" }).click();
    await expect.poll(() => uploadCalled).toBe(true);
  });
});
