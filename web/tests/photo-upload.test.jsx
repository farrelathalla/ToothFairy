import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi } from "vitest";

import PhotoUpload, { VIEW_SLOTS } from "@/components/case/PhotoUpload";

function img(name) {
  return new File([new Uint8Array([1, 2, 3])], name, { type: "image/jpeg" });
}

describe("PhotoUpload", () => {
  it("renders 6 independent slots with Indonesian labels", () => {
    render(<PhotoUpload files={{}} onSelect={vi.fn()} />);
    expect(VIEW_SLOTS).toHaveLength(6);
    for (const slot of VIEW_SLOTS) {
      expect(screen.getByLabelText(slot.label)).toBeInTheDocument();
    }
    // panoramic slot is separated into its own group
    expect(VIEW_SLOTS.filter((s) => s.group === "panoramic")).toHaveLength(1);
  });

  it("calls onSelect with the view key and file when a slot receives a file", async () => {
    const onSelect = vi.fn();
    const user = userEvent.setup();
    render(<PhotoUpload files={{}} onSelect={onSelect} />);

    await user.upload(screen.getByLabelText("Panoramik"), img("pano.jpg"));
    expect(onSelect).toHaveBeenCalledTimes(1);
    const [key, file] = onSelect.mock.calls[0];
    expect(key).toBe("panoramic");
    expect(file.name).toBe("pano.jpg");
  });

  it("shows the filename and a remove button for a filled slot", async () => {
    const onSelect = vi.fn();
    const user = userEvent.setup();
    render(<PhotoUpload files={{ up: img("upper.jpg") }} onSelect={onSelect} />);

    expect(screen.getByText("upper.jpg")).toBeInTheDocument();
    await user.click(screen.getByLabelText("Hapus Rahang Atas (oklusal)"));
    expect(onSelect).toHaveBeenCalledWith("up", null);
  });
});
