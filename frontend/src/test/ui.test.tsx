import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { Badge, Button, Input, Pagination, Tabs, Toggle } from "../components/ui";

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


describe("Input width", () => {
  /* `w-full` and `w-56` have equal specificity, so the winner is whichever
     Tailwind emits later - and that is always `w-full`. Passing a width used
     to do nothing, which is how the Inbox search field grew to fill its row
     and wrapped the Refresh button onto a second line. */

  it("is full width by default", () => {
    render(<Input value="" onChange={() => {}} placeholder="p" />);
    expect(screen.getByPlaceholderText("p").className).toContain("w-full");
  });

  it("drops w-full when the caller sets a width", () => {
    render(<Input value="" onChange={() => {}} placeholder="p" className="w-56" />);
    const cls = screen.getByPlaceholderText("p").className;
    expect(cls).toContain("w-56");
    expect(cls).not.toContain("w-full");
  });

  it("keeps w-full alongside a min- or max- constraint", () => {
    /* `min-w-24` and `max-w-full` are not widths: they bound one. A field
       given only those still needs its own width to fill the space. */
    render(
      <Input value="" onChange={() => {}} placeholder="p" className="min-w-24 flex-1" />,
    );
    expect(screen.getByPlaceholderText("p").className).toContain("w-full");
  });

  it("does not mistake a non-width class for a width", () => {
    render(<Input value="" onChange={() => {}} placeholder="p" className="shadow-card" />);
    expect(screen.getByPlaceholderText("p").className).toContain("w-full");
  });
});


describe("Toggle", () => {
  /* The knob is laid out by flex inside a padded track, not positioned by a
     `translate-x` figure matched to the track width by hand. When those two
     numbers drifted apart the knob rendered outside its own pill. */

  const track = (el: HTMLElement) => el.querySelector("span")!;
  const knob = (el: HTMLElement) => el.querySelector("span > span")!;

  it("keeps the knob inside the track in both states", () => {
    for (const checked of [true, false]) {
      const { unmount } = render(<Toggle checked={checked} onChange={() => {}} />);
      const sw = screen.getByRole("switch");
      // Padding on the track is what contains the knob; absolute positioning
      // would let it escape.
      expect(track(sw).className).toContain("p-0.5");
      expect(knob(sw).className).not.toContain("absolute");
      unmount();
    }
  });

  it("slides the knob by its own width rather than a fixed pixel figure", () => {
    const { rerender } = render(<Toggle checked={false} onChange={() => {}} />);
    expect(knob(screen.getByRole("switch")).className).toContain("translate-x-0");

    rerender(<Toggle checked onChange={() => {}} />);
    expect(knob(screen.getByRole("switch")).className).toContain("translate-x-full");
  });

  it("reports its state to assistive tech", () => {
    render(<Toggle checked onChange={() => {}} />);
    expect(screen.getByRole("switch")).toHaveAttribute("aria-checked", "true");
  });

  it("fills the track when on and greys it when off", () => {
    const { rerender } = render(<Toggle checked onChange={() => {}} />);
    expect(track(screen.getByRole("switch")).className).toContain("bg-brand-ink");

    rerender(<Toggle checked={false} onChange={() => {}} />);
    expect(track(screen.getByRole("switch")).className).toContain("bg-rule-firm");
  });
});
