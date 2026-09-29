import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { Button } from "@/components/ui/button";

describe("app smoke", () => {
  it("renders a shadcn Button with its label and primary classes", () => {
    render(<Button>Kasus Baru</Button>);
    const btn = screen.getByRole("button", { name: "Kasus Baru" });
    expect(btn).toBeInTheDocument();
    expect(btn.className).toContain("bg-primary");
  });

  it("applies the size variant classes", () => {
    render(<Button size="lg">Masuk</Button>);
    expect(screen.getByRole("button", { name: "Masuk" }).className).toContain("h-10");
  });
});
