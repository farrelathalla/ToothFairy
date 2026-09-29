import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect } from "vitest";

import ModelGallery from "@/components/result/ModelGallery";

const ITEMS = [
  { id: "fdi", title: "FDI Intraoral", desc: "penomoran gigi", src: "/x/fdi.jpg" },
  { id: "seg", title: "Segmentasi", desc: "polygon gigi", src: "/x/seg.jpg" },
  { id: "xai_up_fdi", title: "XAI · FDI", desc: "attention", src: "/x/xai.jpg" },
];

describe("ModelGallery", () => {
  it("renders a card per overlay entry", () => {
    render(<ModelGallery items={ITEMS} />);
    expect(screen.getAllByTestId("gallery-card")).toHaveLength(3);
    expect(screen.getByText("FDI Intraoral")).toBeInTheDocument();
  });

  it("opens a lightbox when a card is clicked", async () => {
    const user = userEvent.setup();
    render(<ModelGallery items={ITEMS} />);
    await user.click(screen.getAllByTestId("gallery-card")[0]);
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });
});
