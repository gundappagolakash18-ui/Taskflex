import { useEffect, useRef, useState } from "react";
import { authApi } from "@/api/auth";

interface GoogleIdApi {
  initialize: (config: {
    client_id: string;
    callback: (response: { credential: string }) => void;
  }) => void;
  renderButton: (parent: HTMLElement, options: Record<string, unknown>) => void;
}

declare global {
  interface Window {
    google?: { accounts: { id: GoogleIdApi } };
  }
}

let configPromise: Promise<{ enabled: boolean; client_id: string | null }> | null = null;
let scriptPromise: Promise<GoogleIdApi> | null = null;

function getGoogleConfig() {
  configPromise ??= authApi.googleConfig();
  return configPromise;
}

function loadGsiScript(): Promise<GoogleIdApi> {
  if (window.google?.accounts?.id) return Promise.resolve(window.google.accounts.id);
  scriptPromise ??= new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = "https://accounts.google.com/gsi/client";
    script.async = true;
    script.onload = () => resolve(window.google!.accounts.id);
    script.onerror = () => {
      scriptPromise = null;
      reject(new Error("Failed to load Google Identity Services"));
    };
    document.head.appendChild(script);
  });
  return scriptPromise;
}

interface Props {
  text?: "signin_with" | "signup_with";
  onCredential: (credential: string) => void;
}

export default function GoogleSignInButton({ text = "signin_with", onCredential }: Props) {
  const buttonRef = useRef<HTMLDivElement>(null);
  const credentialRef = useRef(onCredential);
  credentialRef.current = onCredential;
  const [ready, setReady] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const config = await getGoogleConfig();
        if (!config.enabled || !config.client_id) return;
        const gsi = await loadGsiScript();
        if (cancelled || !buttonRef.current) return;
        gsi.initialize({
          client_id: config.client_id,
          callback: (response) => credentialRef.current(response.credential),
        });
        gsi.renderButton(buttonRef.current, {
          theme: "outline",
          size: "large",
          text,
          shape: "pill",
          width: 320,
          logo_alignment: "center",
        });
        setReady(true);
      } catch {
        // Google sign-in is optional UI; hide the block on any failure.
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [text]);

  return (
    <div className={ready ? "" : "hidden"}>
      <div className="my-5 flex items-center gap-3">
        <div className="h-px flex-1 bg-slate-200" />
        <span className="text-xs font-medium uppercase tracking-wide text-slate-400">or</span>
        <div className="h-px flex-1 bg-slate-200" />
      </div>
      <div ref={buttonRef} className="flex justify-center" />
    </div>
  );
}
