/**
 * TypeScript types matching the API response shapes.
 * These are the source of truth for the UI; they match the Pydantic models
 * in src/custos/api.py exactly.
 */

export interface Citation {
  doc_id: string;
  doc_name: string;
  section_path: string[];
  char_start: number;
  char_end: number;
  snippet: string;
}

export interface ChatResponse {
  answer: string;
  citations: Citation[];
  refused: boolean;
}

export interface ToolUseEvent {
  tool_name: string;
  simulated?: boolean;
}

export interface PendingConfirmation {
  actionId: string;
  toolName: string;
  arguments: Record<string, unknown>;
  expired?: boolean;
}

export interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  citations: Citation[];
  refused: boolean;
  toolUses: ToolUseEvent[];
  pendingConfirmation: PendingConfirmation | null;
  timestamp: number;
  permissions?: string[];
  guardrailDetected?: boolean;
  statusText?: string;
}

/**
 * Chat state machine states.
 *
 * The "never stuck" invariant: every state allows the user to send a
 * new message or take an action. "streaming" allows cancel.
 * "awaiting_confirmation" allows approve, reject, or cancel.
 * There is no terminal state where the user is locked out.
 */
export type ChatStatus = "idle" | "streaming" | "awaiting_confirmation" | "error";

export interface ChatState {
  messages: Message[];
  status: ChatStatus;
  errorMessage: string | null;
}
