import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ProvenanceRail } from "../components/ProvenanceRail";
import { WelcomeScreen } from "../components/WelcomeScreen";

describe("welcome and evidence states", () => {
  it("sends the exact suggested question", () => {
    const onSuggestedQuestion = vi.fn();
    render(<WelcomeScreen onSuggestedQuestion={onSuggestedQuestion} />);

    fireEvent.click(
      screen.getByRole("button", {
        name: /what is the pto accrual rate for new employees/i,
      }),
    );

    expect(onSuggestedQuestion).toHaveBeenCalledWith(
      "What is the PTO accrual rate for new employees?",
    );
  });

  it("shows the current access scope before an answer exists", () => {
    render(
      <ProvenanceRail message={null} status="idle" accessGroup="finance" />,
    );

    expect(screen.getByText("Finance documents")).toBeDefined();
    expect(screen.getByText("Evidence appears here.")).toBeDefined();
  });
});
