import { Logo } from "./Logo";

interface WelcomeScreenProps {
  onSuggestedQuestion: (query: string) => void;
}

const SUGGESTED_QUESTIONS = [
  "What is the PTO accrual rate for new employees?",
  "How much does a water heater replacement cost?",
  "What are the emergency gas leak procedures?",
  "What warranty do you provide on labor?",
];

export function WelcomeScreen({ onSuggestedQuestion }: WelcomeScreenProps) {
  return (
    <div className="welcome-screen">
      <div className="welcome-content">
        <div className="welcome-logo">
          <Logo size={48} />
        </div>
        <h1 className="welcome-title">Custos</h1>
        <p className="welcome-subtitle">
          Ask questions about your company documents. Answers are grounded in
          real sources with citations you can verify.
        </p>
        <div className="suggested-questions">
          <p className="suggested-label">Try asking</p>
          {SUGGESTED_QUESTIONS.map((q) => (
            <button
              key={q}
              className="suggested-btn"
              onClick={() => onSuggestedQuestion(q)}
            >
              {q}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
