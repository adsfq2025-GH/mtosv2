import React from "react";
import "@/App.css";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { AuthProvider, useAuth } from "@/auth";
import Layout from "@/Layout";
import { Login, Register } from "@/pages/Auth";
import Dashboard from "@/pages/Dashboard";
import { ClientsList, ClientDetail } from "@/pages/Clients";
import MeetingDetail from "@/pages/MeetingDetail";
import { MeetingsList, Actions, ContentQueue, Integrations, DocsHub } from "@/pages/Others";

function Protected({ children }) {
  const { user, loading } = useAuth();
  if (loading) return <div className="app-bg min-h-screen flex items-center justify-center text-slate-400">Loading…</div>;
  if (!user) return <Navigate to="/login" replace />;
  return <Layout>{children}</Layout>;
}

export default function App() {
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
          <Route path="/content" element={<Protected><ContentQueue /></Protected>} />
          <Route path="/integrations" element={<Protected><Integrations /></Protected>} />
          <Route path="/docs" element={<Protected><DocsHub /></Protected>} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  );
}
