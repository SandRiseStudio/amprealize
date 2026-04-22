import { createContext } from 'react';
import type {
  ActorIdentity,
  ConsentDecision,
  ConsentRequest,
  DeviceCodeResponse,
  DeviceFlowStatus,
} from '../types/auth';

export interface AuthContextValue {
  isAuthenticated: boolean;
  isInitialized: boolean;
  isLoading: boolean;
  actor: ActorIdentity | null;
  error: string | null;

  deviceFlowStatus: DeviceFlowStatus;
  deviceCode: DeviceCodeResponse | null;
  startLogin: () => Promise<void>;
  cancelLogin: () => void;

  loginWithClientCredentials: (clientId: string, clientSecret: string) => Promise<void>;

  completeOAuthLogin: (code: string, state?: string) => Promise<void>;

  logout: () => Promise<void>;
  refreshToken: () => Promise<boolean>;

  hasPendingConsent: boolean;
  nextConsentRequest: ConsentRequest | null;
  respondToConsent: (requestId: string, decision: ConsentDecision, note?: string) => Promise<void>;

  getAccessToken: () => string | null;
  getValidAccessToken: () => Promise<string | null>;
}

export const AuthContext = createContext<AuthContextValue | null>(null);
