/**
 * Rendering tests for the Message component.
 * Verifies markdown renders correctly inside the assistant bubble.
 */

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Message } from "../components/Message";
import type { Message as MessageType } from "../types";

function makeAssistantMsg(content: string, overrides?: Partial<MessageType>): MessageType {
  return {
    id: "test-1",
    role: "assistant",
    content,
    citations: [],
    refused: false,
    toolUses: [],
    pendingConfirmation: null,
    timestamp: Date.now(),
    ...overrides,
  };
}

describe("Message rendering", () => {
  it("renders a fenced code block as <pre><code>", () => {
    const msg = makeAssistantMsg(
      "Here is code:\n\n```python\nprint('hello')\n```\n\nDone.",
    );
    const { container } = render(
      <Message message={msg} isStreaming={false} />,
    );

    const pre = container.querySelector("pre");
    expect(pre).not.toBeNull();

    const code = pre?.querySelector("code");
    expect(code).not.toBeNull();
    expect(code?.textContent).toContain("print('hello')");

    // pre exists in the DOM inside .md-content
    expect(pre?.closest(".md-content")).not.toBeNull();
  });

  it("renders emails as plain text, not clickable links", () => {
    const msg = makeAssistantMsg("Contact test@example.com for help.");
    const { container } = render(
      <Message message={msg} isStreaming={false} />,
    );

    // No <a> tags should be rendered for emails
    const links = container.querySelectorAll("a");
    expect(links.length).toBe(0);
    expect(container.textContent).toContain("test@example.com");
  });

  it("derives access label from permissions", () => {
    const msg = makeAssistantMsg("Answer.", {
      permissions: ["hr"],
      citations: [{
        doc_id: "hr-001",
        doc_name: "HR Records",
        section_path: ["Employee"],
        char_start: 0,
        char_end: 100,
        snippet: "Test snippet",
      }],
    });
    render(<Message message={msg} isStreaming={false} />);

    expect(screen.getByText("Access: HR")).toBeDefined();
  });
});
