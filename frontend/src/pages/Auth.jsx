import React, { useState } from "react";
import { useNavigate, Link } from "react-router-dom";
import { useAuth } from "../auth";
import { Brand } from "../Layout";
import { Sparkle, ArrowRight } from "@phosphor-icons/react";

export function Login() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState("admin@monthlytouchos.com");
  const [password, setPassword] = useState("ChangeMe!2026");
  const [err, setErr] = useState("");
  const [loading, setLoading] = useState(false);

  const submit = async (e) => {
    e.preventDefault(); setErr(""); setLoading(true);
    try { await login(email, password); navigate("/"); }
    catch (e) { setErr(e?.response?.data?.detail || "Login failed"); }
    finally { setLoading(false); }
  };

  return (
    <div className="app-bg min-h-screen grid lg:grid-cols-2">
      <div
        className="hidden lg:flex flex-col justify-between p-10 relative border-r border-white/5"
        style={{
          background:
            "radial-gradient(900px 600px at 12% 18%, rgba(63,169,245,0.22), transparent 55%), radial-gradient(900px 600px at 82% 78%, rgba(47,224,194,0.18), transparent 52%), linear-gradient(180deg, rgba(2,6,23,0.92), rgba(2,6,23,0.92))",
        }}
      >
        <Brand />
        <div>
          <div className="chip chip-info mb-3"><Sparkle size={12} weight="fill" /> Senior Client Success OS</div>
          <h2 className="text-4xl font-bold tracking-tight leading-tight max-w-md">Transform Monthly Touch Meetings into <span style={{ color: "#2FE0C2" }}>strategic growth conversations.</span></h2>
          <p className="text-slate-300 mt-3 max-w-md">AI-prepared briefs. Auto-extracted action items. Testimonial detection. One operating system for retention.</p>
        </div>
        <div className="text-xs text-slate-500">© Monthly Touch OS — Powered by Map Ranking</div>
      </div>
      <div className="flex items-center justify-center p-8">
        <form onSubmit={submit} className="w-full max-w-md card-flat p-7" data-testid="login-form">
          <div className="lg:hidden mb-6"><Brand /></div>
          <h1 className="text-2xl font-bold mb-1">Welcome back</h1>
          <p className="text-slate-400 text-sm mb-6">Sign in to your operating system.</p>
          <label className="label">Email</label>
          <input type="email" className="input mt-1.5 mb-4" value={email} onChange={(e) => setEmail(e.target.value)} required data-testid="login-email-input" />
          <label className="label">Password</label>
          <input type="password" className="input mt-1.5 mb-2" value={password} onChange={(e) => setPassword(e.target.value)} required data-testid="login-password-input" />
          {err && <div className="text-red-400 text-sm my-2" data-testid="login-error">{err}</div>}
          <button type="submit" className="btn-primary w-full mt-4 flex items-center justify-center gap-2" disabled={loading} data-testid="login-submit-btn">
            {loading ? "Signing in…" : "Sign in"} <ArrowRight size={16} weight="bold" />
          </button>
          <div className="text-center mt-5 text-sm text-slate-400">
            New to the team? <Link className="text-[#3FA9F5] hover:underline" to="/register" data-testid="go-register-link">Create an account</Link>
          </div>
          <div className="mt-6 p-3 rounded-lg border border-white/5 bg-white/[0.02] text-xs text-slate-400">
            <strong className="text-slate-200">Bootstrap admin:</strong> admin@monthlytouchos.com / ChangeMe!2026
          </div>
        </form>
      </div>
    </div>
  );
}

export function Register() {
  const { register } = useAuth();
  const navigate = useNavigate();
  const [form, setForm] = useState({ name: "", email: "", password: "", role: "manager" });
  const [err, setErr] = useState(""); const [loading, setLoading] = useState(false);

  const submit = async (e) => {
    e.preventDefault(); setErr(""); setLoading(true);
    try { await register(form); navigate("/"); }
    catch (e) { setErr(e?.response?.data?.detail || "Registration failed"); }
    finally { setLoading(false); }
  };

  return (
    <div className="app-bg min-h-screen flex items-center justify-center p-6">
      <form onSubmit={submit} className="w-full max-w-md card-flat p-7" data-testid="register-form">
        <Brand />
        <h1 className="text-2xl font-bold mt-6 mb-1">Create your account</h1>
        <p className="text-slate-400 text-sm mb-6">First user becomes admin automatically.</p>
        <label className="label">Name</label>
        <input className="input mt-1.5 mb-3" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required data-testid="register-name-input" />
        <label className="label">Email</label>
        <input type="email" className="input mt-1.5 mb-3" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} required data-testid="register-email-input" />
        <label className="label">Password</label>
        <input type="password" className="input mt-1.5 mb-3" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} required data-testid="register-password-input" />
        <label className="label">Role</label>
        <select className="input mt-1.5 mb-3" value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })} data-testid="register-role-select">
          <option value="manager">Account Manager</option>
          <option value="admin">Admin</option>
        </select>
        {err && <div className="text-red-400 text-sm" data-testid="register-error">{err}</div>}
        <button type="submit" className="btn-primary w-full mt-4" disabled={loading} data-testid="register-submit-btn">{loading ? "Creating…" : "Create account"}</button>
        <div className="text-center mt-5 text-sm text-slate-400">
          Already have an account? <Link className="text-[#3FA9F5] hover:underline" to="/login" data-testid="go-login-link">Sign in</Link>
        </div>
      </form>
    </div>
  );
}
