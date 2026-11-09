import { Eye, EyeOff, Lock, Mail, ShieldCheck } from 'lucide-react';
import { useState, type FormEvent } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import { useToast } from '../components/Toast';
import { ApiError } from '../lib/api';

export default function LoginPage() {
  const navigate = useNavigate();
  const { login } = useAuth();
  const { toast } = useToast();

  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      await login(email, password);
      toast('Welcome back!', 'success');
      navigate('/');
    } catch (err) {
      const msg = err instanceof ApiError ? err.message : 'Login failed. Please try again.';
      setError(msg);
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="login-page">
      <form className="login-card" onSubmit={handleSubmit}>
        <div className="brand-mark">S</div>
        <span className="eyebrow">YOUR VOICE. YOUR MEANING. PROTECTED.</span>
        <h1>Welcome back</h1>
        <p className="muted">Sign in to your SASAA Guardian workspace.</p>

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
            placeholder="Enter your password"
            autoComplete="current-password"
            required
            style={{ paddingRight: 44 }}
          />
          <button
            type="button"
            onClick={() => setShowPassword((p) => !p)}
            style={{
              position: 'absolute', right: 13, top: '50%', transform: 'translateY(-50%)',
              background: 'none', border: 0, color: '#746c83', padding: 0, cursor: 'pointer',
            }}
          >
            {showPassword ? <EyeOff size={16} /> : <Eye size={16} />}
          </button>
        </div>

        {error && (
          <div className="alert error" style={{ marginTop: 14, borderRadius: 8, padding: '10px 14px', background: '#2d0a0a', border: '1px solid #5c1010' }}>
            {error}
          </div>
        )}

        <button className="primary full" disabled={loading}>
          {loading ? 'Signing in…' : 'Sign in'}
        </button>

        <p className="muted small" style={{ textAlign: 'center', marginTop: 20 }}>
          No account?{' '}
          <Link to="/register" style={{ color: '#a77af5', textDecoration: 'none', fontWeight: 600 }}>
            Create one free
          </Link>
        </p>

        <p className="muted small" style={{ textAlign: 'center', marginTop: 20, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 6 }}>
          <ShieldCheck size={12} />
          SASAA AI Voice Note Guardian · v1.0
        </p>
      </form>
    </main>
  );
}
