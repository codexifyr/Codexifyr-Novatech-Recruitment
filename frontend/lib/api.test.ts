import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "./api";

afterEach(() => vi.restoreAllMocks());

describe("api", () => {
  it("returns parsed JSON responses", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ success: true }), { status: 200 })));
    await expect(api<{ success: boolean }>("/health")).resolves.toEqual({ success: true });
  });

  it("surfaces backend error details", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: "Forbidden" }), { status: 403 })));
    await expect(api("/protected")).rejects.toThrow("Forbidden");
  });

  it("does not set JSON content type for multipart uploads", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ success: true }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    const form = new FormData();
    form.append("file", new Blob(["content"], { type: "text/plain" }), "file.txt");
    await api("/upload", { method: "POST", body: form });
    expect(fetchMock.mock.calls[0][1].headers["Content-Type"]).toBeUndefined();
    expect(fetchMock.mock.calls[0][1].credentials).toBe("include");
  });
});