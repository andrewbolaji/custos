interface ErrorBannerProps {
  message: string;
  onRetry: () => void;
  onDismiss: () => void;
}

export function ErrorBanner({ message, onRetry, onDismiss }: ErrorBannerProps) {
  return (
    <div className="error-banner" role="alert">
      <p className="error-text">Something went wrong: {message}</p>
      <div className="error-actions">
        <button className="btn btn-retry" onClick={onRetry}>
          Retry
        </button>
        <button className="btn btn-dismiss" onClick={onDismiss}>
          Dismiss
        </button>
      </div>
    </div>
  );
}
