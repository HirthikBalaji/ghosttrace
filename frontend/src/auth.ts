// Authentication for the UI. Production: OpenID Connect authorization code + PKCE (oidc-client-ts), tokens kept in
// sessionStorage and sent as `Authorization: Bearer`. Local demo: the shared demo header (never real auth).
import { UserManager, WebStorageStateStore } from "oidc-client-ts";

const MODE = (import.meta.env.VITE_AUTH_MODE as string | undefined) ?? "demo";
const AUTHORITY = import.meta.env.VITE_OIDC_AUTHORITY as string | undefined;
const CLIENT_ID = import.meta.env.VITE_OIDC_CLIENT_ID as string | undefined;
const SCOPE = (import.meta.env.VITE_OIDC_SCOPE as string | undefined) ?? "openid profile email";

export const authMode: "oidc" | "demo" = MODE === "oidc" ? "oidc" : "demo";

let manager: UserManager | null = null;
function mgr(): UserManager {
  if (!manager) {
    if (!AUTHORITY || !CLIENT_ID) throw new Error("VITE_OIDC_AUTHORITY and VITE_OIDC_CLIENT_ID are required in oidc mode");
    manager = new UserManager({
      authority: AUTHORITY,
      client_id: CLIENT_ID,
      redirect_uri: `${window.location.origin}/`,
      post_logout_redirect_uri: `${window.location.origin}/`,
      response_type: "code",
      scope: SCOPE,
      automaticSilentRenew: true,
      userStore: new WebStorageStateStore({ store: window.sessionStorage }),
    });
  }
  return manager;
}

let accessToken: string | null = null;

/** Completes a login redirect if present; returns true when the user is signed in. */
export async function initAuth(): Promise<boolean> {
  if (authMode === "demo") return true;
  const m = mgr();
  const params = new URLSearchParams(window.location.search);
  if (params.has("code") && params.has("state")) {
    const user = await m.signinRedirectCallback();
    window.history.replaceState({}, document.title, window.location.pathname + window.location.hash);
    accessToken = user.access_token;
    return true;
  }
  const user = await m.getUser();
  if (user && !user.expired) {
    accessToken = user.access_token;
    m.events.addUserLoaded((u) => { accessToken = u.access_token; });
    return true;
  }
  return false;
}

export const signIn = () => mgr().signinRedirect();
export const signOut = () => mgr().signoutRedirect();

export function authHeaders(): Record<string, string> {
  if (authMode === "oidc") return accessToken ? { Authorization: `Bearer ${accessToken}` } : {};
  const token = (import.meta.env.VITE_GT_DEMO_TOKEN as string | undefined) ?? "dev-demo-token";
  return { "X-GT-Demo-Token": token };
}
