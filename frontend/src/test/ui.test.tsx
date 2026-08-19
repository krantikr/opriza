import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { Badge, Button, Pagination, Tabs } from "../components/ui";

/* ---------------------------------------------------------------------------
   Shared controls.

   The point of these is consistency: a button is the same height wherever it
   appears, and a status reads the same way on every screen. Both are easy to
   drift and hard to notice one page at a time.
   --------------------------------------------------------------------------- */

describe("Button sizing", () => {
  it("uses one height and one type size by default", () => {
    render(<Button>Send</Button>);
    const button = screen.getByRole("button", { name: "Send" });
    expect(button.className).toContain("py-2");
    expect(button.className).toContain("text-sm");
  });

  it("keeps the same type size when compact — only the padding tightens", () => {
    // A compact button must still read as the same component, or a dense row
    // ends up looking like a different design.
    render(<Button compact>Save</Button>);
    const button = screen.getByRole("button", { name: "Save" });
    expect(button.className).toContain("text-sm");
    expect(button.className).toContain("py-1");
    expect(button.className).not.toContain("py-2");
  });

  it("matches the height of an input, so a toolbar sits on one baseline", () => {
    render(
      <>
        <Button>Go</Button>
        <input className="rounded-lg border px-3 py-2 text-sm" aria-label="field" />
      </>,
    );
    const button = screen.getByRole("button", { name: "Go" });
    const field = screen.getByLabelText("field");
    // Both are py-2 text-sm; if one changes the other must too.
    expect(button.className).toContain("py-2");
    expect(field.className).toContain("py-2");
  });

  it("renders every variant as one button element", () => {
    for (const variant of ["primary", "secondary", "danger", "ghost"] as const) {
      const { unmount } = render(<Button variant={variant}>{variant}</Button>);
      expect(screen.getByRole("button", { name: variant })).toBeInTheDocument();
      unmount();
    }
  });

  it("does not fire while disabled", async () => {
    const onClick = vi.fn();
    const user = userEvent.setup();
    render(
      <Button disabled onClick={onClick}>
        Send
      </Button>,
    );
    await user.click(screen.getByRole("button", { name: "Send" }));
    expect(onClick).not.toHaveBeenCalled();
  });
});

describe("Badge", () => {
  it("reads a status as words, not as an enum", () => {
    render(<Badge value="READY_FOR_REVIEW" />);
    expect(screen.getByText("ready for review")).toBeInTheDocument();
  });

  it("renders a dash for a missing status rather than an empty pill", () => {
    render(<Badge value={null} />);
    expect(screen.getByText("—")).toBeInTheDocument();
  });
});

describe("Tabs", () => {
  it("reports the tab that was chosen", async () => {
    const onChange = vi.fn();
    const user = userEvent.setup();
    render(
      <Tabs
        tabs={[
          { key: "a", label: "Overview" },
          { key: "b", label: "Pricing", count: 3 },
        ]}
        value="a"
        onChange={onChange}
      />,
    );

    await user.click(screen.getByRole("button", { name: /Pricing/ }));
    expect(onChange).toHaveBeenCalledWith("b");
  });

  it("shows a count beside the tab it belongs to", () => {
    render(
      <Tabs tabs={[{ key: "a", label: "Draft", count: 12 }]} value="a" onChange={vi.fn()} />,
    );
    expect(screen.getByText("12")).toBeInTheDocument();
  });
});

describe("Pagination", () => {
  it("stays out of the way when there is only one page", () => {
    const { container } = render(
      <Pagination page={1} pageCount={1} onChange={vi.fn()} summary="Showing 4 of 4" />,
    );
    // The summary still shows; the pager does not.
    expect(screen.getByText("Showing 4 of 4")).toBeInTheDocument();
    expect(container.querySelectorAll("button")).toHaveLength(0);
  });

  it("moves to the page that was clicked", async () => {
    const onChange = vi.fn();
    const user = userEvent.setup();
    render(<Pagination page={1} pageCount={4} onChange={onChange} />);

    await user.click(screen.getByRole("button", { name: "3" }));
    expect(onChange).toHaveBeenCalledWith(3);
  });

  it("cannot step back from the first page or on from the last", () => {
    const { rerender } = render(
      <Pagination page={1} pageCount={4} onChange={vi.fn()} />,
    );
    expect(screen.getByLabelText("Previous page")).toBeDisabled();

    rerender(<Pagination page={4} pageCount={4} onChange={vi.fn()} />);
    expect(screen.getByLabelText("Next page")).toBeDisabled();
  });
});
