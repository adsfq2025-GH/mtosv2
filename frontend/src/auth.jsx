import React, { createContext, useContext, useEffect, useState } from "react";
import { auth as authApi } from "./api";

const AuthCtx = createContext(null);

// #region debug-point D:auth-debug
const dbgAuth = (hypothesisId, location, msg, data = {}) =>
  fetch("http://127.0.0.1:7777/event", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      sessionId: "google-login-blankpage",
      runId: "pre-fix",
      hypothesisId,
      location,
      msg: `[DEBUG] ${msg}`,
      data,
      ts: Date.now(),
    }),
  }).catch(() => {});
// #endregion

export function AuthProvider({ children }) {
  const [user, setUser] = useState(() => {
    const raw = localStorage.getItem("mtos_user");
    return raw ? JSON.parse(raw) : null;
  });
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const t = localStorage.getItem("mtos_token");
    // #region debug-point D:auth-restore-start
    dbgAuth("D", "auth.jsx:restore", "auth_restore_start", { hasToken: !!t });
    // #endregion
    if (!t) { setLoading(false); return; }
    authApi.me().then((u) => {
      // #region debug-point D:auth-restore-ok
      dbgAuth("D", "auth.jsx:restore", "auth_restore_ok", { userId: u?.id, email: u?.email });
      // #endregion
      setUser(u); localStorage.setItem("mtos_user", JSON.stringify(u));
    }).catch((e) => {
      // #region debug-point D:auth-restore-fail
      dbgAuth("D", "auth.jsx:restore", "auth_restore_fail", { status: e?.response?.status, detail: e?.response?.data?.detail, message: e?.message });
      // #endregion
      localStorage.removeItem("mtos_token"); localStorage.removeItem("mtos_user"); setUser(null);
    }).finally(() => setLoading(false));
  }, []);

  const login = async (email, password) => {
    const r = await authApi.login(email, password);
    localStorage.setItem("mtos_token", r.token);
    localStorage.setItem("mtos_user", JSON.stringify(r.user));
    setUser(r.user);
    return r.user;
  };
  const loginWithGoogle = async (credential) => {
    // #region debug-point A:google-login-submit
    dbgAuth("A", "auth.jsx:loginWithGoogle", "google_login_submit", { hasCredential: !!credential, credentialLength: String(credential || "").length });
    // #endregion
    const r = await authApi.google(credential);
    // #region debug-point A:google-login-ok
    dbgAuth("A", "auth.jsx:loginWithGoogle", "google_login_ok", { userId: r?.user?.id, email: r?.user?.email, hasToken: !!r?.token });
    // #endregion
    localStorage.setItem("mtos_token", r.token);
    localStorage.setItem("mtos_user", JSON.stringify(r.user));
    setUser(r.user);
    return r.user;
  };
  const register = async (payload) => {
    const r = await authApi.register(payload);
    localStorage.setItem("mtos_token", r.token);
    localStorage.setItem("mtos_user", JSON.stringify(r.user));
    setUser(r.user);
    return r.user;
  };
  const logout = () => {
    localStorage.removeItem("mtos_token");
    localStorage.removeItem("mtos_user");
    setUser(null);
  };

  return <AuthCtx.Provider value={{ user, loading, login, loginWithGoogle, register, logout }}>{children}</AuthCtx.Provider>;
}

export const useAuth = () => useContext(AuthCtx);
