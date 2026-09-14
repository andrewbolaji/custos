interface WelcomeScreenProps {
  onSuggestedQuestion: (query: string) => void;
}

const SUGGESTED_QUESTIONS = [
  { label: "People", query: "What is the PTO accrual rate for new employees?" },
  { label: "Facilities", query: "How much does a water heater replacement cost?" },
  { label: "Safety", query: "What are the emergency gas leak procedures?" },
  { label: "Warranty", query: "What warranty do you provide on labor?" },
];

export function WelcomeScreen({ onSuggestedQuestion }: WelcomeScreenProps) {
  return (
    <div className="welcome-screen">
      <div className="welcome-content">
        <div className="welcome-intro">
          <p className="welcome-kicker">Your documents</p>
          <h1 className="welcome-title">Answers you can trust.</h1>
          <p className="welcome-subtitle">
            Ask a question in plain language. Custos answers from approved
            company documents and shows the citations behind the response.
          </p>
          <div className="welcome-steps" aria-label="How Custos works">
            <span><b>01</b> Ask</span>
            <span><b>02</b> Inspect</span>
            <span><b>03</b> Verify</span>
          </div>
        </div>
        <div className="question-panel">
          <div className="question-panel-head">
            <p className="suggested-label">Try asking</p>
            <span>Sample documents</span>
          </div>
          <div className="suggested-questions">
            {SUGGESTED_QUESTIONS.map(({ label, query }, index) => (
              <button
                key={query}
                className="suggested-btn"
                onClick={() => onSuggestedQuestion(query)}
              >
                <span className="question-index">0{index + 1}</span>
                <span className="question-copy">
                  <span className="question-label">{label}</span>
                  <span>{query}</span>
                </span>
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                  <path d="M5 12h14M13 6l6 6-6 6" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              </button>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
