/* ---------------------------------------------------------------------------
   Who is signed in, and which desk they belong to.

   One provider at the root holds the session, so no page fetches identity
   for itself and no two parts of the interface can disagree about which desk
   they are showing.

   The organisation here is for display and for deciding what to show. It is
   never sent to the server as a claim about who the caller is - the server
   reads that from the signed token - so a tampered value in this store
   changes what the interface renders, and nothing about what the API returns.
   --------------------------------------------------------------------------- */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import { api, setSessionExpiredHandler, token } from "../api/client";

export interface User {
  id: number;
  name: string;
  email: string;
  role: "OWNER" | "MEMBER" | "VIEWER";
  is_super_admin: boolean;
  is_active: boolean;
  last_login_at: string | null;
}

export interface Organisation {
  id: number;
  slug: string;
  name: string;
  status: "ACTIVE" | "SUSPENDED";
  timezone: string;
  company_email: string | null;
  company_phone: string | null;
  company_signatory: string | null;
  crawl_active_from: string;
  crawl_active_to: string;
  crawl_active_minutes: number;
  crawl_quiet_minutes: number;
  crawl_enabled: boolean;
}

interface Session {
  access_token: string;
  user: User;
  organisation: Organisation | null;
}

interface AuthValue {
  user: User | null;
  organisation: Organisation | null;
  /** True until the stored token has been checked, so the app does not flash
   *  the sign-in page at somebody who is already signed in. */
  loading: boolean;
  signIn: (email: string, password: string) => Promise<void>;
  acceptInvite: (token: string, name: string, password: string) => Promise<void>;
  signOut: () => void;
  setOrganisation: (organisation: Organisation) => void;
  /** Owners and the platform operator may change team and settings. */
  canAdminister: boolean;
  /** VIEWER accounts can read everything and change nothing. */
  readOnly: boolean;
}

const AuthContext = createContext<AuthValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [organisation, setOrganisationState] = useState<Organisation | null>(null);
  const [loading, setLoading] = useState(true);

  const signOut = useCallback(() => {
    token.clear();
    setUser(null);
    setOrganisationState(null);
  }, []);

  // A 401 from any request means the session is over. Handled once, here,
  // rather than by every caller.
  useEffect(() => setSessionExpiredHandler(signOut), [signOut]);

  // Restore a session on load, so a refresh does not sign anybody out.
  useEffect(() => {
    if (!token.get()) {
      setLoading(false);
      return;
    }
    api
      .get<Session>("/auth/me")
      .then((session) => {
        setUser(session.user);
        setOrganisationState(session.organisation);
      })
      .catch(() => token.clear())
      .finally(() => setLoading(false));
  }, []);

  const adopt = useCallback((session: Session) => {
    token.set(session.access_token);
    setUser(session.user);
    setOrganisationState(session.organisation);
  }, []);

  const signIn = useCallback(
    async (email: string, password: string) => {
      adopt(await api.post<Session>("/auth/login", { email, password }));
    },
    [adopt],
  );

  const acceptInvite = useCallback(
    async (inviteToken: string, name: string, password: string) => {
      adopt(
        await api.post<Session>("/auth/accept-invite", {
          token: inviteToken,
          name,
          password,
        }),
      );
    },
    [adopt],
  );

  const value = useMemo<AuthValue>(
    () => ({
      user,
      organisation,
      loading,
      signIn,
      acceptInvite,
      signOut,
      setOrganisation: setOrganisationState,
      canAdminister: !!user && (user.is_super_admin || user.role === "OWNER"),
      readOnly: !!user && user.role === "VIEWER",
    }),
    [user, organisation, loading, signIn, acceptInvite, signOut],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthValue {
  const value = useContext(AuthContext);
  if (!value) {
    throw new Error("useAuth must be used inside an AuthProvider.");
  }
  return value;
}
