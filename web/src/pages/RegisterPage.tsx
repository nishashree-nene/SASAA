import { Eye, EyeOff, Lock, Mail, User } from 'lucide-react';
import { useState, type FormEvent } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import { useToast } from '../components/Toast';
import { ApiError } from '../lib/api';

function passwordStrength(pw: string): { score: number; label: string } {
  let score = 0;
  if (pw.length >= 8) score++;
  if (/[0-9]/.test(pw)) score++;
  if (/[A-Z]/.test(pw)) score++;
  if (/[^A-Za-z0-9]/.test(pw)) score++;
  const labels = ['', 'Weak', 'Fair', 'Good', 'Strong'];
  return { score, label: labels[score] ?? '' };
}

const STRENGTH_CLASSES = ['', 'filled-weak', 'filled-fair', 'filled-good', 'filled-strong'];

export default function RegisterPage() {
  const navigate = useNavigate();
  const { register } = useAuth();
  const { toast } = useToast();

  const [fullName, setFullName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [agreed, setAgreed] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const { score, label: strengthLabel } = passwordStrength(password);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError('');

    if (!fullName.trim()) { setError('Full name is required.'); return; }
    if (password !== confirmPassword) { setError('Passwords do not match.'); return; }
    if (!agreed) { setError('Please agree to the terms to continue.'); return; }

    setLoading(true);
    try {
      await register(email, password, fullName.trim());
      toast('Account created! Welcome to SASAA.', 'success');
      navigate('/');
    } catch (err) {
      const msg = err instanceof ApiError ? err.message : 'Registration failed. Please try again.';
      setError(msg);
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="login-page">
      <form className="login-card" onSubmit={handleSubmit}>
        <div className="brand-mark">S</div>
        <span className="eyebrow">AI VOICE NOTE GUARDIAN</span>
        <h1>Create your account</h1>
        <p className="muted">Join SASAA to protect every voice message.</p>

        <label>
          <User size={13} style={{ marginRight: 6, verticalAlign: 'middle' }} />
          Full name
        </label>
        <input
          value={fullName}
          onChange={(e) => setFullName(e.target.value)}
          placeholder="Your full name"
          autoComplete="name"
          required
        />

        <label>
          <Mail size={13} style={{ marginRight: 6, verticalAlign: 'middle' }} />
          Email address
        </label>
        <input
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          placeholder="you@example.com"
          autoComplete="email"
          required
        />

        <label>
          <Lock size={13} style={{ marginRight: 6, verticalAlign: 'middle' }} />
          Password
        </label>
        <div style={{ position: 'relative' }}>
          <input
            type={showPassword ? 'text' : 'password'}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="Min. 8 characters, include a number"
            autoComplete="new-password"
            required
            minLength={8}
            style={{ paddingRight: 44 }}
          />
          <button
            type="button"
            onClick={() => setShowPassword((p) => !p)}
            style={{ position: 'absolute', right: 13, top: '50%', transform: 'translateY(-50%)', background: 'none', border: 0, color: '#746c83', padding: 0, cursor: 'pointer' }}
          >
            {showPassword ? <EyeOff size={16} /> : <Eye size={16} />}
          </button>
        </div>
        {password && (
          <>
            <div className="password-strength" style={{ marginTop: 8 }}>
              {[1, 2, 3, 4].map((i) => (
                <div key={i} className={`strength-bar ${i <= score ? STRENGTH_CLASSES[score] : ''}`} />
              ))}
            </div>
            <p className="strength-label">{strengthLabel}</p>
          </>
        )}

        <label>Confirm password</label>
        <input
          type="password"
          value={confirmPassword}
          onChange={(e) => setConfirmPassword(e.target.value)}
          placeholder="Repeat your password"
          autoComplete="new-password"
          required
        />

        <label style={{ display: 'flex', alignItems: 'flex-start', gap: 10, marginTop: 18, cursor: 'pointer' }}>
          <input
            type="checkbox"
            checked={agreed}
            onChange={(e) => setAgreed(e.target.checked)}
            style={{ width: 'auto', marginTop: 2 }}
          />
          <span className="muted small">
            I agree to SASAA's terms of service and privacy policy. Voice recordings are processed securely.
          </span>
        </label>

        {error && (
          <div className="alert error" style={{ marginTop: 14, borderRadius: 8, padding: '10px 14px', background: '#2d0a0a', border: '1px solid #5c1010' }}>
            {error}
          </div>
        )}

        <button className="primary full" disabled={loading}>
          {loading ? 'Creating account…' : 'Create account'}
        </button>

        <p className="muted small" style={{ textAlign: 'center', marginTop: 20 }}>
          Already have an account?{' '}
          <Link to="/login" style={{ color: '#a77af5', textDecoration: 'none', fontWeight: 600 }}>
            Sign in
          </Link>
        </p>
      </form>
    </main>
  );
}
