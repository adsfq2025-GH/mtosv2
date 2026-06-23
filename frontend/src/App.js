import React, { useEffect } from "react";
import "@/App.css";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { AuthProvider, useAuth } from "@/auth";
import Layout from "@/Layout";
import { Login, Register } from "@/pages/Auth";
import Dashboard from "@/pages/Dashboard";
import { ClientsList, ClientDetail } from "@/pages/Clients";
import MeetingDetail from "@/pages/MeetingDetail";
import { MeetingsList, Actions, Integrations, DocsHub } from "@/pages/Others";
import FollowUp from "@/pages/FollowUp";
import Opportunities from "@/pages/Opportunities";
import Testimonials from "@/pages/Testimonials";
import Strategy from "@/pages/Strategy";
import WinsLibrary from "@/pages/WinsLibrary";
import IssuesLibrary from "@/pages/IssuesLibrary";
import WhiteLabel from "@/pages/WhiteLabel";
import AiVisibility from "@/pages/AiVisibility";
import PromptCenter from "@/pages/PromptCenter";
import { applyDisplayMode, getSavedDisplayMode } from "@/displayMode";
import { canManageAdminSurfaces } from "@/rbac";

function Protected({ children }) {
  const { user, loading } = useAuth();
  if (loading) return <div className="app-bg min-h-screen flex items-center justify-center text-slate-400">Loading…</div>;
  if (!user) return <Navigate to="/login" replace />;
  return <Layout>{children}</Layout>;
}

function AdminOnly({ children }) {
  const { user, loading } = useAuth();
  if (loading) return <div className="app-bg min-h-screen flex items-center justify-center text-slate-400">Loading…</div>;
  if (!user) return <Navigate to="/login" replace />;
  if (!canManageAdminSurfaces(user)) return <Navigate to="/" replace />;
  return <Layout>{children}</Layout>;
}

export default function App() {
  useEffect(() => {
    try {
      applyDisplayMode(getSavedDisplayMode());
    } catch (e) {}
  }, []);
  return (
    <BrowserRouter>
      <AuthProvider>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/register" element={<Register />} />
          <Route path="/" element={<Protected><Dashboard /></Protected>} />
          <Route path="/clients" element={<Protected><ClientsList /></Protected>} />
          <Route path="/clients/:id" element={<Protected><ClientDetail /></Protected>} />
          <Route path="/meetings" element={<Protected><MeetingsList /></Protected>} />
          <Route path="/meetings/:id" element={<Protected><MeetingDetail /></Protected>} />
          <Route path="/actions" element={<Protected><Actions /></Protected>} />
          <Route path="/follow-up" element={<Protected><FollowUp /></Protected>} />
          <Route path="/opportunities" element={<Protected><Opportunities /></Protected>} />
          <Route path="/testimonials" element={<Protected><Testimonials /></Protected>} />
          <Route path="/wins" element={<Protected><WinsLibrary /></Protected>} />
          <Route path="/issues" element={<Protected><IssuesLibrary /></Protected>} />
          <Route path="/strategy" element={<Protected><Strategy /></Protected>} />
          <Route path="/white-label" element={<AdminOnly><WhiteLabel /></AdminOnly>} />
          <Route path="/ai-visibility" element={<AdminOnly><AiVisibility /></AdminOnly>} />
          <Route path="/prompt-center" element={<AdminOnly><PromptCenter /></AdminOnly>} />
          <Route path="/content" element={<Navigate to="/opportunities" replace />} />
          <Route path="/integrations" element={<AdminOnly><Integrations /></AdminOnly>} />
          <Route path="/docs" element={<Protected><DocsHub /></Protected>} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  );
}
