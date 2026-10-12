import { useState } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi } from "vitest";
import { ClipEditor, Timeline } from "./ReviewTimeline";
import { demoClips, type Job } from "../api";
const job: Job = {
  id: "test",
  status: "analyzed",
  duration: 60,
  clips: demoClips,
  candidates: demoClips,
  interest: [
    { time: 0, score: 20 },
    { time: 30, score: 90 },
  ],
};
function Editor() {
  const [clips, setClips] = useState(demoClips);
  return (
    <ClipEditor
      clips={clips}
      duration={60}
      onChange={setClips}
      onPreview={vi.fn()}
    />
  );
}
describe("review timeline", () => {
  it("shows interest, candidates and clips and seeks to a selected moment", async () => {
    const seek = vi.fn();
    render(<Timeline job={job} onSeek={seek} />);
    expect(
      screen.getByRole("img", { name: /Interest score/ }),
    ).toBeInTheDocument();
    await userEvent.click(
      screen.getByRole("button", {
        name: `Candidate: ${demoClips[1].caption}`,
      }),
    );
    expect(seek).toHaveBeenLastCalledWith(24);
    await userEvent.click(
      screen.getByRole("button", { name: `Seek to ${demoClips[0].caption}` }),
    );
    expect(seek).toHaveBeenLastCalledWith(8);
    fireEvent.change(screen.getByRole("slider", { name: "Seek source" }), {
      target: { value: "39.1" },
    });
    expect(seek).toHaveBeenLastCalledWith(39.1);
  });
  it("handles missing interest data without inventing scores", () => {
    render(
      <Timeline
        job={{ ...job, duration: 0, interest: [], clips: [], candidates: [] }}
        onSeek={vi.fn()}
      />,
    );
    expect(screen.getByText("No interest signal supplied")).toBeInTheDocument();
  });
});
describe("clip edits", () => {
  it("keeps drops reversible and edits captions", async () => {
    render(<Editor />);
    const keep = screen.getByRole("checkbox", {
      name: `Keep ${demoClips[0].caption}`,
    });
    await userEvent.click(keep);
    expect(keep).not.toBeChecked();
    await userEvent.click(keep);
    expect(keep).toBeChecked();
    const caption = screen.getByLabelText("Caption 1");
    await userEvent.clear(caption);
    await userEvent.type(caption, "New caption");
    expect(
      screen.getByRole("checkbox", { name: "Keep New caption" }),
    ).toBeChecked();
  });
  it("trims and reorders while preserving edits and range preview", async () => {
    render(<Editor />);
    fireEvent.change(screen.getByLabelText("Trim start 1"), {
      target: { value: "10" },
    });
    fireEvent.change(screen.getByLabelText("Trim end 1"), {
      target: { value: "16" },
    });
    await userEvent.click(screen.getByLabelText("Move clip 1 down"));
    expect(screen.getByLabelText("Caption 2")).toHaveValue(
      demoClips[0].caption,
    );
    expect(screen.getByLabelText("Trim start 2")).toHaveValue("10");
    expect(screen.getByLabelText("Trim end 2")).toHaveValue("16");
  });
  it("supports drag reorder and previews exact ranges", () => {
    const change = vi.fn(),
      preview = vi.fn();
    render(
      <ClipEditor
        clips={demoClips}
        duration={60}
        onChange={change}
        onPreview={preview}
      />,
    );
    const cards = screen.getAllByRole("article");
    fireEvent.dragStart(cards[0], { dataTransfer: { setData: vi.fn() } });
    fireEvent.dragOver(cards[2]);
    fireEvent.drop(cards[2]);
    expect(change.mock.calls[0][0].map((c: { id: string }) => c.id)).toEqual([
      "whiff",
      "team",
      "clutch",
    ]);
    fireEvent.click(screen.getAllByText("Preview range")[1]);
    expect(preview).toHaveBeenCalledWith(demoClips[1]);
  });
  it("locks editing during processing", () => {
    render(
      <ClipEditor
        clips={demoClips}
        duration={60}
        disabled
        onChange={vi.fn()}
        onPreview={vi.fn()}
      />,
    );
    expect(screen.getByLabelText("Trim start 1")).toBeDisabled();
    expect(screen.getByLabelText("Move clip 1 down")).toBeDisabled();
  });
});
