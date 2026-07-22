import { describe, expect, it } from "vitest";

import { decryptSecret, encryptSecret, maskedSecret } from "../src/crypto";

describe("integration credential encryption", () => {
  it("encrypts with authenticated tenant context and decrypts the original secret", async () => {
    const key = "test-master-key-with-more-than-32-characters";
    const encrypted = await encryptSecret("secret-value-1234", key, "tenant-a:api-key");
    expect(encrypted).not.toContain("secret-value-1234");
    await expect(decryptSecret(encrypted, key, "tenant-a:api-key")).resolves.toBe(
      "secret-value-1234",
    );
    await expect(decryptSecret(encrypted, key, "tenant-b:api-key")).rejects.toThrow();
  });

  it("only exposes the final four characters in masked output", () => {
    expect(maskedSecret("sk-private-1234")).toBe("••••••••1234");
    expect(maskedSecret("")).toBe("");
  });
});
