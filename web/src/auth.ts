import { initializeApp, getApps } from "firebase/app";
import {
  getAuth,
  GoogleAuthProvider,
  signInWithPopup,
  signOut,
  onAuthStateChanged,
  type User,
} from "firebase/auth";

const firebaseConfig = {
  apiKey: import.meta.env.VITE_FIREBASE_API_KEY,
  authDomain: import.meta.env.VITE_FIREBASE_AUTH_DOMAIN,
  projectId: import.meta.env.VITE_FIREBASE_PROJECT_ID,
};

if (!getApps().length) {
  initializeApp(firebaseConfig);
}

const auth = getAuth();
const provider = new GoogleAuthProvider();

export async function signIn(): Promise<void> {
  await signInWithPopup(auth, provider);
}

export async function signOutUser(): Promise<void> {
  await signOut(auth);
}

export async function getIdToken(): Promise<string | null> {
  const user = auth.currentUser;
  if (!user) return null;
  return user.getIdToken();
}

export async function getRole(): Promise<string | null> {
  // Ask the API for the effective role — it applies the default-admins policy, so this is
  // the single source of truth (a raw token claim would miss default-admins with no claim set).
  const token = await getIdToken();
  if (!token) return null;
  const base = import.meta.env.VITE_API_BASE as string;
  try {
    const r = await fetch(`${base}/me`, { headers: { Authorization: `Bearer ${token}` } });
    if (!r.ok) return null;
    const data = await r.json();
    return (data.role as string) ?? null;
  } catch {
    return null;
  }
}

export function onAuthChanged(callback: (user: User | null) => void): () => void {
  return onAuthStateChanged(auth, callback);
}

export { auth };
