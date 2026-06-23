import React, { useEffect, useMemo, useState } from "react";
import { useNavigate, Link } from "react-router-dom";
import { useAuth } from "../auth";
import { Brand } from "../Layout";
import { Sparkle, ArrowRight } from "@phosphor-icons/react";

function GoogleAuthButton({ mode, setErr }) {
  const { loginWithGoogle } = useAuth();
  const navigate = useNavigate();
  const [googleReady, setGoogleReady] = useState(false);
  const googleClientId = useMemo(
    () => String(process.env.REACT_APP_GOOGLE_CLIENT_ID || "").replace(/^["'`]+|["'`]+$/g, "").trim(),
    [],
  );
  const buttonId = mode === "register" ? "googleRegisterDiv" : "googleSignInDiv";

  useEffect(() => {
    const cid = googleClientId;
    if (!cid) return;
    const id = "google-gsi";
    const existing = document.getElementById(id);
    if (!existing) {
      const s = document.createElement("script");
      s.id = id;
      s.src = "https://accounts.google.com/gsi/client";
      s.async = true;
      s.defer = true;
      s.onload = () => setGoogleReady(true);
      document.body.appendChild(s);
      return;
    }
    if (window.google?.accounts?.id) setGoogleReady(true);
    else {
      const onReady = window.setInterval(() => {
        if (window.google?.accounts?.id) {
          window.clearInterval(onReady);
          setGoogleReady(true);
        }
      }, 200);
      return () => window.clearInterval(onReady);
    }
  }, [googleClientId]);

  useEffect(() => {
    const cid = googleClientId;
    if (!googleReady || !cid) return;
    let pollId = null;
    let timeoutId = null;
    const mountGoogleButton = () => {
      if (!window.google?.accounts?.id) return false;
      window.google.accounts.id.initialize({
        client_id: cid,
        callback: async (resp) => {
          try {
            await loginWithGoogle(resp.credential);
            navigate("/");
          } catch (e) {
            const detail = e?.response?.data?.detail;
            const status = e?.response?.status;
            const prefix = mode === "register" ? "Google sign-up failed" : "Google sign-in failed";
            if (detail) setErr(String(detail));
            else if (status) setErr(`${prefix} (HTTP ${status})`);
            else setErr(`${prefix} (${e?.message || "Network/CORS error"})`);
          }
        },
      });
      const el = document.getElementById(buttonId);
      if (el) {
        el.innerHTML = "";
        window.google.accounts.id.renderButton(el, {
          theme: "outline",
          size: "large",
          width: 360,
          text: mode === "register" ? "signup_with" : "signin_with",
        });
      }
      return true;
    };
    if (!mountGoogleButton()) {
      pollId = window.setInterval(() => {
        if (mountGoogleButton()) {
          window.clearInterval(pollId);
          pollId = null;
        }
      }, 250);
      timeoutId = window.setTimeout(() => {
        if (pollId) {
          window.clearInterval(pollId);
        }
      }, 5000);
    }
    return () => {
      if (pollId) window.clearInterval(pollId);
      if (timeoutId) window.clearTimeout(timeoutId);
    };
  }, [buttonId, googleClientId, googleReady, loginWithGoogle, mode, navigate, setErr]);

  if (!googleClientId) return null;
  return (
    <>
      <div className="divider my-5" />
      <div className="flex justify-center" id={buttonId} data-testid={mode === "register" ? "google-register-btn" : "google-login-btn"} />
    </>
  );
}

export function Login() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [err, setErr] = useState("");
  const [loading, setLoading] = useState(false);

  const submit = async (e) => {
    e.preventDefault(); setErr(""); setLoading(true);
    try { await login(email, password); navigate("/"); }
    catch (e) {
      const detail = e?.response?.data?.detail;
      const status = e?.response?.status;
      if (detail) setErr(String(detail));
      else if (status) setErr(`Login failed (HTTP ${status})`);
      else setErr(`Login failed (${e?.message || "Network error"})`);
    }
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
          <GoogleAuthButton mode="login" setErr={setErr} />
          <div className="text-center mt-5 text-sm text-slate-400">
            New to the team? <Link className="text-[#3FA9F5] hover:underline" to="/register" data-testid="go-register-link">Create an account</Link>
          </div>
        </form>
      </div>
    </div>
  );
}

export function Register() {
  const { register } = useAuth();
  const navigate = useNavigate();
  const [form, setForm] = useState({ name: "", email: "", password: "" });
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
        <p className="text-slate-400 text-sm mb-6">Map Ranking team access only. The first user becomes admin automatically; all other new users start as Account Managers.</p>
        <label className="label">Name</label>
        <input className="input mt-1.5 mb-3" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required data-testid="register-name-input" />
        <label className="label">Email</label>
        <input type="email" className="input mt-1.5 mb-3" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} required data-testid="register-email-input" />
        <label className="label">Password</label>
        <input type="password" className="input mt-1.5 mb-3" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} required data-testid="register-password-input" />
        {err && <div className="text-red-400 text-sm" data-testid="register-error">{err}</div>}
        <button type="submit" className="btn-primary w-full mt-4" disabled={loading} data-testid="register-submit-btn">{loading ? "Creating…" : "Create account"}</button>
        <GoogleAuthButton mode="register" setErr={setErr} />
        <div className="text-center mt-5 text-sm text-slate-400">
          Already have an account? <Link className="text-[#3FA9F5] hover:underline" to="/login" data-testid="go-login-link">Sign in</Link>
        </div>
      </form>
    </div>
  );
}
