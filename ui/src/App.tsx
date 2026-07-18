import { ChatInput } from "./components/ChatInput";
import { DemoBanner } from "./components/DemoBanner";
import { ErrorBanner } from "./components/ErrorBanner";
import { Header } from "./components/Header";
import { MessageList } from "./components/MessageList";
import { ProvenanceRail } from "./components/ProvenanceRail";
import { WelcomeScreen } from "./components/WelcomeScreen";
import { useChat } from "./hooks/useChat";

export default function App() {
  const {
    state,
    accessGroup,
    setAccessGroup,
    sendMessage,
    cancelStream,
    retry,
    clearError,
    approveAction,
    rejectAction,
  } = useChat();
  const hasMessages = state.messages.length > 0;
  const lastAssistant = [...state.messages].reverse().find((m) => m.role === "assistant");

  return (
    <div className="app">
      <DemoBanner />
      <Header accessGroup={accessGroup} onAccessChange={setAccessGroup} />
      <div className="body-layout">
        <div className="thread">
          <main className="chat-container">
            {hasMessages ? (
              <MessageList
                messages={state.messages}
                status={state.status}
                onApprove={approveAction}
                onReject={rejectAction}
              />
            ) : (
              <WelcomeScreen onSuggestedQuestion={sendMessage} />
            )}
            {state.status === "error" && state.errorMessage && (
              <ErrorBanner
                message={state.errorMessage}
                onRetry={retry}
                onDismiss={clearError}
              />
            )}
          </main>
          <div className="composer-wrap">
            <ChatInput
              status={state.status}
              onSend={sendMessage}
              onCancel={cancelStream}
            />
          </div>
        </div>
        <ProvenanceRail message={lastAssistant ?? null} status={state.status} />
      </div>
    </div>
  );
}
