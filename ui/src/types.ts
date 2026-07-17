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

export interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  citations: Citation[];
  refused: boolean;
  toolUses: ToolUseEvent[];
  timestamp: number;
}

/**
 * Chat state machine states.
 *
 * The "never stuck" invariant: every state except "streaming" allows the user
 * to send a new message. "streaming" allows cancel. There is no terminal
 * state where the user is locked out.
 */
export type ChatStatus = "idle" | "streaming" | "error";

export interface ChatState {
  messages: Message[];
  status: ChatStatus;
  errorMessage: string | null;
}
