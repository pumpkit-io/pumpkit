import { useState } from 'react';
import { Link } from 'react-router-dom';
import { motion, AnimatePresence } from 'framer-motion';
import { ArrowLeft, Send, CheckCircle, Sparkles, Clock, Zap, Bell } from 'lucide-react';
import { apiService } from '../services/apiService';

export function Waitlist() {
  const [email, setEmail] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isSubmitted, setIsSubmitted] = useState(false);
  const [error, setError] = useState('');

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');

    if (!email || !email.includes('@')) {
      setError('Please enter a valid email address');
      return;
    }

    setIsSubmitting(true);

    try {
      await apiService.post('/waitlist', { email });
      setIsSubmitting(false);
      setIsSubmitted(true);
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Something went wrong. Please try again.');
      setIsSubmitting(false);
    }
  };

  return (
    <div className="waitlist-page">
      {/* Animated background */}
      <div className="fixed inset-0 overflow-hidden pointer-events-none">
        <div className="aurora aurora-1" />
        <div className="aurora aurora-2" />
        <div className="aurora aurora-3" />
        <div className="grid-overlay" />
        <div className="noise-overlay" />
        <div className="particles">
          {[...Array(20)].map((_, i) => (
            <div key={i} className="particle" style={{
              left: `${Math.random() * 100}%`,
              animationDelay: `${Math.random() * 20}s`,
              animationDuration: `${15 + Math.random() * 20}s`,
            }} />
          ))}
        </div>
      </div>

      {/* Back to home link */}
      <motion.div
        initial={{ opacity: 0, x: -20 }}
        animate={{ opacity: 1, x: 0 }}
        transition={{ duration: 0.6, delay: 0.1 }}
        className="back-link-container"
      >
        <Link to="/" className="back-link">
          <ArrowLeft className="w-4 h-4" />
          <span>Back to home</span>
        </Link>
      </motion.div>

      {/* Main content */}
      <div className="waitlist-container">
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.8, delay: 0.2 }}
          className="logo-container"
        >
          <span className="text-2xl font-bold tracking-tight text-white">YourApp</span>
        </motion.div>

        <AnimatePresence mode="wait">
          {!isSubmitted ? (
            <motion.div
              key="form"
              initial={{ opacity: 0, y: 30 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -20, scale: 0.95 }}
              transition={{ duration: 0.8, delay: 0.3 }}
              className="content-card"
            >
              <div className="card-glow" />
              <div className="card-inner">
                <div className="status-badge">
                  <Clock className="w-4 h-4" />
                  <span>Coming Soon</span>
                </div>

                <h1>
                  Be the first to
                  <br />
                  <span className="gradient-text">experience it</span>
                </h1>

                <p className="subtitle">
                  We're putting the finishing touches on something great.
                  Join the waitlist to get early access.
                </p>

                <form onSubmit={handleSubmit} className="email-form">
                  <div className="input-wrapper">
                    <div className="input-glow" />
                    <input
                      type="email"
                      value={email}
                      onChange={(e) => setEmail(e.target.value)}
                      placeholder="Enter your email"
                      className={error ? 'error' : ''}
                      disabled={isSubmitting}
                    />
                    <button
                      type="submit"
                      disabled={isSubmitting || !email}
                      className="submit-button"
                    >
                      {isSubmitting ? (
                        <div className="spinner" />
                      ) : (
                        <>
                          <span>Join waitlist</span>
                          <Send className="w-4 h-4" />
                        </>
                      )}
                    </button>
                  </div>
                  {error && (
                    <motion.p
                      initial={{ opacity: 0, y: -10 }}
                      animate={{ opacity: 1, y: 0 }}
                      className="error-message"
                    >
                      {error}
                    </motion.p>
                  )}
                </form>

                <div className="features-preview">
                  <div className="feature-item">
                    <Zap className="w-4 h-4" />
                    <span>Early access</span>
                  </div>
                  <div className="feature-item">
                    <Sparkles className="w-4 h-4" />
                    <span>Exclusive perks</span>
                  </div>
                  <div className="feature-item">
                    <Bell className="w-4 h-4" />
                    <span>Launch updates</span>
                  </div>
                </div>
              </div>
            </motion.div>
          ) : (
            <motion.div
              key="success"
              initial={{ opacity: 0, scale: 0.9, y: 20 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              transition={{ duration: 0.6, ease: [0.22, 1, 0.36, 1] }}
              className="success-card"
            >
              <div className="card-glow success-glow" />
              <div className="card-inner">
                <motion.div
                  initial={{ scale: 0 }}
                  animate={{ scale: 1 }}
                  transition={{ duration: 0.5, delay: 0.2, type: 'spring', stiffness: 200 }}
                  className="success-icon"
                >
                  <CheckCircle className="w-16 h-16" />
                </motion.div>

                <motion.h2
                  initial={{ opacity: 0, y: 20 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.5, delay: 0.4 }}
                >
                  You're on the list!
                </motion.h2>

                <motion.p
                  initial={{ opacity: 0, y: 20 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.5, delay: 0.5 }}
                >
                  We'll notify you at <strong>{email}</strong> as soon as we're ready for you.
                </motion.p>

                <motion.div
                  initial={{ opacity: 0, y: 20 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.5, delay: 0.6 }}
                  className="success-cta"
                >
                  <Link to="/" className="back-home-button">
                    <ArrowLeft className="w-4 h-4" />
                    Back to home
                  </Link>
                </motion.div>
              </div>
            </motion.div>
          )}
        </AnimatePresence>

        <motion.p
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ duration: 0.8, delay: 0.8 }}
          className="footer-note"
        >
          No spam, ever. We'll only email you about launch updates.
        </motion.p>
      </div>

      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=Instrument+Sans:wght@400;500;600;700&family=Sora:wght@300;400;500;600;700&display=swap');

        .waitlist-page {
          --color-bg: #030308;
          --color-bg-elevated: rgba(15, 15, 25, 0.8);
          --color-text: #f0f0f5;
          --color-text-muted: #8888a0;
          --color-accent: #a78bfa;
          --color-accent-bright: #c4b5fd;
          --color-accent-dim: rgba(139, 92, 246, 0.15);
          --color-success: #34d399;
          --color-error: #f87171;

          font-family: 'Instrument Sans', -apple-system, BlinkMacSystemFont, sans-serif;
          background: var(--color-bg);
          color: var(--color-text);
          min-height: 100vh;
          display: flex;
          flex-direction: column;
          align-items: center;
          justify-content: center;
          overflow-x: hidden;
          position: relative;
          padding: 2rem;
        }

        .aurora {
          position: absolute;
          width: 100%;
          height: 100%;
          opacity: 0.5;
          filter: blur(120px);
          will-change: transform;
        }

        .aurora-1 {
          background: radial-gradient(ellipse at 30% 30%, rgba(139, 92, 246, 0.4) 0%, transparent 50%);
          animation: aurora1 20s ease-in-out infinite;
        }

        .aurora-2 {
          background: radial-gradient(ellipse at 70% 60%, rgba(59, 130, 246, 0.3) 0%, transparent 50%);
          animation: aurora2 25s ease-in-out infinite;
        }

        .aurora-3 {
          background: radial-gradient(ellipse at 50% 80%, rgba(168, 85, 247, 0.25) 0%, transparent 50%);
          animation: aurora3 30s ease-in-out infinite;
        }

        @keyframes aurora1 {
          0%, 100% { transform: translate(0, 0) scale(1); }
          33% { transform: translate(5%, 5%) scale(1.1); }
          66% { transform: translate(-5%, 2%) scale(0.95); }
        }

        @keyframes aurora2 {
          0%, 100% { transform: translate(0, 0) scale(1); }
          33% { transform: translate(-8%, 3%) scale(1.05); }
          66% { transform: translate(4%, -4%) scale(1.1); }
        }

        @keyframes aurora3 {
          0%, 100% { transform: translate(0, 0) scale(1); }
          50% { transform: translate(3%, -5%) scale(1.08); }
        }

        .grid-overlay {
          position: absolute;
          inset: 0;
          background-image:
            linear-gradient(rgba(255, 255, 255, 0.02) 1px, transparent 1px),
            linear-gradient(90deg, rgba(255, 255, 255, 0.02) 1px, transparent 1px);
          background-size: 50px 50px;
          mask-image: radial-gradient(ellipse at center, black 0%, transparent 70%);
        }

        .noise-overlay {
          position: absolute;
          inset: 0;
          background-image: url("data:image/svg+xml,%3Csvg viewBox='0 0 256 256' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='noise'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23noise)'/%3E%3C/svg%3E");
          opacity: 0.03;
          mix-blend-mode: overlay;
        }

        .particles {
          position: absolute;
          inset: 0;
          overflow: hidden;
        }

        .particle {
          position: absolute;
          width: 4px;
          height: 4px;
          background: var(--color-accent);
          border-radius: 50%;
          opacity: 0.3;
          animation: float linear infinite;
        }

        @keyframes float {
          0% {
            transform: translateY(100vh) rotate(0deg);
            opacity: 0;
          }
          10% { opacity: 0.3; }
          90% { opacity: 0.3; }
          100% {
            transform: translateY(-100vh) rotate(720deg);
            opacity: 0;
          }
        }

        .back-link-container {
          position: fixed;
          top: 2rem;
          left: 2rem;
          z-index: 100;
        }

        .back-link {
          display: flex;
          align-items: center;
          gap: 0.5rem;
          color: var(--color-text-muted);
          text-decoration: none;
          font-size: 0.9rem;
          font-weight: 500;
          padding: 0.5rem 1rem;
          border-radius: 8px;
          background: rgba(255, 255, 255, 0.03);
          border: 1px solid rgba(255, 255, 255, 0.06);
          transition: all 0.3s ease;
        }

        .back-link:hover {
          color: var(--color-text);
          background: rgba(255, 255, 255, 0.06);
          border-color: rgba(255, 255, 255, 0.1);
          transform: translateX(-4px);
        }

        .waitlist-container {
          position: relative;
          z-index: 10;
          display: flex;
          flex-direction: column;
          align-items: center;
          width: 100%;
          max-width: 480px;
        }

        .logo-container {
          margin-bottom: 2rem;
        }

        .content-card,
        .success-card {
          position: relative;
          width: 100%;
        }

        .card-glow {
          position: absolute;
          inset: -40%;
          background: radial-gradient(ellipse at center, rgba(139, 92, 246, 0.2) 0%, transparent 60%);
          filter: blur(60px);
          z-index: -1;
        }

        .success-glow {
          background: radial-gradient(ellipse at center, rgba(52, 211, 153, 0.15) 0%, transparent 60%);
        }

        .card-inner {
          background: linear-gradient(135deg, rgba(20, 20, 35, 0.95) 0%, rgba(15, 15, 25, 0.9) 100%);
          border: 1px solid rgba(139, 92, 246, 0.15);
          border-radius: 24px;
          padding: 3rem;
          backdrop-filter: blur(20px);
          box-shadow:
            0 0 0 1px rgba(255, 255, 255, 0.03),
            0 25px 80px -12px rgba(0, 0, 0, 0.5);
        }

        .status-badge {
          display: inline-flex;
          align-items: center;
          gap: 0.5rem;
          padding: 0.5rem 1rem;
          background: var(--color-accent-dim);
          border: 1px solid rgba(139, 92, 246, 0.25);
          border-radius: 100px;
          font-size: 0.8rem;
          font-weight: 600;
          color: var(--color-accent-bright);
          margin-bottom: 1.5rem;
          text-transform: uppercase;
          letter-spacing: 0.05em;
        }

        .content-card h1 {
          font-family: 'Sora', sans-serif;
          font-size: 2.25rem;
          font-weight: 600;
          line-height: 1.2;
          letter-spacing: -0.02em;
          margin: 0 0 1rem;
        }

        .gradient-text {
          background: linear-gradient(135deg, var(--color-accent) 0%, #60a5fa 50%, var(--color-accent-bright) 100%);
          -webkit-background-clip: text;
          -webkit-text-fill-color: transparent;
          background-clip: text;
        }

        .subtitle {
          font-size: 1rem;
          line-height: 1.7;
          color: var(--color-text-muted);
          margin: 0 0 2rem;
        }

        .email-form {
          margin-bottom: 2rem;
        }

        .input-wrapper {
          position: relative;
          display: flex;
          gap: 0.75rem;
        }

        .input-glow {
          position: absolute;
          inset: -2px;
          background: linear-gradient(135deg, var(--color-accent), #60a5fa, var(--color-accent-bright));
          border-radius: 14px;
          opacity: 0;
          transition: opacity 0.3s ease;
          z-index: -1;
        }

        .input-wrapper:focus-within .input-glow {
          opacity: 0.5;
          filter: blur(8px);
        }

        .email-form input {
          flex: 1;
          background: rgba(0, 0, 0, 0.3);
          border: 1px solid rgba(255, 255, 255, 0.1);
          border-radius: 12px;
          padding: 1rem 1.25rem;
          font-family: inherit;
          font-size: 1rem;
          color: var(--color-text);
          transition: all 0.3s ease;
          outline: none;
        }

        .email-form input::placeholder {
          color: var(--color-text-muted);
        }

        .email-form input:focus {
          border-color: rgba(139, 92, 246, 0.5);
          background: rgba(0, 0, 0, 0.4);
        }

        .email-form input.error {
          border-color: var(--color-error);
        }

        .email-form input:disabled {
          opacity: 0.6;
          cursor: not-allowed;
        }

        .submit-button {
          display: flex;
          align-items: center;
          justify-content: center;
          gap: 0.5rem;
          background: linear-gradient(135deg, #8b5cf6 0%, #7c3aed 50%, #6d28d9 100%);
          color: white;
          font-family: inherit;
          font-size: 0.95rem;
          font-weight: 600;
          padding: 1rem 1.5rem;
          border-radius: 12px;
          border: none;
          cursor: pointer;
          transition: all 0.3s ease;
          white-space: nowrap;
          box-shadow:
            0 0 0 1px rgba(139, 92, 246, 0.5),
            0 4px 15px rgba(139, 92, 246, 0.25),
            inset 0 1px 0 rgba(255, 255, 255, 0.2);
        }

        .submit-button:hover:not(:disabled) {
          transform: translateY(-2px);
          box-shadow:
            0 0 0 1px rgba(139, 92, 246, 0.6),
            0 8px 30px rgba(139, 92, 246, 0.35),
            inset 0 1px 0 rgba(255, 255, 255, 0.2);
        }

        .submit-button:disabled {
          opacity: 0.6;
          cursor: not-allowed;
          transform: none;
        }

        .spinner {
          width: 20px;
          height: 20px;
          border: 2px solid rgba(255, 255, 255, 0.3);
          border-top-color: white;
          border-radius: 50%;
          animation: spin 0.8s linear infinite;
        }

        @keyframes spin {
          to { transform: rotate(360deg); }
        }

        .error-message {
          color: var(--color-error);
          font-size: 0.875rem;
          margin: 0.75rem 0 0;
        }

        .features-preview {
          display: flex;
          justify-content: center;
          gap: 1.5rem;
          flex-wrap: wrap;
        }

        .feature-item {
          display: flex;
          align-items: center;
          gap: 0.5rem;
          font-size: 0.85rem;
          color: var(--color-text-muted);
        }

        .feature-item svg {
          color: var(--color-accent);
        }

        .success-card .card-inner {
          text-align: center;
          border-color: rgba(52, 211, 153, 0.2);
        }

        .success-icon {
          display: inline-flex;
          align-items: center;
          justify-content: center;
          width: 80px;
          height: 80px;
          background: rgba(52, 211, 153, 0.1);
          border-radius: 50%;
          margin-bottom: 1.5rem;
          color: var(--color-success);
        }

        .success-card h2 {
          font-family: 'Sora', sans-serif;
          font-size: 1.75rem;
          font-weight: 600;
          margin: 0 0 1rem;
          color: var(--color-success);
        }

        .success-card p {
          color: var(--color-text-muted);
          line-height: 1.7;
          margin: 0 0 2rem;
        }

        .success-card p strong {
          color: var(--color-text);
        }

        .success-cta {
          display: flex;
          justify-content: center;
        }

        .back-home-button {
          display: inline-flex;
          align-items: center;
          gap: 0.5rem;
          color: var(--color-text-muted);
          text-decoration: none;
          font-size: 0.95rem;
          font-weight: 500;
          padding: 0.75rem 1.25rem;
          border-radius: 10px;
          background: rgba(255, 255, 255, 0.05);
          border: 1px solid rgba(255, 255, 255, 0.1);
          transition: all 0.3s ease;
        }

        .back-home-button:hover {
          color: var(--color-text);
          background: rgba(255, 255, 255, 0.08);
          transform: translateX(-4px);
        }

        .footer-note {
          margin-top: 2rem;
          font-size: 0.8rem;
          color: var(--color-text-muted);
          opacity: 0.7;
        }

        @media (max-width: 640px) {
          .waitlist-page {
            padding: 1.5rem;
          }

          .back-link-container {
            top: 1rem;
            left: 1rem;
          }

          .card-inner {
            padding: 2rem;
          }

          .content-card h1 {
            font-size: 1.75rem;
          }

          .input-wrapper {
            flex-direction: column;
          }

          .submit-button {
            width: 100%;
            padding: 1rem;
          }

          .features-preview {
            gap: 1rem;
          }
        }
      `}</style>
    </div>
  );
}
