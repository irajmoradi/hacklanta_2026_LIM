import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import App from "./App";
afterEach(() => {
  window.history.replaceState({}, "", "/");
  vi.unstubAllGlobals();
});
it("uploads, analyzes, previews a bounded range, edits, and simulates export without a backend", async () => {
  window.history.replaceState({}, "", "/?mock=1");
  const create = vi.fn().mockReturnValue("blob:test");
  const revoke = vi.fn();
  URL.createObjectURL = create;
  URL.revokeObjectURL = revoke;
  const play = vi.spyOn(HTMLMediaElement.prototype, "play").mockResolvedValue();
  const pause = vi
    .spyOn(HTMLMediaElement.prototype, "pause")
    .mockImplementation(() => {});
  const fetcher = vi.fn();
  vi.stubGlobal("fetch", fetcher);
  const { container, unmount } = render(<App />);
  await userEvent.upload(
    screen.getByLabelText("Upload gameplay"),
    new File(["synthetic placeholder"], "test.mp4", { type: "video/mp4" }),
  );
  await userEvent.click(
    await screen.findByRole("button", { name: /Find my moments/ }),
  );
  await screen.findByLabelText("Caption 1");
  await userEvent.click(
    screen.getAllByRole("button", { name: /Preview range/ })[0],
  );
  const source = container.querySelector(".player video") as HTMLVideoElement;
  expect(source.currentTime).toBe(8);
  expect(play).toHaveBeenCalled();
  source.currentTime = 17.2;
  fireEvent.timeUpdate(source);
  expect(pause).toHaveBeenCalled();
  expect(source.currentTime).toBe(17);
  await userEvent.click(screen.getByLabelText("Keep One shot. Round saved."));
  await userEvent.selectOptions(
    screen.getByLabelText("Export preset"),
    "vertical",
  );
  await userEvent.click(screen.getByRole("button", { name: /Render reel/ }));
  await screen.findByText("Demo export complete");
  expect(
    screen.queryByRole("link", { name: /Download montage/ }),
  ).not.toBeInTheDocument();
  expect(fetcher).not.toHaveBeenCalled();
  unmount();
  expect(revoke).toHaveBeenCalledWith("blob:test");
});
it("rejects oversized uploads without posting video data", async () => {
  const fetcher = vi.fn();
  vi.stubGlobal("fetch", fetcher);
  render(<App />);
  const file = new File(["x"], "big.mp4", { type: "video/mp4" });
  Object.defineProperty(file, "size", { value: 3 * 1024 ** 3 });
  fireEvent.change(screen.getByLabelText("Upload gameplay"), {
    target: { files: [file] },
  });
  await waitFor(() =>
    expect(screen.getByRole("alert")).toHaveTextContent("smaller than 2 GB"),
  );
  expect(fetcher).toHaveBeenCalledExactlyOnceWith("/api/info", { method: "GET" });
});
