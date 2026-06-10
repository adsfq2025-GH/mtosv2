import { createClient } from "@supabase/supabase-js";

const supabaseUrl = String(process.env.REACT_APP_SUPABASE_URL || "").trim();
const supabasePublishableKey = String(process.env.REACT_APP_SUPABASE_PUBLISHABLE_KEY || "").trim();
const supabaseEnabled = String(process.env.REACT_APP_SUPABASE_ENABLED || "false").trim().toLowerCase() === "true";

let browserClient = null;

export const SUPABASE_CONFIG = Object.freeze({
  url: supabaseUrl,
  publishableKey: supabasePublishableKey,
  enabled: supabaseEnabled,
});

export function isSupabaseConfigured() {
  return Boolean(SUPABASE_CONFIG.enabled && SUPABASE_CONFIG.url && SUPABASE_CONFIG.publishableKey);
}

export function getSupabaseBrowserClient() {
  if (!isSupabaseConfigured()) {
    return null;
  }

  if (!browserClient) {
    browserClient = createClient(SUPABASE_CONFIG.url, SUPABASE_CONFIG.publishableKey, {
      auth: {
        autoRefreshToken: false,
        detectSessionInUrl: false,
        persistSession: false,
      },
      global: {
        headers: {
          "X-Client-Info": "mtos-cra-phase1",
        },
      },
      realtime: {
        params: {
          eventsPerSecond: 10,
        },
      },
    });
  }

  return browserClient;
}
