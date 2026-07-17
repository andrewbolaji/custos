import { ChatInput } from "./components/ChatInput";
import { DemoBanner } from "./components/DemoBanner";
import { ErrorBanner } from "./components/ErrorBanner";
import { MessageList } from "./components/MessageList";
import { WelcomeScreen } from "./components/WelcomeScreen";
import { useChat } from "./hooks/useChat";

export default function App() {
  const {
    state,
    sendMessage,
    cancelStream,
    retry,
    clearError,
    approveAction,
    rejectAction,
  } = useChat();
  const hasMessages = state.messages.length > 0;

  return (
    <div className="app">
      <DemoBanner />
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
      <footer className="chat-footer">
        <ChatInput
          status={state.status}
          onSend={sendMessage}
          onCancel={cancelStream}
        />
      </footer>
    </div>
  );
}
