import React, { createContext, useContext, useEffect, useState } from "react";
import { auth as authApi } from "./api";

const AuthCtx = createContext(null);

function persistAuthResponse(response) {
  const token = response?.token || "";
  if (token) localStorage.setItem("mtos_token", token);
  else localStorage.removeItem("mtos_token");
  if (response?.refresh_token) localStorage.setItem("mtos_refresh_token", response.refresh_token);
  else localStorage.removeItem("mtos_refresh_token");
  if (response?.user) localStorage.setItem("mtos_user", JSON.stringify(response.user));
  else localStorage.removeItem("mtos_user");
}

export function AuthProvider({ children }) {
  const [user, setUser] = useState(() => {
    const raw = localStorage.getItem("mtos_user");
    return raw ? JSON.parse(raw) : null;
  });
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const t = localStorage.getItem("mtos_token");
    if (!t) { setLoading(false); return; }
    authApi.me().then((u) => {
      setUser(u); localStorage.setItem("mtos_user", JSON.stringify(u));
    }).catch((e) => {
      localStorage.removeItem("mtos_token"); localStorage.removeItem("mtos_refresh_token"); localStorage.removeItem("mtos_user"); setUser(null);
    }).finally(() => setLoading(false));
  }, []);

  const login = async (email, password) => {
    const r = await authApi.login(email, password);
    persistAuthResponse(r);
    setUser(r.user);
    return r.user;
  };
  const loginWithGoogle = async (credential) => {
    const r = await authApi.google(credential);
    persistAuthResponse(r);
    setUser(r.user);
    return r.user;
  };
  const register = async (payload) => {
    const r = await authApi.register(payload);
    persistAuthResponse(r);
    setUser(r.user);
    return r.user;
  };
  const logout = () => {
    localStorage.removeItem("mtos_token");
    localStorage.removeItem("mtos_refresh_token");
    localStorage.removeItem("mtos_user");
    setUser(null);
  };

  return <AuthCtx.Provider value={{ user, loading, login, loginWithGoogle, register, logout }}>{children}</AuthCtx.Provider>;
}

export const useAuth = () => useContext(AuthCtx);
