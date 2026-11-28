import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "./api";

afterEach(() => {
  vi.unstubAllGlobals();
  localStorage.clear();
});

describe("api client", () => {
  it("converts FastAPI validation details to a readable error", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({
      detail: [
        { loc: ["body", "birth_date"], msg: "Дата рождения не может быть в будущем", type: "value_error" },
      ],
    }), { status: 422, headers: { "Content-Type": "application/json" } })));

    await expect(api("/api/patients", { method: "POST" }))
      .rejects.toThrow("Дата рождения не может быть в будущем");
  });

  it("clears expired token and signals the app to return to login", async () => {
    localStorage.setItem("gepa_token", "expired-token");
    const onExpired = vi.fn();
    window.addEventListener("gepa:auth-expired", onExpired);
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("{}", { status: 401 })));

    await expect(api("/api/auth/me")).rejects.toThrow("Сессия истекла");
    expect(localStorage.getItem("gepa_token")).toBeNull();
    expect(onExpired).toHaveBeenCalledOnce();
    window.removeEventListener("gepa:auth-expired", onExpired);
  });

  it("returns a useful message for connection failures", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("offline")));
    await expect(api("/api/worklist")).rejects.toThrow("Не удалось связаться с сервером");
  });
});
