import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import { initAuth, signIn } from "./auth";
import "./styles.css";

const root = createRoot(document.getElementById("root")!);

function SignIn({ error }: { error?: string }) {
  return (
    <main className="state" style={{ maxWidth: 520, margin: "12vh auto" }}>
      <h1>GHOSTTRACE</h1>
      <p>Sign in with your organisation's identity provider to continue.</p>
      {error && <p className="state err" role="alert">{error}</p>}
      <button className="btn primary" onClick={() => signIn()}>Sign in</button>
    </main>
  );
}

initAuth()
  .then((ok) => root.render(<StrictMode>{ok ? <App /> : <SignIn />}</StrictMode>))
  .catch((e: Error) => root.render(<SignIn error={`Sign-in failed: ${e.message}`} />));

